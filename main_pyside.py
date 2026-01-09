from __future__ import annotations
import os
os.environ["QT_API"] = "pyside6"


import logging
import inspect
import uuid
import sys
import time
import traceback
import smtplib
import subprocess
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, Union, get_args, get_origin
from skinnervation3d_fractal_tasks.tasks import fit_surface, count_number_fiber_crossing

from pydantic import BaseModel, Field, ValidationError, create_model

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QDoubleSpinBox,
    QSplitter,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

# =============================================================================
# 0) Plug your tasks here
# =============================================================================
#
# For now, I include a tiny demo task and show how to register your
# init_correct_illumination once it’s importable in this environment.
#
# Replace the DEMO task(s) with imports like:
#   from your_pkg.init_correct_illumination import init_correct_illumination
#

def demo_task(*, zarr_urls: list[str], zarr_dir: str, sleep_s: float = 0.5) -> dict[str, Any]:
    """Demo task: sleeps a bit and returns the chosen zarr url."""
    time.sleep(max(sleep_s, 0.0))
    logger.info(f"Demo task: sleeping {sleep_s} seconds")
    return {"zarr_urls": zarr_urls, "zarr_dir": zarr_dir}


# Example: once you can import your task, register it like this:
# from your_module import init_correct_illumination

TASK_FUNCTIONS: List[Callable[..., Any]] = [
    demo_task,
    fit_surface.fit_surface,
    count_number_fiber_crossing.count_number_fiber_crossing,
    # init_correct_illumination,
]

HIDDEN_WORKFLOW_FIELDS = {"zarr_dir", "zarr_url", "zarr_urls"}


# =============================================================================
# 1) Email (optional)
# =============================================================================

@dataclass(frozen=True)
class EmailConfig:
    enabled: bool
    to_address: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    use_tls: bool = True
    from_address: Optional[str] = None


def load_email_config(to_address: str) -> EmailConfig:
    enabled = bool(to_address.strip())
    return EmailConfig(
        enabled=enabled,
        to_address=to_address.strip(),
        smtp_host=os.environ.get("WF_SMTP_HOST", ""),
        smtp_port=int(os.environ.get("WF_SMTP_PORT", "587")),
        smtp_user=os.environ.get("WF_SMTP_USER", ""),
        smtp_password=os.environ.get("WF_SMTP_PASS", ""),
        use_tls=True,
        from_address=os.environ.get("WF_SMTP_FROM", None),
    )


def send_email(cfg: EmailConfig, subject: str, body: str) -> None:
    if not cfg.enabled or not cfg.to_address.strip():
        return
    if not cfg.smtp_host:
        raise RuntimeError("SMTP host missing (WF_SMTP_HOST).")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["To"] = cfg.to_address
    msg["From"] = cfg.from_address or cfg.smtp_user or cfg.to_address
    msg.set_content(body)

    if cfg.use_tls:
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30) as s:
            s.starttls()
            if cfg.smtp_user:
                s.login(cfg.smtp_user, cfg.smtp_password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30) as s:
            if cfg.smtp_user:
                s.login(cfg.smtp_user, cfg.smtp_password)
            s.send_message(msg)


# =============================================================================
# 2) TaskSpec: auto model from function signature
# =============================================================================

@dataclass(frozen=True)
class TaskSpec:
    key: str
    title: str
    description: str
    fn: Callable[..., Any]
    model: Type[BaseModel]  # auto-generated from fn signature


def _safe_doc_firstline(fn: Callable[..., Any]) -> str:
    doc = inspect.getdoc(fn) or ""
    return doc.splitlines()[0] if doc else ""


def build_model_from_signature(fn: Callable[..., Any]) -> Type[BaseModel]:
    """
    Create a Pydantic model from a callable signature:
      - respects type hints
      - uses defaults
      - keyword-only args are included normally
    """
    sig = inspect.signature(fn)
    type_hints = getattr(fn, "__annotations__", {})

    fields: Dict[str, Tuple[Any, Any]] = {}

    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue

        ann = type_hints.get(name, Any)

        if param.default is inspect._empty:
            # required
            fields[name] = (ann, ...)
        else:
            # default
            # If there's no type info, still accept Any
            fields[name] = (ann, param.default)

    model_name = f"{fn.__name__}_Params"
    return create_model(model_name, **fields)  # type: ignore[arg-type]


