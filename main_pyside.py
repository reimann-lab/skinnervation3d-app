from __future__ import annotations
import os
import re
import logging
import inspect
import uuid
import sys
import traceback
import smtplib
import subprocess
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, Union, get_args, get_origin, get_type_hints
from skinnervation3d_fractal_tasks.tasks import (fit_surface,
                                                 segment_fibers,
                                                 analyse_fiber_plexus,
                                                 compute_fiber_density_per_structure,
                                                 count_number_fiber_crossing)

from mesospim_fractal_tasks.tasks import (crop_regions_of_interest_dask,
                                          correct_flatfield_dask,
                                          correct_illumination_dask,
                                          stitch_with_multiview_stitcher, 
                                          mesospim_to_omezarr)

from pydantic import BaseModel, ValidationError, create_model, TypeAdapter

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
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
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

# =============================================================================
# 0) Tasks definition
# =============================================================================


TASK_FUNCTIONS: List[Callable[..., Any]] = [
    mesospim_to_omezarr.mesospim_to_omezarr,
    crop_regions_of_interest_dask.crop_regions_of_interest,
    correct_flatfield_dask.correct_flatfield,
    correct_illumination_dask.correct_illumination,
    stitch_with_multiview_stitcher.stitch_with_multiview_stitcher,
    fit_surface.fit_surface,
    segment_fibers.segment_fibers,
    count_number_fiber_crossing.count_number_fiber_crossing,
    compute_fiber_density_per_structure.compute_fiber_density_per_structure,
    analyse_fiber_plexus.analyse_fiber_plexus,
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

def launch_napari_in_conda_env(*, analysis_dir: Path, zarr_paths: List[str] | None, env_name: str) -> None:

    #log_path = analysis_dir / f"napari_launch.log"
    child_env = os.environ.copy()
    child_env.pop("QT_API", None)
    args = ["conda", "run", "-n", env_name, "napari"]
    if zarr_paths:
        for p in zarr_paths:
            args.append(str(p))

    #with log_path.open("w") as f:
    #    f.write("CMD: " + " ".join(args) + "\n\n")
    p = subprocess.Popen(
        args,
        cwd=str(analysis_dir),
        stdout=subprocess.DEVNULL, #f
        stderr=subprocess.STDOUT,
        text=True,
        env=child_env,
    )
     #   f.write(f"\nSpawned PID: {p.pid}\n")

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
    param_descriptions: dict[str, str]

def _parse_doc_fn_description(fn: Callable[..., Any]) -> str:
    doc = inspect.getdoc(fn) or ""
    if doc:
        doc_lines = doc.split("\n")
        l = 0
        while (l < len(doc_lines)) and (not doc_lines[l].startswith("Parameters")):
            l += 1
        return "\n".join(doc_lines[:l])
    else:
        return ""
    
def _parse_doc_param_description(fn: Callable[..., Any]) -> dict[str, str]:
    doc = inspect.getdoc(fn) or ""
    possible_headers = ("Args:", "Arguments:", "Parameters:", "Kwargs:", "Keyword Args:")
    if not doc:
        return {}

    lines = doc.splitlines()
    
    # Find the first relevant section header
    start = None
    for i, line in enumerate(lines):
        if line.strip() in possible_headers:
            start = i + 1
            break
    if start is None:
        return {}

    out = {}
    param_line_re = re.compile(
        r"""
        ^(?P<indent>\s+)                      # indentation
        (?P<name>[A-Za-z_][A-Za-z0-9_]*)      # param name
        (?:\s*\([^)]*\))?                     # optional "(type)" - ignored
        \s*:\s*
        (?P<desc>.*\S.*)?                     # initial description (optional, may be empty)
        $""",
        re.VERBOSE,
    )
    current_name = None
    current_desc_parts = []
    base_indent = None

    def flush():
        nonlocal current_name, current_desc_parts
        if current_name:
            # Normalize whitespace, keep it readable
            desc = " ".join(s.strip() for s in current_desc_parts if s.strip()).strip()
            if desc:
                out[current_name] = desc
        current_name = None
        current_desc_parts = []

    # Parse until we hit a non-indented line (next section) or end
    for line in lines[start:]:
        # Stop at the next top-level section header
        if line and not line.startswith(" "):  # non-indented => new section likely
            break

        if not line.strip():
            # Blank line inside Args section -> treat as paragraph break
            if current_name:
                current_desc_parts.append("")
            continue

        m = param_line_re.match(line)
        if m:
            flush()
            current_name = m.group("name")
            base_indent = len(m.group("indent"))
            first = (m.group("desc") or "").strip()
            if first:
                current_desc_parts.append(first)
            continue

        # Continuation line: must belong to current param and be more indented than the param line
        if current_name is not None and base_indent is not None:
            indent_len = len(line) - len(line.lstrip(" "))
            if indent_len > base_indent:
                current_desc_parts.append(line.strip())
                continue

        # Otherwise: ignore (or could break if you want strict behavior)
        # Here we just ignore unexpected lines.

    flush()
    return out

def build_model_from_signature(fn: Callable[..., Any]) -> Type[BaseModel]:
    """
    Create a Pydantic model from a callable signature:
      - respects type hints
      - uses defaults
      - keyword-only args are included normally
    """
    sig = inspect.signature(fn)
    type_hints = get_type_hints(fn, include_extras=True)

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
                title=fn.__name__.replace("_", " ").capitalize(),
                description=_parse_doc_fn_description(fn),
                fn=fn,
                model=build_model_from_signature(fn),
                param_descriptions=_parse_doc_param_description(fn),
            )
        )
    return specs


