from __future__ import annotations

import html
from typing import Any, get_args, get_origin, Union
from pydantic import BaseModel, ValidationError, TypeAdapter
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGroupBox,
    QFormLayout)

from skinnervation3d_app.ui.param_widgets.optional import OptionalWrapperWidget
from skinnervation3d_app.ui.param_widgets.tuple_widget import TupleWidget
from skinnervation3d_app.ui.param_widgets.list_widget import ListWidget
from skinnervation3d_app.ui.param_widgets.leaf import build_leaf_widget, read_leaf_widget_value
from skinnervation3d_app.tasks.spec import (
    HIDDEN_WORKFLOW_FIELDS,
    _parse_doc_param_description)

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
        return widget.value_model()

    # Leaf
    raw = read_leaf_widget_value(widget)
    
    # Validate/coerce via pydantic
    try:
        return TypeAdapter(base).validate_python(raw)
    except ValidationError as e:
        raise ValueError(f"Invalid value for {base}: {e}") from e