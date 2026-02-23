from __future__ import annotations

from typing import Any
from PySide6.QtWidgets import (
    QCheckBox,
    QWidget,
    QLineEdit,
    QSpinBox,
    QDoubleSpinBox,
)

def build_leaf_widget(tp: Any, default: Any = None) -> QWidget:
    if tp is int:
        w = QSpinBox()
        w.setRange(-2_147_483_648, 2_147_483_647) 
        if default not in (None, ...):
            w.setValue(int(default))
        return w

    if tp is float:
        w = QDoubleSpinBox()
        w.setDecimals(3)
        w.setSingleStep(0.001)
        w.setRange(-1e6, 1e6)
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

def read_leaf_widget_value(widget: QWidget) -> Any:
    if isinstance(widget, QSpinBox):
        return int(widget.value())
    if isinstance(widget, QDoubleSpinBox):
        return float(widget.value())
    if isinstance(widget, QCheckBox):
        return bool(widget.isChecked())
    if isinstance(widget, QLineEdit):
        txt = widget.text().strip()
        return txt

    raise TypeError(f"Unsupported leaf widget: {type(widget)}")

def set_leaf_widget_value(widget: QWidget, val: Any) -> None:
    if isinstance(widget, QSpinBox):
        if val is not None:
            widget.setValue(int(val))
    elif isinstance(widget, QDoubleSpinBox):
        if val is not None:
            widget.setValue(float(val))
    elif isinstance(widget, QCheckBox):
        if val is not None:
            widget.setChecked(bool(val))
    elif isinstance(widget, QLineEdit):
        widget.setText("" if val is None else str(val))
    else:
        raise TypeError(f"Unsupported leaf widget: {type(widget)}")