TASKS: List[TaskSpec] = build_task_specs(TASK_FUNCTIONS)

# =============================================================================
# 3) Pydantic type-to-widget helper class
# =============================================================================

class OptionalWrapperWidget(QWidget):
    """
    Wraps an editor widget with an 'Enabled' checkbox.
    If unchecked => value() returns None and editor is disabled.
    """
    def __init__(self, inner: QWidget, default_is_none: bool, parent=None):
        super().__init__(parent)
        self.inner = inner

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.chk = QCheckBox("Set value")
        
        # If default is None, start disabled; otherwise enabled.
        self.chk.setChecked(not default_is_none)
        layout.addWidget(self.chk)
        layout.addWidget(self.inner)

        self.inner.setVisible(self.chk.isChecked())
        self.chk.toggled.connect(lambda checked: self.inner.setVisible(checked))

    def is_enabled(self) -> bool:
        return self.chk.isChecked()
    

class TupleWidget(QWidget):
    """
    Fixed-length tuple editor: tuple[T1, T2, ...]
    """
    def __init__(self, tuple_type: Any, default: Any = None, parent=None):
        super().__init__(parent)
        self.tuple_type = tuple_type
        self.item_types = list(get_args(tuple_type))
        self.widgets: list[QWidget] = []

        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        default_items = list(default) if isinstance(default, (tuple, list)) else [None] * len(self.item_types)

        for i, t in enumerate(self.item_types):
            w = build_leaf_widget(t, default_items[i] if i < len(default_items) else None)
            self.widgets.append(w)
            layout.addRow(w)

    def value(self) -> tuple:
        out = []
        for w, t in zip(self.widgets, self.item_types):
            raw = read_leaf_widget_value(w, t)
            try:
                v = TypeAdapter(t).validate_python(raw)
            except ValidationError as e:
                raise ValueError(f"Invalid tuple element ({t}): {e}") from e
            out.append(v)
        return tuple(out)
    

