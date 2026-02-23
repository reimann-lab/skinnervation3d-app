from __future__ import annotations

import re
from typing import Any, get_args
from pydantic import ValidationError, TypeAdapter
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QLabel,
    QHBoxLayout,
    QLineEdit
)

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
            item = QListWidgetItem(str(it))
            item.setData(Qt.UserRole, it)  # <-- was missing
            self.view.addItem(item)

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
        tokens = self.split_tokens(text)
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
        #for i, v in enumerate(self._items):
        #    self.view.item(i).setData(Qt.UserRole, v)

    def split_tokens(self, text: str) -> list[str]:
        text = text.strip()
        if not text:
            return []
        
        SEP_PATTERN = re.compile(
            r"""
            [,\s;/|]+            # comma, whitespace, semicolon, slash, pipe 
            """, re.VERBOSE)
        
        parts = SEP_PATTERN.split(text)
        return [p for p in (x.strip() for x in parts) if p]

    def value(self) -> list[Any]:
        # If reorder is enabled, read current order from view
        if self.view.dragDropMode() == QListWidget.InternalMove:
            self._sync_items_from_view()

        # Validate whole list
        try:
            return TypeAdapter(self.list_type).validate_python(self._items)
        except ValidationError as e:
            raise ValueError(f"Invalid list value: {e}") from e