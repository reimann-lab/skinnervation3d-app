from __future__ import annotations

from typing import Any, get_args
from pydantic import ValidationError, TypeAdapter
from PySide6.QtWidgets import (
    QWidget,
    QFormLayout,
)

from skinnervation3d_app.ui.param_widgets.leaf import (
    build_leaf_widget,
    read_leaf_widget_value,
)

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
            raw = read_leaf_widget_value(w)
            try:
                v = TypeAdapter(t).validate_python(raw)
            except ValidationError as e:
                raise ValueError(f"Invalid tuple element ({t}): {e}") from e
            out.append(v)
        return tuple(out)
    
    def set_value(self, val: tuple | list) -> None:
        items = list(val) if isinstance(val, (tuple, list)) else [None] * len(self.widgets)
        for w, v in zip(self.widgets, items):
            from skinnervation3d_app.ui.param_widgets.leaf import set_leaf_widget_value
            set_leaf_widget_value(w, v)