class ListWidget(QWidget):
    """
    list[T] editor:
    - append tokens (split by separators)
    - clear list
    - optional reorder by drag & drop
    """
    def __init__(self, list_type: Any, default: Any = None, allow_reorder: bool = True, parent=None):
        super().__init__(parent)
        self.list_type = list_type
        (self.item_type,) = get_args(list_type)

        self._items: list[Any] = list(default) if isinstance(default, list) else []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        root.addWidget(QLabel("Items:"))

        self.view = QListWidget()
        self.view.setSelectionMode(QListWidget.ExtendedSelection)

        if allow_reorder:
            # Built-in Qt reorder (drag within list)
            self.view.setDragDropMode(QListWidget.InternalMove)
            self.view.setDefaultDropAction(Qt.MoveAction)
        else:
            self.view.setDragDropMode(QListWidget.NoDragDrop)

        root.addWidget(self.view)

        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Append… (separators: space, comma, ;, /, |, ' - ')")
        row.addWidget(self.input)

        self.btn_append = QPushButton("Append")
        self.btn_clear = QPushButton("Clear")
        row.addWidget(self.btn_append)
        row.addWidget(self.btn_clear)
        root.addLayout(row)

        self.btn_append.clicked.connect(self._on_append)
        self.btn_clear.clicked.connect(self._on_clear)

        self._refresh_from_items()

    def _refresh_from_items(self):
        self.view.clear()
        for it in self._items:
            self.view.addItem(QListWidgetItem(str(it)))

    def _sync_items_from_view(self):
        # If reorder is enabled, reflect current GUI order back into _items
        current = []
        for i in range(self.view.count()):
            current.append(self.view.item(i).data(Qt.UserRole))
        self._items = current

    def _on_clear(self):
        self._items = []
        self._refresh_from_items()

    def _on_append(self):
        text = self.input.text()
        tokens = split_tokens(text)
        if not tokens:
            return

        new_vals = []
        for tok in tokens:
            try:
                v = TypeAdapter(self.item_type).validate_python(tok)
            except ValidationError as e:
                raise ValueError(f"Invalid list item ({self.item_type}): {tok!r}. {e}") from e
            new_vals.append(v)

        self._items.extend(new_vals)
        self.input.clear()
        self._refresh_from_items()
        
        # Store typed values in item UserRole for robust re-sync after reorder:
        for i, v in enumerate(self._items):
            self.view.item(i).setData(Qt.UserRole, v)

    def value(self) -> list[Any]:
        # If reorder is enabled, read current order from view
        if self.view.dragDropMode() == QListWidget.InternalMove:
            self._sync_items_from_view()

        # Validate whole list
        try:
            return TypeAdapter(self.list_type).validate_python(self._items)
        except ValidationError as e:
            raise ValueError(f"Invalid list value: {e}") from e
        

class CustomModelWidget(QWidget):
    """
    GUI for a nested Pydantic BaseModel.
    """
    def __init__(
        self, 
        model_cls: type[BaseModel], 
        default: Any = None, 
        parent=None,
        param_descriptions: dict[str, str] | None = None
    ):
        super().__init__(parent)
        self.model_cls = model_cls

        # default can be None, dict, or BaseModel instance
        if isinstance(default, BaseModel):
            default_dict = default.model_dump()
        elif isinstance(default, dict):
            default_dict = default
        else:
            default_dict = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.group = QGroupBox()
        outer.addWidget(self.group)

        self.widgets = build_widgets_from_model(model_cls, defaults=default_dict, param_descriptions=param_descriptions)

        form = QFormLayout(self.group)
        form.setContentsMargins(8, 8, 8, 8)
        for fname, w in self.widgets.items():
            form.addRow(fname, w)

    def value_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for fname, w in self.widgets.items():
            ftype = self.model_cls.model_fields[fname].annotation
            out[fname] = read_widget_value(w, ftype)
        return out

    def value_model(self) -> BaseModel:
        data = self.value_dict()
        try:
            return TypeAdapter(self.model_cls).validate_python(data)
        except ValidationError as e:
            raise ValueError(f"Invalid {self.model_cls.__name__}: {e}") from e


# =============================================================================
# 3) Pydantic -> widgets (basic types)
# =============================================================================