def build_task_specs(fns: List[Callable[..., Any]]) -> List[TaskSpec]:
    specs: List[TaskSpec] = []
    for fn in fns:
        specs.append(
            TaskSpec(
                key=fn.__name__,
                title=fn.__name__,
                description=_safe_doc_firstline(fn),
                fn=fn,
                model=build_model_from_signature(fn),
            )
        )
    return specs


TASKS: List[TaskSpec] = build_task_specs(TASK_FUNCTIONS)


# =============================================================================
# 3) Pydantic -> widgets (basic types)
# =============================================================================

def _unwrap_optional(tp: Any) -> Any:
    origin = get_origin(tp)
    if origin is Union:
        args = [a for a in get_args(tp) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return tp


def build_widgets_from_model(model_cls: Type[BaseModel]) -> Dict[str, QWidget]:
    """
    Supports: int, float, bool, str, list[str] (nice for zarr_urls).
    """
    widgets: Dict[str, QWidget] = {}

    for name, field in model_cls.model_fields.items():
        if name in HIDDEN_WORKFLOW_FIELDS:
            continue
        ann = _unwrap_optional(field.annotation)
        default = field.default
        desc = field.description or ""

        # list[str] support (simple comma/newline separated input)
        if get_origin(ann) is list and (get_args(ann) == (str,) or get_args(ann) == (Any,)):
            w = QTextEdit()
            w.setFixedHeight(70)
            if default not in (None, ...):
                if isinstance(default, list):
                    w.setPlainText("\n".join(map(str, default)))
                else:
                    w.setPlainText(str(default))
            if desc:
                w.setToolTip(desc)
            widgets[name] = w
            continue

        if ann is int:
            w = QSpinBox()
            # You can add constraints later if you use Field(ge/le)
            if default not in (None, ...):
                w.setValue(int(default))

        elif ann is float:
            w = QDoubleSpinBox()
            w.setDecimals(6)
            if default not in (None, ...):
                w.setValue(float(default))

        elif ann is bool:
            w = QCheckBox()
            if default not in (None, ...):
                w.setChecked(bool(default))

        elif ann is str:
            w = QLineEdit()
            if default not in (None, ...):
                w.setText(str(default))

        else:
            # Fallback: text input
            w = QLineEdit()
            if default not in (None, ...):
                w.setText(str(default))
            w.setPlaceholderText(f"Unsupported type {ann!r} → treated as text")

        if desc:
            w.setToolTip(desc)

        # Make workflow-scoped fields read-only in the UI
        if name in {"zarr_dir", "zarr_url", "zarr_urls"}:
            w.setEnabled(False)
        widgets[name] = w

    return widgets


def read_widget_value(widget: QWidget, expected_type: Any) -> Any:
    # list[str] text area
    if isinstance(widget, QTextEdit):
        txt = widget.toPlainText().strip()
        if not txt:
            return []
        # allow newline or comma separation
        parts = []
        for line in txt.splitlines():
            for chunk in line.split(","):
                chunk = chunk.strip()
                if chunk:
                    parts.append(chunk)
        return parts

    if isinstance(widget, QSpinBox):
        return int(widget.value())
    if isinstance(widget, QDoubleSpinBox):
        return float(widget.value())
    if isinstance(widget, QCheckBox):
        return bool(widget.isChecked())
    if isinstance(widget, QLineEdit):
        return widget.text()
    raise TypeError(f"Unsupported widget: {type(widget)}")


# =============================================================================
# 4) Worker: runs tasks sequentially, frozen UI, logs, status, optional email, optional visualize
# =============================================================================

class WorkflowWorker(QObject):
    log = Signal(str)
    task_started = Signal(int, int, str)
    task_finished = Signal(int, int, str)
    finished = Signal(bool, str)

    def __init__(
        self,
        analysis_dir: Path,
        plan: List[Tuple[TaskSpec, BaseModel]],
        auto_visualize: bool,
        email_cfg: EmailConfig,
    ):
        super().__init__()
        self.analysis_dir = analysis_dir
        self.plan = plan
        self.auto_visualize = auto_visualize
        self.email_cfg = email_cfg
        self._cancelled = False

        # If tasks return an output path, we can store it here
        self._last_path: Optional[Path] = None

    def cancel(self) -> None:
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    @Slot()
    def run(self) -> None:
        total = len(self.plan)
        ok = True
        final = "Success"

        self.log.emit(f"=== Workflow started ({total} task(s)) ===")
        self.log.emit(f"Directory: {self.analysis_dir}")

        try:
            for i, (task, params_model) in enumerate(self.plan, start=1):
                if self.is_cancelled():
                    ok = False
                    final = "Cancelled"
                    self.log.emit("Cancellation requested. Stopping.")
                    break

                self.task_started.emit(i, total, task.title)
                self.log.emit(f"[{i}/{total}] START {task.title}")
                self.log.emit(f"  params: {params_model.model_dump()}")

                # Call the task: your validate_call wrapper will validate again internally.
                out = task.fn(**params_model.model_dump())

                # Heuristic: if output contains a path, store it
                self._last_path = self._extract_output_path(out) or self._last_path

                self.log.emit(f"[{i}/{total}] DONE  {task.title}")
                self.task_finished.emit(i, total, task.title)

            # Auto-visualize hook
            if ok and self.auto_visualize:
                if self._last_path is None:
                    self.log.emit("Auto-visualize enabled, but no output path detected.")
                else:
                    self.log.emit(f"Auto-visualize: opening in napari: {self._last_path}")
                    try:
                        subprocess.Popen([sys.executable, "-m", "napari", str(self._last_path)])
                    except Exception as e:
                        self.log.emit(f"Auto-visualize failed: {e!r}")

            # Email notification
            if self.email_cfg.enabled and self.email_cfg.to_address.strip():
                subject = f"Workflow finished: {final}"
                body = f"Directory: {self.analysis_dir}\nResult: {final}\n"
                try:
                    send_email(self.email_cfg, subject, body)
                    self.log.emit("Email notification sent.")
                except Exception as e:
                    self.log.emit(f"Email notification failed: {e!r}")

        except Exception:
            ok = False
            final = "Failed"
            self.log.emit("ERROR:\n" + traceback.format_exc())

        self.log.emit(f"=== Workflow finished: {final} ===")
        self.finished.emit(ok, final)

    def _extract_output_path(self, out: Any) -> Optional[Path]:
        """
        Best-effort extraction:
        - If out is dict and contains something like output_zarr_url/zarr_url/path, use it.
        - If it contains parallelization_list, use first item's zarr_url.
        You can customize for your conventions.
        """
        try:
            if isinstance(out, dict):
                # common keys
                for k in ("output_path", "output_zarr_url", "output_zarr", "zarr_url", "path"):
                    if k in out and out[k]:
                        return Path(str(out[k]))

                # fractal init convention
                if "parallelization_list" in out and isinstance(out["parallelization_list"], list) and out["parallelization_list"]:
                    first = out["parallelization_list"][0]
                    if isinstance(first, dict) and "zarr_url" in first:
                        return Path(str(first["zarr_url"]))
        except Exception:
            return None
        return None


# =============================================================================
# 5) Opening dialog: choose analysis directory → open workflow window
# =============================================================================

class OpeningDialog(QDialog):
    dir_selected = Signal(Path)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("SkInnervation3D\n Workflow Runner")

        title = QLabel("<h2>Workflow Runner</h2>")
        desc = QLabel(
            "Select a directory to start processing files in it.\n"
            "Once selected, the workflow window will open."
        )
        desc.setWordWrap(True)

        self.dir_line = QLineEdit()
        self.dir_line.setReadOnly(True)
        self.dir_line.setPlaceholderText("No directory selected")

        choose_btn = QPushButton("Choose directory…")
        choose_btn.clicked.connect(self.choose_dir)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(desc)
        layout.addSpacing(12)
        layout.addWidget(self.dir_line)
        layout.addWidget(choose_btn)

        self.resize(520, 220)

    def choose_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select analysis directory")
        if not folder:
            return
        p = Path(folder)
        self.dir_line.setText(str(p))
        self.dir_selected.emit(p)
        self.accept()


# =============================================================================
# 6) Workflow window
# =============================================================================

class WorkflowWindow(QMainWindow):
    def __init__(self, analysis_dir: Path, tasks: List[TaskSpec]):
        super().__init__()
        self.setWindowTitle("Workflow Runner — Workflow")

        self.analysis_dir = analysis_dir
        self.tasks = tasks
        self.tasks_by_key: Dict[str, TaskSpec] = {t.key: t for t in self.tasks}

        # workflow ordered task ids
        self.workflow_ids: List[str] = []
        self.task_by_id: Dict[str, TaskSpec] = {} #task_id => task {t.key: t for t in self.tasks}
        self.params_by_id: dict[str, dict[str, Any]] = {}  # workflow_id -> param values

        # thread/worker
        self.thread: Optional[QThread] = None
        self.worker: Optional[WorkflowWorker] = None

        # toolbar: auto visualize + email
        tb = QToolBar("Main")
        self.addToolBar(tb)

        self.auto_vis_chk = QCheckBox("Auto-visualize at end")
        self.auto_vis_chk.setChecked(False)
        tb.addWidget(self.auto_vis_chk)

        tb.addSeparator()

        tb.addWidget(QLabel("Email to:"))
        self.email_to = QLineEdit()
        self.email_to.setPlaceholderText("optional@example.org")
        self.email_to.setFixedWidth(240)
        tb.addWidget(self.email_to)

        # central UI
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        top_label = QLabel(f"<b>Analysis directory:</b> {self.analysis_dir}")
        top_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        main_layout.addWidget(top_label)

        # Panels: Available / Workflow / Parameters
        splitter = QSplitter(Qt.Horizontal)

        # left: available tasks
        left_box = QGroupBox("Available tasks")
        left_layout = QVBoxLayout(left_box)
        self.available_list = QListWidget()
        for t in self.tasks:
            item = QListWidgetItem(t.title)
            item.setData(Qt.UserRole + 1, t.key)
            item.setToolTip(t.description)
            self.available_list.addItem(item)
        left_layout.addWidget(self.available_list)

        # middle: workflow tasks
        mid_box = QGroupBox("Workflow (runs top → bottom)")
        mid_layout = QVBoxLayout(mid_box)
        self.workflow_list = QListWidget()
        self.workflow_list.currentItemChanged.connect(self.on_workflow_selected)
        mid_layout.addWidget(self.workflow_list)

        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("Add →")
        self.add_btn.clicked.connect(self.add_task)
        self.remove_btn = QPushButton("← Remove")
        self.remove_btn.clicked.connect(self.remove_task)
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.remove_btn)
        mid_layout.addLayout(btn_row)

        move_row = QHBoxLayout()
        self.up_btn = QPushButton("Move up")
        self.up_btn.clicked.connect(self.move_up)
        self.down_btn = QPushButton("Move down")
        self.down_btn.clicked.connect(self.move_down)
        move_row.addWidget(self.up_btn)
        move_row.addWidget(self.down_btn)
        mid_layout.addLayout(move_row)

        # right: params
        right_box = QGroupBox("Parameters")
        right_layout = QVBoxLayout(right_box)

        self.params_title = QLabel("Select a workflow task to edit parameters.")
        self.params_title.setWordWrap(True)
        right_layout.addWidget(self.params_title)

        self.form_container = QWidget()
        self.form_layout = QFormLayout(self.form_container)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.form_container)
        right_layout.addWidget(scroll)

        splitter.addWidget(left_box)
        splitter.addWidget(mid_box)
        splitter.addWidget(right_box)
        splitter.setSizes([300, 430, 520])
        main_layout.addWidget(splitter, 2)

        # Run row
        run_row = QHBoxLayout()
        
        # Zarr selector: scan *.zarr under analysis dir
        self.zarr_image_combo = QComboBox()
        self.zarr_image_combo.addItem("Select zarr image…", None)  # placeholder
        self.zarr_image_combo.addItem("No zarr image (conversion task)", "__NO_ZARR__")
        self.zarr_image_combo.currentIndexChanged.connect(self._on_zarr_image_changed)
        self.refresh_zarr_images_btn = QPushButton("Refresh")
        self.refresh_zarr_images_btn.clicked.connect(self._populate_images_choices)

        # Run/cancel button
        self.run_btn = QPushButton("Run workflow")
        self.run_btn.clicked.connect(self.run_workflow)
        self.run_btn.setEnabled(False)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_workflow)
        
        run_row.addWidget(QLabel("Dataset:"))
        run_row.addWidget(self.zarr_image_combo, 1)
        run_row.addWidget(self.refresh_zarr_images_btn)
        run_row.addSpacing(12)        
        run_row.addWidget(self.run_btn)
        run_row.addWidget(self.cancel_btn)
        run_row.addStretch(1)
        main_layout.addLayout(run_row)

        # bottom: status + logs
        bottom_split = QSplitter(Qt.Horizontal)

        status_box = QGroupBox("Task status")
        status_layout = QVBoxLayout(status_box)
        self.status_list = QListWidget()
        status_layout.addWidget(self.status_list)

        logs_box = QGroupBox("Logs")
        logs_layout = QVBoxLayout(logs_box)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        logs_layout.addWidget(self.log_view)

        bottom_split.addWidget(status_box)
        bottom_split.addWidget(logs_box)
        bottom_split.setSizes([340, 900])
        main_layout.addWidget(bottom_split, 1)

        self.resize(1300, 860)
        self.append_log("Ready.")

        self._populate_images_choices()

    # --- zarr discovery ---
    def _discover_zarr_images(self, root: Path) -> List[Path]:
        """
        Show only:
        - root/* (directories)
        - root/*/* (directories)
        """
        out: List[Path] = []
        try:
            level1 = [p for p in root.iterdir() if p.suffix == ".zarr" and p.is_dir()]
            out.extend(sorted(level1))

            for p in level1:
                try:
                    out.extend(sorted([c for c in p.iterdir() if c.is_dir()]))
                except PermissionError:
                    continue
        except Exception:
            pass

        # unique preserve order
        seen = set()
        uniq: List[Path] = []
        for p in out:
            if p not in seen:
                uniq.append(p)
                seen.add(p)
        return uniq

    def _selected_zarr_image(self) -> Optional[Path]:
        data = self.zarr_image_combo.currentData()
        if not data:
            return None
        if data == "__NO_ZARR__":
            return None
        return Path(str(data))
    
    def _populate_images_choices(self) -> None:
        current = self.zarr_image_combo.currentData()

        self.zarr_image_combo.blockSignals(True)
        self.zarr_image_combo.clear()

        self.zarr_image_combo.addItem("Select dataset…", None)
        self.zarr_image_combo.addItem("No zarr image (conversion task)", "__NO_ZARR__")

        for p in self._discover_zarr_images(self.analysis_dir):
            label = str(p.relative_to(self.analysis_dir))
            self.zarr_image_combo.addItem(label, str(p))

        # restore selection if possible
        if current is not None:
            idx = self.zarr_image_combo.findData(current)
            if idx >= 0:
                self.zarr_image_combo.setCurrentIndex(idx)
            else:
                self.zarr_image_combo.setCurrentIndex(0)
        else:
            self.zarr_image_combo.setCurrentIndex(0)

        self.zarr_image_combo.blockSignals(False)
        self._on_zarr_image_changed()

    def _on_zarr_image_changed(self) -> None:
        """
        Enable Run only if the user chose either:
        - a dataset folder
        - or "No zarr image"
        """
        data = self.zarr_image_combo.currentData()
        valid = (data is not None)  # placeholder None => invalid
        self.run_btn.setEnabled(valid and len(self.workflow_ids) > 0)

    # --- logging ---
    def append_log(self, msg: str) -> None:
        self.log_view.append(str(msg))

    # --- freeze/unfreeze ---
    def freeze_ui(self, frozen: bool) -> None:
        self.available_list.setEnabled(not frozen)
        self.workflow_list.setEnabled(not frozen)
        self.add_btn.setEnabled(not frozen)
        self.remove_btn.setEnabled(not frozen)
        self.up_btn.setEnabled(not frozen)
        self.down_btn.setEnabled(not frozen)
        self.auto_vis_chk.setEnabled(not frozen)
        self.email_to.setEnabled(not frozen)
        self.zarr_image_combo.setEnabled(not frozen)
        self.run_btn.setEnabled(not frozen)
        self.cancel_btn.setEnabled(frozen)

        # disable parameter widgets while running
        for name, widget in self.current_param_widgets.items():
            #for w in widgets.values():
            widget.setEnabled(not frozen)

    # --- workflow building ---
    def add_task(self) -> None:
        item = self.available_list.currentItem()
        if not item:
            return
        task_id = uuid.uuid4().hex

        key = item.data(Qt.UserRole + 1)
        task = self.tasks_by_key[key]
        
        #key = item.data(Qt.UserRole)
        self.task_by_id[task_id] = task

        self.workflow_ids.append(task_id)

        w_item = QListWidgetItem(task.title)
        w_item.setData(Qt.UserRole, task_id)
        w_item.setData(Qt.UserRole + 1, task.key)
        w_item.setToolTip(task.description)
        self.workflow_list.addItem(w_item)
        self.params_by_id[task_id] = {}

        self.status_list.addItem(f"⏳ {task.title}")
        self.append_log(f"Added task: {task.title}")

        # Auto-fill common parameters for this task (if present)
        #self._autofill_common_params_for_task(task_id)

        self._on_zarr_image_changed()

    def remove_task(self) -> None:
        row = self.workflow_list.currentRow()
        if row < 0:
            return
        item = self.workflow_list.takeItem(row)
        task_id = item.data(Qt.UserRole)
        del self.workflow_ids[task_id]
        del self.params_by_id[task_id]
        del item

        s_item = self.status_list.takeItem(row)
        del s_item

        self.append_log(f"Removed task: {self.task_by_id[task_id].title}")
        self.clear_params_form()

        self._on_zarr_image_changed()

    def move_up(self) -> None:
        row = self.workflow_list.currentRow()
        if row <= 0:
            return
        self._swap_rows(row, row - 1)
        self.workflow_list.setCurrentRow(row - 1)

    def move_down(self) -> None:
        row = self.workflow_list.currentRow()
        if row < 0 or row >= self.workflow_list.count() - 1:
            return
        self._swap_rows(row, row + 1)
        self.workflow_list.setCurrentRow(row + 1)

    def _swap_rows(self, a: int, b: int) -> None:
        self.workflow_ids[a], self.workflow_ids[b] = self.workflow_ids[b], self.workflow_ids[a]

        a_item = self.workflow_list.item(a)
        b_item = self.workflow_list.item(b)
        a_key = a_item.data(Qt.UserRole + 1)
        b_key = b_item.data(Qt.UserRole + 1)
        a_id = a_item.data(Qt.UserRole)
        b_id = b_item.data(Qt.UserRole)
        a_text = a_item.text()
        b_text = b_item.text()

        a_item.setText(b_text); a_item.setData(Qt.UserRole + 1, b_key); a_item.setData(Qt.UserRole, b_id)
        b_item.setText(a_text); b_item.setData(Qt.UserRole + 1, a_key); b_item.setData(Qt.UserRole, a_id)

        s_a = self.status_list.item(a).text()
        s_b = self.status_list.item(b).text()
        self.status_list.item(a).setText(s_b)
        self.status_list.item(b).setText(s_a)

    def _set_widget_value(self, w: QWidget, val: Any) -> None:
        if isinstance(w, QSpinBox):
            w.setValue(int(val))
        elif isinstance(w, QDoubleSpinBox):
            w.setValue(float(val))
        elif isinstance(w, QCheckBox):
            w.setChecked(bool(val))
        elif isinstance(w, QLineEdit):
            w.setText("" if val is None else str(val))
        elif isinstance(w, QTextEdit):
            if isinstance(val, list):
                w.setPlainText("\n".join(map(str, val)))
            else:
                w.setPlainText("" if val is None else str(val))


    # --- params editor ---
    def clear_params_form(self) -> None:
        self.params_title.setText("Select a workflow task to edit parameters.")
        while self.form_layout.rowCount():
            self.form_layout.removeRow(0)
    
    def _save_current_params(self) -> None:
        if not hasattr(self, "current_param_widgets"):
            return
        raw: dict[str, Any] = {}
        task = self.task_by_id[self.current_workflow_id]
        for name, w in self.current_param_widgets.items():
            if name in HIDDEN_WORKFLOW_FIELDS:
                continue
            raw[name] = read_widget_value(w, task.model.model_fields[name].annotation)
        self.params_by_id[self.current_workflow_id] = raw

    def on_workflow_selected(self, current: QListWidgetItem, previous: QListWidgetItem) -> None:
        self._save_current_params()
        if not current:
            return
        task_id = current.data(Qt.UserRole)
        task_key = current.data(Qt.UserRole + 1)
        #row = self.workflow_list.currentRow()
        self.show_task_params(task_key, task_id)

    def show_task_params(self, task_key: str, task_id: str) -> None:
        task = self.task_by_id[task_id]
        self.params_title.setText(f"<b>{task.title}</b><br/>{task.description}")

        while self.form_layout.rowCount():
            self.form_layout.removeRow(0)

        # build NEW widgets each time
        widgets = build_widgets_from_model(task.model)

        # restore previous values if we have them
        saved = self.params_by_id.get(task_id, {})
        for name, w in widgets.items():
            if name in saved:
                self._set_widget_value(w, saved[name])
        #self.param_widgets[task_id] = widgets

        # store current widgets for reading later
        self.current_param_widgets = widgets
        self.current_task_key = task_key
        self.current_workflow_id = task_id

        # add to layout
        for name in task.model.model_fields.keys():
            if name in HIDDEN_WORKFLOW_FIELDS:
                continue
            self.form_layout.addRow(name, widgets[name])

    # --- autofill common args (zarr_urls/zarr_dir) ---
    def _autofill_common_params_for_task(self, task_id: str) -> None:
        widgets = self.param_widgets[task_id]
        chosen_zarr_image = str(self.zarr_image_combo.currentData()) if self.zarr_image_combo.currentData() else ""

        # zarr_dir
        if "zarr_dir" in widgets and isinstance(widgets["zarr_dir"], QLineEdit):
            #widgets["zarr_dir"].setText(str(self.analysis_dir))
            widgets["zarr_dir"].setEnabled(False)
        
        if "zarr_url" in widgets and isinstance(widgets["zarr_url"], QLineEdit):
            #widgets["zarr_url"].setText(chosen_zarr_image)
            widgets["zarr_url"].setEnabled(False)

        # zarr_urls (list[str]) shown as QTextEdit
        if "zarr_urls" in widgets and isinstance(widgets["zarr_urls"], QTextEdit):
            #widgets["zarr_urls"].setPlainText(chosen_zarr_image)
            widgets["zarr_urls"].setEnabled(False)

    def collect_params_model_for_row(self, row: int) -> BaseModel:
        task_id = self.workflow_ids[row]
        task = self.task_by_id[task_id]

        raw = dict(self.params_by_id.get(task_id, {}))

        # Force workflow-scoped inputs
        selected_dir = str(self.analysis_dir)
        selected_image = self._selected_zarr_image()
        selected_image_str = str(selected_image) if selected_image else ""

        # Always force zarr_dir if present
        if "zarr_dir" in task.model.model_fields:
            raw["zarr_dir"] = selected_dir

        # Force zarr_url if present
        if "zarr_url" in task.model.model_fields:
            raw["zarr_url"] = selected_image_str

        # Force zarr_urls if present: always [zarr_url]
        if "zarr_urls" in task.model.model_fields:
            raw["zarr_urls"] = [selected_image_str] if selected_image_str else []

        # 3) Validate/coerce with Pydantic model created from signature
        return task.model(**raw)

    def build_plan(self) -> list[tuple[TaskSpec, BaseModel]]:
        # Ensure current edits are saved
        self._save_current_params()

        plan = []
        for row in range(len(self.workflow_ids)):
            params_model = self.collect_params_model_for_row(row)
            plan.append((self.task_by_id[self.workflow_ids[row]], params_model))
        return plan

    def reset_status(self) -> None:
        for i in range(self.status_list.count()):
            txt = self.status_list.item(i).text()
            title = txt.split(" ", 1)[1] if " " in txt else txt
            self.status_list.item(i).setText(f"⏳ {title}")

    # --- run/cancel ---
    def run_workflow(self) -> None:
        if not self.workflow_ids:
            QMessageBox.information(self, "No workflow", "Add at least one task to the workflow.")
            return

        # refresh autofill for tasks that use zarr_urls/zarr_dir
        #for task_id in self.workflow_ids:
        #    self._autofill_common_params_for_task(task_id)

        try:
            plan = self.build_plan()
        except ValidationError as e:
            QMessageBox.warning(self, "Invalid parameters", str(e))
            return

        self.reset_status()
        self.freeze_ui(True)
        self.append_log("Starting workflow…")

        email_cfg = load_email_config(self.email_to.text())
        if email_cfg.enabled and not email_cfg.smtp_host:
            QMessageBox.warning(
                self,
                "Email not configured",
                "Email address provided but SMTP env vars are missing.\n"
                "Set WF_SMTP_HOST/WF_SMTP_PORT/WF_SMTP_USER/WF_SMTP_PASS.\n"
                "Continuing without email.",
            )
            email_cfg = EmailConfig(False, "", "", 587, "", "")

        self.thread = QThread(self)
        self.worker = WorkflowWorker(
            analysis_dir=self.analysis_dir,
            plan=plan,
            auto_visualize=self.auto_vis_chk.isChecked(),
            email_cfg=email_cfg,
        )
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.log.connect(self.append_log)
        self.worker.task_started.connect(self.on_task_started)
        self.worker.task_finished.connect(self.on_task_finished)
        self.worker.finished.connect(self.on_finished)

        # cleanup
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)

        self.thread.start()

    def cancel_workflow(self) -> None:
        if self.worker:
            self.append_log("Cancellation requested…")
            self.worker.cancel()

    @Slot(int, int, str)
    def on_task_started(self, idx: int, total: int, title: str) -> None:
        self.append_log(f"Running {idx}/{total}: {title}")

    @Slot(int, int, str)
    def on_task_finished(self, idx: int, total: int, title: str) -> None:
        row = idx - 1
        if 0 <= row < self.status_list.count():
            self.status_list.item(row).setText(f"✅ {title}")

    @Slot(bool, str)
    def on_finished(self, ok: bool, msg: str) -> None:
        if not ok:
            for i in range(self.status_list.count()):
                txt = self.status_list.item(i).text()
                if txt.startswith("⏳ "):
                    self.status_list.item(i).setText(txt.replace("⏳", "⛔", 1))

        self.append_log(f"Workflow finished: {msg}")
        self.freeze_ui(False)

        self.thread = None
        self.worker = None


# =============================================================================
# 7) App entry
# =============================================================================

def main() -> None:
    app = QApplication(sys.argv)

    welcome = OpeningDialog()
    chosen_dir: Optional[Path] = None

    def on_dir_selected(p: Path) -> None:
        nonlocal chosen_dir
        chosen_dir = p

    welcome.dir_selected.connect(on_dir_selected)

    if welcome.exec() != QDialog.Accepted or chosen_dir is None:
        return

    win = WorkflowWindow(chosen_dir, TASKS)
    win.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()