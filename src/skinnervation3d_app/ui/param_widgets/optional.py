from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QWidget,
    QVBoxLayout,
)

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