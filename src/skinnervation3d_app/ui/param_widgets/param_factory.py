from __future__ import annotations

import html
import uuid
from typing import Any, get_args, get_origin, Union
from pydantic import BaseModel, ValidationError, TypeAdapter
from pydantic_core import PydanticUndefined
from PySide6.QtWidgets import (
    QWidget,
    QFormLayout,
    QGroupBox,
    QVBoxLayout,
    QHBoxLayout, 
    QPushButton, 
    QLabel,
    QListWidget, 
    QListWidgetItem,
    QMessageBox
)
from PySide6.QtCore import Qt, QEvent, QPoint

from skinnervation3d_app.ui.param_widgets.optional import OptionalWrapperWidget
from skinnervation3d_app.ui.param_widgets.tuple_widget import TupleWidget
from skinnervation3d_app.ui.param_widgets.list_widget import ListWidget
from skinnervation3d_app.ui.param_widgets.leaf import (
    build_leaf_widget, read_leaf_widget_value, set_leaf_widget_value)
from skinnervation3d_app.tasks.spec import (
    HIDDEN_WORKFLOW_FIELDS,
    _parse_doc_param_description)



class ModelListMasterDetailWidget(QWidget):
    """
    Master-detail list[BaseModel] editor.

    - List shows a label for each item (e.g. Channel.label).
    - Detail editor shows ONE CustomModelWidget for add/edit.
    - Append adds a new item from editor.
    - Edit Selected updates selected item from editor.
    - Remove Selected removes selected items.
    """

    def __init__(
        self,
        list_type: Any,
        default: Any = None,
        label_field: str = "label",
        allow_multi_select: bool = True,
        parent=None,
    ):
        super().__init__(parent)

        self._by_id: dict[str, dict[str, Any]] = {}
        self._order: list[str] = []

        self.list_type = list_type
        (self.item_model_cls,) = get_args(list_type)  # BaseModel subclass
        self.label_field = label_field
        
        self._default_dict = {}
        for fname, f in self.item_model_cls.model_fields.items():
            if f.default is not PydanticUndefined:
                self._default_dict[fname] = f.default

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # Master list
        root.addWidget(QLabel("Items:"))
        self.view = QListWidget()
        self.view.viewport().installEventFilter(self)
        self.view.setSelectionMode(
            QListWidget.ExtendedSelection if allow_multi_select else QListWidget.SingleSelection
        )
        root.addWidget(self.view)

        # Detail editor
        root.addWidget(QLabel("Parameters:"))
        self.editor = CustomModelWidget(self.item_model_cls, default=None)
        root.addWidget(self.editor)

        # Buttons
        row = QHBoxLayout()
        self.btn_append = QPushButton("Append")
        self.btn_edit = QPushButton("Edit selected")
        self.btn_remove = QPushButton("Remove selected")
        row.addWidget(self.btn_append)
        row.addWidget(self.btn_edit)
        row.addWidget(self.btn_remove)
        row.addStretch(1)
        root.addLayout(row)
        root.addStretch(1)

        # Signals
        self.btn_append.clicked.connect(self._on_append)
        self.btn_edit.clicked.connect(self._on_edit_selected)
        self.btn_remove.clicked.connect(self._on_remove_selected)
        self.view.currentItemChanged.connect(self._on_current_item_changed)

        # Init with default list
        if isinstance(default, list):
            # accept list of dicts or BaseModel
            for it in default:
                self._append_raw(it)

        # start in "new item" mode
        self._reset_editor_to_model_defaults()

    # ---------- internal helpers ----------

    def eventFilter(self, watched, event):
        if watched is self.view.viewport() and event.type() == QEvent.MouseButtonPress:
            # If user clicks on empty area (no item under cursor), clear selection/current
            pos = event.pos()
            item = self.view.itemAt(pos)
            if item is None:
                self.view.blockSignals(True)
                self.view.clearSelection()
                self.view.setCurrentItem(None)
                self.view.blockSignals(False)
                self._reset_editor_to_model_defaults()
                return True  # consume event (optional)
        return super().eventFilter(watched, event)

    def _coerce_to_dict(self, item: Any) -> dict[str, Any]:
        if isinstance(item, BaseModel):
            return item.model_dump()
        if isinstance(item, dict):
            return item
        raise TypeError(f"Expected dict or BaseModel, got {type(item)}")

    def _display_text(self, d: dict[str, Any]) -> str:
        v = d.get(self.label_field, "")
        return str(v) if v is not None else ""

    def _append_raw(self, item: Any) -> None:
        d = self._coerce_to_dict(item)
        d2 = TypeAdapter(self.item_model_cls).validate_python(d).model_dump()

        item_id = uuid.uuid4().hex
        self._by_id[item_id] = d2
        self._order.append(item_id)

        lw_item = QListWidgetItem(self._display_text(d2))
        lw_item.setFlags(lw_item.flags() | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        lw_item.setData(Qt.UserRole, item_id)
        self.view.addItem(lw_item)

    def _reset_editor_to_model_defaults(self) -> None:
        # Clear everything first (now safe because leaf setters reset on None)
        for fname, fw in self.editor.widgets.items():
            set_widget_value(fw, None)

        # Apply model defaults (if any)
        for fname, val in self._default_dict.items():
            if fname in self.editor.widgets:
                set_widget_value(self.editor.widgets[fname], val)

    def _refresh_list(self, keep_current_id: str | None = None) -> None:
        self.view.blockSignals(True)
        self.view.clear()
        for item_id in self._order:
            d = self._by_id[item_id]
            it = QListWidgetItem(self._display_text(d))
            it.setFlags(it.flags() | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            it.setData(Qt.UserRole, item_id)
            self.view.addItem(it)
        self.view.blockSignals(False)

        # restore current item if requested
        if keep_current_id is not None:
            for i in range(self.view.count()):
                if self.view.item(i).data(Qt.UserRole) == keep_current_id:
                    self.view.setCurrentRow(i)
                    break

    def _current_id(self) -> str | None:
        it = self.view.currentItem()
        if it is None:
            return None
        item_id = it.data(Qt.UserRole)
        return item_id if isinstance(item_id, str) else None

    def _selected_indices(self) -> list[int]:
        # map selected QListWidgetItems to indices in self._items
        out: list[int] = []
        for it in self.view.selectedItems():
            idx = it.data(Qt.UserRole)
            if isinstance(idx, int):
                out.append(idx)
        # unique + sorted
        return sorted(set(out))

    def _load_into_editor(self, d: dict[str, Any]) -> None:
        # push dict into editor widgets
        self._reset_editor_to_model_defaults()
        for fname, fw in self.editor.widgets.items():
            if fname in d:
                set_widget_value(fw, d[fname])
            else:
                set_widget_value(fw, None)

    def _editor_value_as_dict_validated(self) -> dict[str, Any]:
        d = self.editor.value_dict()
        try:
            m = TypeAdapter(self.item_model_cls).validate_python(d)
        except ValidationError as e:
            raise ValueError(str(e)) from e
        return m.model_dump()

    # ---------- slots ----------

    def _on_current_item_changed(self, current: QListWidgetItem, previous: QListWidgetItem) -> None:
        if current is None:
            self._reset_editor_to_model_defaults()
            return

        item_id = current.data(Qt.UserRole)
        if isinstance(item_id, str) and item_id in self._by_id:
            self._load_into_editor(self._by_id[item_id])
        else:
            self._reset_editor_to_model_defaults()


    def _on_append(self) -> None:
        try:
            d = self._editor_value_as_dict_validated()
        except ValueError as e:
            QMessageBox.critical(self, "Invalid item", str(e))
            return
        self._append_raw(d)
        
        self.view.setCurrentItem(None)  # clears current -> triggers reset
        self.view.clearSelection()
        self._reset_editor_to_model_defaults()

        #self.view.setCurrentRow(len(self._order) - 1)

    def _on_edit_selected(self) -> None:
        # Use current item for editing (detail panel is single-item)
        item_id = self._current_id()
        if item_id is None or item_id not in self._by_id:
            QMessageBox.information(self, "Edit selected", "Select exactly one item to edit.")
            return

        try:
            d = self._editor_value_as_dict_validated()
        except ValueError as e:
            QMessageBox.critical(self, "Invalid item", str(e))
            return

        self._by_id[item_id] = d
        self._refresh_list(keep_current_id=item_id)

    def _on_remove_selected(self) -> None:
        ids: list[str] = []
        for it in self.view.selectedItems():
            item_id = it.data(Qt.UserRole)
            if isinstance(item_id, str) and item_id in self._by_id:
                ids.append(item_id)

        if not ids:
            return

        for item_id in ids:
            self._by_id.pop(item_id, None)
            if item_id in self._order:
                self._order.remove(item_id)

        self._refresh_list()
        self.view.setCurrentItem(None)
        self.view.clearSelection()
        self._reset_editor_to_model_defaults()

    # ---------- public API used by your framework ----------

    def value(self) -> list[Any]:
        data = [self._by_id[item_id] for item_id in self._order]
        try:
            return TypeAdapter(self.list_type).validate_python(data)
        except ValidationError as e:
            raise ValueError(f"Invalid list value: {e}") from e

    def set_value(self, val: Any) -> None:
        self._by_id.clear()
        self._order.clear()
        self.view.clear()

        if isinstance(val, list):
            for it in val:
                self._append_raw(it)

        self.view.setCurrentItem(None)
        self.view.clearSelection()
        self._reset_editor_to_model_defaults()



class CustomModelWidget(QWidget):
    """
    GUI for a nested Pydantic BaseModel.
    """
    def __init__(
        self, 
        model_cls: type[BaseModel], 
        default: Any = None, 
        parent=None
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

        param_descriptions = _parse_doc_param_description(model_cls)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.group = QGroupBox()
        outer.addWidget(self.group)

        self.widgets = build_widgets_from_model(model_cls, 
                                                defaults=default_dict, 
                                                param_descriptions=param_descriptions)

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

def is_pydantic_model_type(tp: Any) -> bool:
    tp = unwrap_optional(tp)
    try:
        return isinstance(tp, type) and issubclass(tp, BaseModel)
    except TypeError:
        return False
    
def is_list_of_pydantic_models(tp: Any) -> bool:
    tp0 = unwrap_optional(tp)
    if get_origin(tp0) is not list:
        return False
    (item_type,) = get_args(tp0)
    try:
        return isinstance(item_type, type) and issubclass(item_type, BaseModel)
    except TypeError:
        return False
    
def fixed_width_tooltip(text: str, width_px: int = 360) -> str:
    """
    Return rich-text tooltip HTML with a fixed pixel width
    and proper line wrapping.
    """
    safe = html.escape(text).replace("\n", "<br>")
    return f"""
    <div style="
        width:{width_px}px;
        white-space:normal;
        word-wrap:break-word;
    ">
        {safe}
    </div>
    """

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
            if is_list_of_pydantic_models(ann_full):
                inner = ModelListMasterDetailWidget(
                    ann,
                    default=default if isinstance(default, list) else [],
                    label_field="label",
                )
            else:
                inner = ListWidget(
                    ann,
                    default=default if isinstance(default, list) else [],
                    allow_reorder=True,
                )
            
        elif is_pydantic_model_type(ann_full):
            if isinstance(default, BaseModel):
                nested_default = default.model_dump()
            elif isinstance(default, dict):
                nested_default = default
            else:
                nested_default = {}
            inner = CustomModelWidget(ann, default=nested_default)
            if opt:
                default = None

        else:
            inner = build_leaf_widget(ann, default=default)

        # Wrap optional
        if opt:
            inner = OptionalWrapperWidget(inner, default_is_none=(default is None))
        
        inner.setToolTip(fixed_width_tooltip(param_desc, width_px=360))

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
        return widget.value_dict()
    
    if isinstance(widget, ModelListMasterDetailWidget):
        return widget.value()

    # Leaf
    raw = read_leaf_widget_value(widget)
    
    # Validate/coerce via pydantic
    try:
        return TypeAdapter(base).validate_python(raw)
    except ValidationError as e:
        raise ValueError(f"Invalid value for {base}: {e}") from e
    
def set_widget_value(w: QWidget, val: Any) -> None:
    if isinstance(w, OptionalWrapperWidget):
        if val is None:
            w.set_enabled(False)
            return
        w.set_enabled(True)
        w = w.inner

    if isinstance(w, ListWidget):
        w._items = list(val) if isinstance(val, list) else []
        w._refresh_from_items()
    elif isinstance(w, ModelListMasterDetailWidget):
        w.set_value(val)
    elif isinstance(w, TupleWidget):
        w.set_value(val)
    elif isinstance(w, CustomModelWidget):
        if isinstance(val, dict):
            for fname, fw in w.widgets.items():
                if fname in val:
                    set_widget_value(fw, val[fname])
    else:
        set_leaf_widget_value(w, val)  # handles QSpinBox, QDoubleSpinBox, QCheckBox, QLineEdit