from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Dict, Any
import uuid
from pydantic import BaseModel, ValidationError
import logging
from datetime import datetime

from PySide6.QtCore import Signal, Slot, Qt, QThread, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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

from skinnervation3d_app.workflow.models import (
    TaskSpec, WorkflowPlan, PlanItem)
from skinnervation3d_app.ui.worker_window import WorkflowWorker
from skinnervation3d_app.tasks.spec import HIDDEN_WORKFLOW_FIELDS
from skinnervation3d_app.ui.param_widgets.param_factory import (
    build_widgets_from_model,
    read_widget_value,
)
from skinnervation3d_app.ui.logging import QtLogEmitter, QtLogHandler
from skinnervation3d_app.services.server import DocsServer

logger = logging.getLogger(__name__)

class WorkflowWindow(QMainWindow):

    request_change_analysis_dir = Signal()          # ask app to go back to opening dialog
    request_open_napari = Signal(object, object)    # ask app to open napari

    def __init__(self, analysis_dir: Path, tasks: List[TaskSpec], docs_server: DocsServer):
        super().__init__()
        self.setWindowTitle("Workflow Runner — Workflow")

        self.analysis_dir = analysis_dir
        self.log_path = analysis_dir / "logs"
        if not self.log_path.exists():
            self.log_path.mkdir()
        self.date = datetime.now().strftime("%Y-%m-%d_%H:%M")
        self.workflow_log_path = self.log_path / f"workflow_{self.date}.log"
        self.selected_image: Optional[Path] = None
        self.tasks = tasks
        self.tasks_by_key: Dict[str, TaskSpec] = {t.key: t for t in self.tasks}

        # workflow ordered task ids
        self.workflow_ids: List[str] = []
        self.task_by_id: Dict[str, TaskSpec] = {}                # task_id => task
        self.params_by_id: dict[str, dict[str, Any]] = {}        # task_id -> param values

        # Keep track of current workflow
        self.current_workflow_id: Optional[str] = None
        self.current_param_widgets: Optional[dict[str, QWidget]] = None
        self.current_task_key: Optional[str] = None

        # thread/worker
        self._gui_log_handler: Optional[QtLogHandler] = None
        self.thread: Optional[QThread] = None
        self.worker: Optional[WorkflowWorker] = None

        # Docs
        self._docs_server = docs_server

        self._build_ui()
        self.resize(1300, 860)
        self.append_log("Ready.")

        self._populate_images_choices()         # initial zarr image display




    # --------------------------------------------------------------------------------
    # UI building
    # --------------------------------------------------------------------------------

    def _build_ui(self) -> None:
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
        
        self.pre_list_title = QLabel("Preprocessing")
        self.pre_list = QListWidget()
        pre_tasks = [t for t in self.tasks if t.category == "preprocessing"]
        for t in pre_tasks:
            item = QListWidgetItem(t.title)
            item.setData(Qt.UserRole + 1, t.key)
            item.setToolTip(t.description)
            self.pre_list.addItem(item)
        left_layout.addWidget(self.pre_list_title)
        left_layout.addWidget(self.pre_list)

        self.analysis_list_title = QLabel("Analysis")
        self.analysis_list = QListWidget()
        analysis_tasks = [t for t in self.tasks if t.category == "analysis"]
        for t in analysis_tasks:
            item = QListWidgetItem(t.title)
            item.setData(Qt.UserRole + 1, t.key)
            item.setToolTip(t.description)
            self.analysis_list.addItem(item)
        left_layout.addWidget(self.analysis_list_title)
        left_layout.addWidget(self.analysis_list)
        left_layout.addStretch(1)

        # which available list is currently "active" (clicked last)
        self._active_available_list: QListWidget = self.pre_list
        self.pre_list.itemClicked.connect(lambda _: self._set_active(self.pre_list))
        self.pre_list.currentItemChanged.connect(lambda *_: self._set_active(self.pre_list))
        self.analysis_list.itemClicked.connect(lambda _: self._set_active(self.analysis_list))
        self.analysis_list.currentItemChanged.connect(lambda *_: self._set_active(self.analysis_list))

        # middle: workflow tasks
        mid_box = QGroupBox("Workflow (runs top → bottom)")
        self._set_title_stylesheet(mid_box)
        mid_layout = QVBoxLayout(mid_box)
        self.workflow_list = QListWidget()
        self.workflow_list.currentItemChanged.connect(self._on_task_selected)
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
        
        docs_row = QHBoxLayout()
        self.more_info_btn = QPushButton("More info…")
        self.more_info_btn.setEnabled(False)
        self.more_info_btn.clicked.connect(self._open_more_info)
        docs_row.addStretch(1)
        docs_row.addWidget(self.more_info_btn)
        right_layout.addLayout(docs_row)

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

    def _set_title_stylesheet(self, group_box: QGroupBox) -> None:
        group_box.setStyleSheet("""
            QGroupBox {
                margin-top: 24px;
            }

            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 6px;
                font-size: 24pt;
                font-weight: bold;
            }
            """)

    # --------------------------------------------------------------------------------
    # UI event handlers
    # --------------------------------------------------------------------------------
    
    def _set_active(self, lst: QListWidget) -> None:
        self._active_available_list = lst

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

    def _on_zarr_image_changed(self) -> None:
        """
        Enable Run only if the user chose either:
        - a dataset folder
        - or "No zarr image"
        """
        data = self.zarr_image_combo.currentData()
        valid = (data is not None)  # placeholder None => invalid
        self.run_btn.setEnabled(valid and len(self.workflow_ids) > 0)

    def _on_task_selected(self, current: QListWidgetItem, previous: QListWidgetItem) -> None:
        self._save_current_params()
        if not current:
            return
        task_id = current.data(Qt.UserRole)
        task_key = current.data(Qt.UserRole + 1)
        self.more_info_btn.setEnabled(True)
        self.show_task_params(task_key, task_id)

    def _open_more_info(self) -> None:
        if not self.current_workflow_id:
            return
        task_id = self.current_workflow_id
        task = self.task_by_id[task_id]
        current_docs_path = task.doc_path
        try:
            if not self._docs_server.is_running:
                self._docs_server.start()

            if current_docs_path is not None:
                url = str(Path(self._docs_server.base_url(), current_docs_path))
            else:
                return
            QDesktopServices.openUrl(QUrl(url))

        except Exception as e:
            # you already have append_log
            self.append_log(f"Could not open docs: {e}")


    # --------------------------------------------------------------------------------
    # Zarr image discovery functions
    # --------------------------------------------------------------------------------

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

    def _get_selected_zarr_image(self) -> Optional[Path]:
        data = self.zarr_image_combo.currentData()
        if not data:
            return None
        if data == "__NO_ZARR__":
            return None
        return Path(str(data))
    



    # --------------------------------------------------------------------------------
    # Workflow building functions
    # --------------------------------------------------------------------------------

    def add_task(self) -> None:
        item = self._active_available_list.currentItem()
        if not item:
            return
        task_id = uuid.uuid4().hex

        key = item.data(Qt.UserRole + 1)
        task = self.tasks_by_key[key]
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

        if self.workflow_list.count() == 0:
            while self.form_layout.rowCount():
                self.form_layout.removeRow(0)
                self.more_info_btn.setEnabled(False)
            self.current_param_widgets = None
            self.current_task_key = None
            self.current_workflow_id = None
            self.params_title.setText("Select a workflow task to edit parameters.")

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




    # --------------------------------------------------------------------------------
    # Parameters edition functions
    # --------------------------------------------------------------------------------
    
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

    # --- autofill common args (zarr_urls/zarr_dir) ---
    def _autofill_common_params_for_task_stale(self, task_id: str) -> None:
        widgets = self.param_widgets[task_id] 

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
        self.selected_image = self._get_selected_zarr_image()
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
    



    # --------------------------------------------------------------------------------
    # Workflow build
    # --------------------------------------------------------------------------------

    def build_plan(self) -> WorkflowPlan:
        
        # Ensure current edits are saved
        self._save_current_params()

        plan: List[PlanItem] = []
        for row in range(len(self.workflow_ids)):
            task_id = self.workflow_ids[row]
            task = self.task_by_id[task_id]
            params_model = self.collect_params_model_for_row(row)  # validates
            plan.append(PlanItem(task, params_model))
        return WorkflowPlan(items=plan)




    # --------------------------------------------------------------------------------
    # Run workflow functions
    # --------------------------------------------------------------------------------

    def run_workflow(self) -> None:
        if not self.workflow_ids:
            QMessageBox.information(self, "No workflow", "Add at least one task to the workflow.")
            return
        
        if self.thread is not None and self.thread.isRunning():
            QMessageBox.information(self, "Busy", "A workflow is still running.")
            return

        # Logging
        self.log_emitter = QtLogEmitter()
        self.log_emitter.message.connect(self.append_log)
        
        self.log_handler = QtLogHandler(self.log_emitter)
        self.log_handler.setLevel(logging.INFO)
        self.log_handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
        )
        
        self.file_handler_tasks = logging.FileHandler(self.log_path / f"tasks_{self.date}.log")
        self.file_handler_tasks.setLevel(logging.INFO)
        self.file_handler_tasks.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
        )

        skin3d_logger = logging.getLogger("skinnervation3d_fractal_tasks")
        skin3d_logger.propagate = False
        skin3d_logger.addHandler(self.log_handler)
        skin3d_logger.addHandler(self.file_handler_tasks)
        skin3d_logger.setLevel(logging.INFO)

        mesospim_logger = logging.getLogger("mesospim_fractal_tasks")
        mesospim_logger.propagate = False
        mesospim_logger.addHandler(self.log_handler)
        mesospim_logger.addHandler(self.file_handler_tasks)
        mesospim_logger.setLevel(logging.INFO)

        self._gui_log_handler = self.log_handler

        try:
            plan = self.build_plan()
        except ValidationError as e:
            QMessageBox.warning(self, "Invalid parameters", str(e))
            return

        self.reset_status()
        self.freeze_ui(True)
        self.append_log("Starting workflow…")

        #email_cfg = load_email_config(self.email_to.text())
        #if email_cfg.enabled and not email_cfg.smtp_host:
        #    QMessageBox.warning(
        #        self,
        #        "Email not configured",
        #        "Email address provided but SMTP env vars are missing.\n"
        #        "Set WF_SMTP_HOST/WF_SMTP_PORT/WF_SMTP_USER/WF_SMTP_PASS.\n"
        #        "Continuing without email.",
        #    )
        #    email_cfg = EmailConfig(False, "", "", 587, "", "")

        self.thread = QThread()
        self.worker = WorkflowWorker(
            analysis_dir=self.analysis_dir,
            selected_image=self.selected_image,
            plan=plan,
            auto_visualize=self.auto_vis_chk.isChecked()
        )
        self.worker.moveToThread(self.thread)

        if self.thread is not None:
            self.thread.started.connect(self.worker.run)
            self.worker.log.connect(self.append_log, Qt.QueuedConnection)
            self.worker.task_started.connect(self.on_task_started)
            self.worker.task_finished.connect(self.on_task_finished)
            self.worker.finished.connect(self.on_finished)

            self.thread.start()

    def interrupt_workflow(self) -> None:
        if self.worker:
            self.append_log("Interruption requested…")
            self.worker.interrupt()

    def reset_status(self) -> None:
        for i in range(self.status_list.count()):
            txt = self.status_list.item(i).text()
            title = txt.split(" ", 1)[1] if " " in txt else txt
            self.status_list.item(i).setText(f"⏳ {title}")

    # --- logging ---
    def append_log(self, msg: str) -> None:
        self.log_view.append(str(msg))
        with self.workflow_log_path.open("a") as f:
            f.write(msg + "\n")
            f.flush()

    # --- freeze/unfreeze ---
    def freeze_ui(self, frozen: bool) -> None:
        self.pre_list.setEnabled(not frozen)
        self.analysis_list.setEnabled(not frozen)
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
        if self.current_param_widgets is not None:
            for name, widget in self.current_param_widgets.items():
                #for w in widgets.values():
                widget.setEnabled(not frozen)

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

        if self._gui_log_handler is None:
            return

        skin3d_logger = logging.getLogger("skinnervation3d_app")
        skin3d_logger.removeHandler(self._gui_log_handler)
        skin3d_logger.propagate = True
        mesospim_logger = logging.getLogger("mesospim_fractal_tasks")
        mesospim_logger.removeHandler(self._gui_log_handler)
        mesospim_logger.propagate = True

        self.date = datetime.now().strftime("%Y-%m-%d_%H:%M")
        self.workflow_log_path = self.log_path / f"workflow_{self.date}.log"

        self._gui_log_handler.close()
        self._gui_log_handler = None