def is_optional(tp: Any) -> bool:
    origin = get_origin(tp)
    return origin is Union and type(None) in get_args(tp)

def unwrap_optional(tp: Any) -> Any:
    if is_optional(tp):
        return next(a for a in get_args(tp) if a is not type(None))
    return tp

def is_tuple_type(tp: Any) -> bool:
    tp = unwrap_optional(tp)
    return get_origin(tp) is tuple

def is_list_type(tp: Any) -> bool:
    tp = unwrap_optional(tp)
    return get_origin(tp) is list

def split_tokens(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    
    SEP_PATTERN = re.compile(
        r"""
        [,\s;/|]+            # comma, whitespace, semicolon, slash, pipe 
        """, re.VERBOSE)
    
    parts = SEP_PATTERN.split(text)
    return [p for p in (x.strip() for x in parts) if p]

def is_pydantic_model_type(tp: Any) -> bool:
    tp = unwrap_optional(tp)
    try:
        return isinstance(tp, type) and issubclass(tp, BaseModel)
    except TypeError:
        return False

def build_leaf_widget(tp: Any, default: Any = None) -> QWidget:
    if tp is int:
        w = QSpinBox()
        w.setRange(-2_147_483_648, 2_147_483_647) 
        if default not in (None, ...):
            w.setValue(int(default))
        return w

    if tp is float:
        w = QDoubleSpinBox()
        w.setDecimals(6)
        if default not in (None, ...):
            w.setValue(float(default))
        return w

    if tp is bool:
        w = QCheckBox()
        if default not in (None, ...):
            w.setChecked(bool(default))
        return w

    # fallback string
    w = QLineEdit()
    if default not in (None, ...):
        w.setText(str(default))
    return w

def read_leaf_widget_value(widget: QWidget, expected_type: Any) -> Any:
    if isinstance(widget, QSpinBox):
        return int(widget.value())
    if isinstance(widget, QDoubleSpinBox):
        return float(widget.value())
    if isinstance(widget, QCheckBox):
        return bool(widget.isChecked())
    if isinstance(widget, QLineEdit):
        txt = widget.text().strip()
        #opt = is_optional(expected_type)
        #if opt and txt == "":
        #    return None
        return txt

    raise TypeError(f"Unsupported leaf widget: {type(widget)}")

def build_widgets_from_model(
    model_cls: type[BaseModel],
    defaults: dict[str, Any] | None = None,
    param_descriptions: dict[str, str] | None = None
) -> dict[str, QWidget]:
    
    defaults = defaults or {}
    widgets: dict[str, QWidget] = {}

    for name, field in model_cls.model_fields.items():
        if name in HIDDEN_WORKFLOW_FIELDS:
            continue

        ann_full = field.annotation
        opt = is_optional(ann_full)
        ann = unwrap_optional(ann_full)

        default = defaults.get(name, field.default)
        param_desc = param_descriptions[name] if param_descriptions else "None"

        # Build the "inner" editor first
        if is_tuple_type(ann_full):
            inner = TupleWidget(ann, default=default)

        elif is_list_type(ann_full):
            inner = ListWidget(
                ann, 
                default=default if isinstance(default, list) else [], 
                allow_reorder=True)
            
        elif is_pydantic_model_type(ann_full):
            if isinstance(default, BaseModel):
                nested_default = default.model_dump()
            elif isinstance(default, dict):
                nested_default = default
            else:
                nested_default = {}
            inner = CustomModelWidget(ann, default=nested_default, param_descriptions=param_descriptions)
            if opt:
                default = None
        else:
            inner = build_leaf_widget(ann, default=default)

        # Wrap optional
        if opt:
            inner = OptionalWrapperWidget(inner, default_is_none=(default is None))

        inner.setToolTip(param_desc)

        widgets[name] = inner

    return widgets

def read_widget_value(widget: QWidget, expected_type: Any) -> Any:
    base = unwrap_optional(expected_type)

    # Optional wrapper
    if isinstance(widget, OptionalWrapperWidget):
        if not widget.is_enabled():
            return None
        widget = widget.inner  # unwrap and continue

    # Tuple/list containers
    if isinstance(widget, TupleWidget):
        return widget.value()

    if isinstance(widget, ListWidget):
        return widget.value()
    
    if isinstance(widget, CustomModelWidget):
        return widget.value_model()

    # Leaf
    raw = read_leaf_widget_value(widget, base)
    
    # Validate/coerce via pydantic
    try:
        return TypeAdapter(base).validate_python(raw)
    except ValidationError as e:
        raise ValueError(f"Invalid value for {base}: {e}") from e


# =============================================================================
# 4) Redirect stdout logging
# =============================================================================

class QtLogHandler(logging.Handler):
    def __init__(self, emit_fn):
        super().__init__()
        self._emit_fn = emit_fn

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        self._emit_fn(msg)

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
        selected_image: Path | None,
        plan: List[Tuple[TaskSpec, BaseModel]],
        auto_visualize: bool,
        email_cfg: EmailConfig,
    ):
        super().__init__()
        self.analysis_dir = analysis_dir
        self.selected_image = selected_image
        self.plan = plan
        self.auto_visualize = auto_visualize
        self.email_cfg = email_cfg
        self._interrupted = False

        # If tasks return output paths, we can store it here
        self._last_path: Optional[List[Path]] = None

    def interrupt(self) -> None:
        self._interrupted = True

    def is_interrupted(self) -> bool:
        return self._interrupted
    
    def _pretty_dict(self, d: dict[str, Any]) -> str:
        out = ""
        for k, v in d.items():
            if isinstance(v, dict):
                v = self._pretty_dict(v)
        return "\n".join([f"  {k}: {v}" for k, v in d.items()])

    @Slot()
    def run(self) -> None:
        root = logging.getLogger()
        
        # --- install GUI logging handler ---
        handler = QtLogHandler(self.log.emit)
        handler.setLevel(logging.INFO)
        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
        )

        old_level = root.level
        root.setLevel(logging.INFO)

        old_handlers = list(root.handlers)
        removed = []
        for h in old_handlers:
            if isinstance(h, logging.StreamHandler):
                removed.append(h)
                root.removeHandler(h)
        class DropDistributedFilter(logging.Filter):
            def filter(self, record: logging.LogRecord) -> bool:
                return not (
                    record.name == "distributed"
                    or record.name.startswith("distributed.")
                    or record.name.startswith("tornado")
                )

        handler.addFilter(DropDistributedFilter())
        root.addHandler(handler)

        try:
            self.log.emit("Starting workflow…")
            self._run_workflow()
        finally:
            root.removeHandler(handler)
            for h in removed:
                root.addHandler(h)
            root.setLevel(old_level)

    def _run_workflow(self) -> None:
        total = len(self.plan)
        ok = True
        final = "Success"

        self.log.emit(f"=== Workflow started ({total} task(s)) ===")
        self.log.emit(f"Directory: {self.analysis_dir}")

        try:
            for i, (task, params_model) in enumerate(self.plan, start=1):
                if self.is_interrupted():
                    ok = False
                    final = "Interrupted"
                    self.log.emit("Workflow interruption requested. Stopping after this task.")
                    break

                if i > 0 and self._last_path:
                    
                    # If last task output path, use it as new zarr_url
                    params = dict(params_model.model_dump())
                    params["zarr_url"] = str(self._last_path[0])
                    params_model = task.model(**params)

                self.task_started.emit(i, total, task.title)
                self.log.emit(f"[{i}/{total}] START {task.title}")
                self.log.emit(f"  Parameters: {params_model.model_dump()}")
                self.log.emit(f"-------------------------------------------------------------------------------\n")

                # Call the task: your validate_call wrapper will validate again internally.
                out = task.fn(**params_model.model_dump())

                # Heuristic: if output contains a path, store it
                self._last_path = self._extract_output_path(out)

                self.log.emit(f"[{i}/{total}] DONE  {task.title}")
                self.task_finished.emit(i, total, task.title)

            # Auto-visualize hook
            if ok and self.auto_visualize:
                if self._last_path is None:
                    if self.selected_image is None:
                        self.log.emit("Output visualization enabled, but no output image detected.")
                    else:
                        paths_to_open = [self.selected_image.parent / self.selected_image.name]
                else:
                    paths_to_open = [p.parent / p.name for p in self._last_path]
                paths_str = ", ".join(map(str, paths_to_open))
                self.log.emit(f"Output visualization: opening in Napari: " + paths_str)
                try:
                    launch_napari_in_conda_env(analysis_dir=self.analysis_dir, 
                                               zarr_paths=paths_to_open, 
                                               env_name="napari-crop")
                except Exception as e:
                    self.log.emit(f"Output visualization failed: {e!r}")

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
            self._last_path = None
            self.log.emit("ERROR:\n" + traceback.format_exc())

        self.log.emit(f"=== Workflow finished: {final} ===")
        self.finished.emit(ok, final)

    def _extract_output_path(self, out: Any) -> Optional[list[Path]]:
        """
        Extract zarr_url from image_list_updates if output by a task.
        """
        try:
            if isinstance(out, dict):
                # common keys
                if "image_list_updates" in out.keys() and isinstance(out["image_list_updates"], list):
                    image_list = []
                    for image_dict in out["image_list_updates"]:
                        if "zarr_url" in image_dict.keys():
                            image_list.append(Path(image_dict["zarr_url"]))
                    return image_list
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

        # Default path (shown immediately)
        self.default_dir = Path.home() / "Documents" / "SkInnervationProject" / "Data" / "Multitile"
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
        
        # Start browsing from current text if valid, otherwise from default_dir
        start_dir = self.default_dir
        current = self.dir_line.text().strip()
        if current:
            try:
                p = Path(current)
                if p.exists():
                    start_dir = p
            except Exception:
                pass

        folder = QFileDialog.getExistingDirectory(
            self,
            "Select analysis directory",
            str(start_dir),
        )
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

    request_change_analysis_dir = Signal()          # ask app to go back to opening dialog
    request_open_napari = Signal(object, object)

    def __init__(self, analysis_dir: Path, tasks: List[TaskSpec]):
        super().__init__()
        self.setWindowTitle("Workflow Runner — Workflow")

        self.analysis_dir = analysis_dir
        self.selected_image: Optional[Path] = None
        self.tasks = tasks
        self.tasks_by_key: Dict[str, TaskSpec] = {t.key: t for t in self.tasks}

        # workflow ordered task ids
        self.workflow_ids: List[str] = []
        self.task_by_id: Dict[str, TaskSpec] = {} #task_id => task {t.key: t for t in self.tasks}
        self.params_by_id: dict[str, dict[str, Any]] = {}  # workflow_id -> param values

        # Keep track of current workflow
        self.current_workflow_id: Optional[str] = None
        self.current_param_widgets: Optional[dict[str, QWidget]] = None
        self.current_task_key: Optional[str] = None

        # thread/worker
        self.thread: Optional[QThread] = None
        self.worker: Optional[WorkflowWorker] = None

        # central UI
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        #------------------------------------------------------------
        # First row: analysis directory
        top_row = QHBoxLayout()
        self.top_label = QLabel(f"<b>Analysis directory:</b> {self.analysis_dir}")
        self.top_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        top_row.addWidget(self.top_label, 1)

        self.change_dir_btn = QPushButton("Change analysis directory…")
        self.change_dir_btn.clicked.connect(self._on_change_dir_clicked)
        top_row.addWidget(self.change_dir_btn)

        main_layout.addLayout(top_row)

        #------------------------------------------------------------
        # Second row: image selection and possible visualisation
        second_row = QHBoxLayout()

        # Image selection combo list: scan *.zarr under analysis dir
        self.zarr_image_combo = QComboBox()
        self.zarr_image_combo.addItem("Select zarr image…", None)  # placeholder
        self.zarr_image_combo.addItem("No zarr image (conversion task)", "__NO_ZARR__")
        self.zarr_image_combo.currentIndexChanged.connect(self._on_zarr_image_changed)
        self.refresh_zarr_images_btn = QPushButton("Refresh list")
        self.refresh_zarr_images_btn.clicked.connect(self._populate_images_choices)
        
        # Button to visualise image in napari
        self.crop_napari_btn = QPushButton("Visualize image in napari…")
        self.crop_napari_btn.clicked.connect(self._on_crop_in_napari_clicked)

        second_row.addWidget(QLabel("<b>Image:</b>"))
        second_row.addWidget(self.zarr_image_combo, 1)
        second_row.addWidget(self.refresh_zarr_images_btn)  
        second_row.addWidget(self.crop_napari_btn)
        main_layout.addLayout(second_row)

        #------------------------------------------------------------
        # Panels: Available / Workflow / Parameters
        splitter = QSplitter(Qt.Horizontal)

        # left: available tasks
        left_box = QGroupBox("Available tasks")
        self._set_title_stylesheet(left_box)
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
        self._set_title_stylesheet(mid_box)
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
        self._set_title_stylesheet(right_box)
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

        #------------------------------------------------------------
        # Run row
        run_row = QHBoxLayout()

        # Run/interrupt button
        self.run_btn = QPushButton("Run workflow")
        self.run_btn.clicked.connect(self.run_workflow)
        self.run_btn.setEnabled(False)
        self.interrupt_btn = QPushButton("Interrupt Workflow")
        self.interrupt_btn.setEnabled(False)
        self.interrupt_btn.clicked.connect(self.interrupt_workflow)
             
        run_row.addWidget(self.run_btn)
        run_row.addSpacing(12)
        run_row.addWidget(self.interrupt_btn)
        run_row.addSpacing(12)

        self.auto_vis_chk = QCheckBox("Visualize End Result")
        self.auto_vis_chk.setChecked(False)
        run_row.addWidget(self.auto_vis_chk)
        run_row.addSpacing(12)

        #run_row.addWidget(QLabel("Email to:"))
        self.email_to = QLineEdit()
        self.email_to.setPlaceholderText("optional@example.org")
        self.email_to.setFixedWidth(240)
        self.email_to.setVisible(False)
        run_row.addWidget(self.email_to)
        run_row.addStretch(1)


        main_layout.addLayout(run_row)

        # toolbar: auto visualize + email
        #tb = QToolBar("Main")
        #self.addToolBar(tb)
        #tb.addSeparator()

        #------------------------------------------------------------
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

    def _set_title_stylesheet(self, group_box: QGroupBox) -> None:
        group_box.setStyleSheet("""
            QGroupBox {
                margin-top: 24px;
            }

            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 6px;
                font-size: 18pt;
                font-weight: bold;
            }
            """)
        
    def _on_change_dir_clicked(self) -> None:
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("Change analysis directory?")
        msg.setText("Changing the analysis directory will close this workflow window.")
        msg.setInformativeText("Any current workflow setup and parameters will be lost.")
        msg.setStandardButtons(QMessageBox.Cancel | QMessageBox.Ok)
        msg.setDefaultButton(QMessageBox.Cancel)

        if msg.exec() != QMessageBox.Ok:
            return

        # If a workflow is running, interrupt first (optional but recommended)
        if getattr(self, "worker", None) is not None:
            # reuse your existing cancel logic
            try:
                self.interrupt_workflow()
            except Exception:
                pass

        self.request_change_analysis_dir.emit()

    def _on_crop_in_napari_clicked(self) -> None:
        # determine currently selected image choice
        data = self.zarr_image_combo.currentData()  # you already store None / "__NO_ZARR__" / str
        selected = None if (data in (None, "__NO_ZARR__")) else str(data)

        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle("Open napari?")
        if selected:
            msg.setText("Napari will open in a new window.")
            msg.setInformativeText(f"It will try to open:\n{selected}")
        else:
            msg.setText("Napari will open in a new window.")
            msg.setInformativeText("No dataset is selected. Napari will open empty.")
        msg.setStandardButtons(QMessageBox.Cancel | QMessageBox.Ok)
        msg.setDefaultButton(QMessageBox.Ok)

        if msg.exec() != QMessageBox.Ok:
            return

        self.request_open_napari.emit(self.analysis_dir, selected)

    # --- zarr discovery ---
    def _discover_zarr_images(self, root: Path) -> List[Path]:
        """
        Show only:
        - root/*.zarr/ (directories)
        """
        out: List[Path] = []
        try:
            level1 = [p for p in root.iterdir() if p.suffix == ".zarr" and p.is_dir()]
            #out.extend(sorted(level1))

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
        self.interrupt_btn.setEnabled(frozen)

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

        self._on_zarr_image_changed()

    def remove_task(self) -> None:
        row = self.workflow_list.currentRow()
        if row < 0:
            return
        item = self.workflow_list.item(row) # don't yet trigger on_workflow_selected
        task_id = item.data(Qt.UserRole)
        if self.current_workflow_id == task_id:
            self.current_workflow_id = None
            self.current_param_widgets = None
            self.current_task_key = None
        item = self.workflow_list.takeItem(row) # now trigger on_workflow_selected
        del self.params_by_id[task_id]
        del self.workflow_ids[row]
        del item

        s_item = self.status_list.takeItem(row)
        del s_item

        self.append_log(f"Removed task: {self.task_by_id[task_id].title}")
        del self.task_by_id[task_id]

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
        if self.current_workflow_id is None:
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
        self.show_task_params(task_key, task_id)

    def show_task_params(self, task_key: str, task_id: str) -> None:
        task = self.task_by_id[task_id]
        self.params_title.setText(f"<b>{task.title}</b><br/>{task.description}")

        while self.form_layout.rowCount():
            self.form_layout.removeRow(0)

        # build NEW widgets each time
        widgets = build_widgets_from_model(task.model, 
                                           param_descriptions=task.param_descriptions)

        # restore previous values if we have them
        saved = self.params_by_id.get(task_id, {})
        for name, w in widgets.items():
            if name in saved:
                self._set_widget_value(w, saved[name])

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
        self.selected_image = self._selected_zarr_image()
        selected_image_str = str(self.selected_image) if self.selected_image else ""

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

    # --- run/interrupt ---
    def run_workflow(self) -> None:
        if not self.workflow_ids:
            QMessageBox.information(self, "No workflow", "Add at least one task to the workflow.")
            return
        
        if self.thread is not None and self.thread.isRunning():
            QMessageBox.information(self, "Busy", "A workflow is still running.")
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

        self.thread = QThread()
        self.worker = WorkflowWorker(
            analysis_dir=self.analysis_dir,
            selected_image=self.selected_image,
            plan=plan,
            auto_visualize=self.auto_vis_chk.isChecked(),
            email_cfg=email_cfg,
        )
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.log.connect(self.append_log, Qt.QueuedConnection)
        self.worker.task_started.connect(self.on_task_started)
        self.worker.task_finished.connect(self.on_task_finished)
        self.worker.finished.connect(self.on_finished)

        # cleanup
        #self.worker.finished.connect(self.thread.quit)
        #self.worker.finished.connect(self.worker.deleteLater)
        #self.thread.finished.connect(self.thread.deleteLater)

        self.thread.start()

    def interrupt_workflow(self) -> None:
        if self.worker:
            self.append_log("Interruption requested…")
            self.worker.interrupt()

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

        t = self.thread
        w = self.worker

        if t is not None:
            if t.isRunning():
                t.quit()
                t.wait()
            t.deleteLater()

        if w is not None:
            w.deleteLater()

        self.thread = None
        self.worker = None
