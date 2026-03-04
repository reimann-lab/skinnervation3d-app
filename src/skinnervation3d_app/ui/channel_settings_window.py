from __future__ import annotations
from pathlib import Path
import json
import re
from typing import Any, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QMessageBox, QInputDialog, QLineEdit, 
    QFormLayout, QDialogButtonBox, QTableWidget, QTableWidgetItem,
    QColorDialog, QWidget, QFrame
)
from pydantic import ValidationError

from skinnervation3d_app.utils.models import ChannelEntry

PRESET_RE = re.compile(r"^channel_color_(.+)\.json$")



class ChannelPresetEditorDialog(QDialog):
    """
    Edits ONE preset mapping: { "<laser>": {label,color,laser_wavelength}, ... }

    Left: existing entries (laser keys)
    Right: form
      - defaults when empty
      - selecting an entry loads it
    Buttons:
      - Add entry: creates NEW entry from form (never overwrites selection)
      - Edit entry: updates selected entry from form
      - Remove entry: deletes selected entry
    """
    DEFAULTS = {
        "label": "",
        "color": "FFFFFF",
        "laser_wavelength": "",
    }

    def __init__(self, parent, initial_data: Dict[str, Any] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Edit channel preset")
        self.setModal(True)
        self.resize(860, 480)

        self._data: Dict[str, Dict[str, Any]] = {
            str(k): dict(v) for k, v in (initial_data or {}).items()
        }

        self._current_key: Optional[str] = None 

        # Outer layout for Ok/Cancel buttons
        outer = QVBoxLayout(self)

        # Content layout for actual editor UI
        content = QHBoxLayout()

        # Left panel: list of entries
        left = QVBoxLayout()
        left.addWidget(QLabel("<b>Channel Entries</b>"))
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_select)
        left.addWidget(self.list, 1)
        left.addStretch(1)

        content.addLayout(left, 1)

        # Right panel: form to edit + buttons
        right = QVBoxLayout()
        right.addWidget(QLabel("<b>Channel Settings</b>"))
        right.addSpacing(10)

        form = QFormLayout()
        self.laser_edit = QLineEdit()
        self.label_edit = QLineEdit()
        self.color_edit = QLineEdit()

        self.laser_edit.setPlaceholderText("e.g. 561 (required)")
        self.label_edit.setPlaceholderText("e.g. Lectin (required)")
        self.color_edit.setPlaceholderText("e.g. 00C853 (6 hex digits)")

        self.pick_color_btn = QPushButton("Pick…")
        self.pick_color_btn.clicked.connect(self._pick_color)

        color_layout = QHBoxLayout()
        color_layout.setContentsMargins(0, 0, 0, 0)
        color_layout.addWidget(self.color_edit)
        color_layout.addWidget(self.pick_color_btn)

        color_widget = QWidget()
        color_widget.setLayout(color_layout)

        form.addRow("laser_wavelength", self.laser_edit)
        form.addRow("label", self.label_edit)
        form.addRow("color", color_widget)
        right.addLayout(form)
        right.addStretch(1)

        entry_bar = QHBoxLayout()
        entry_bar.setSpacing(10)

        self.add_btn = QPushButton("Add entry")
        self.add_btn.clicked.connect(self._add_entry)

        self.edit_btn = QPushButton("Edit entry")
        self.edit_btn.clicked.connect(self._edit_entry)
        self.edit_btn.setEnabled(False)

        self.rm_btn = QPushButton("Remove entry")
        self.rm_btn.clicked.connect(self._remove_entry)
        self.rm_btn.setEnabled(False)

        entry_bar.addStretch(1)
        entry_bar.addWidget(self.add_btn)
        entry_bar.addWidget(self.edit_btn)
        entry_bar.addWidget(self.rm_btn)
        right.addLayout(entry_bar)

        content.addLayout(right, 2)

        outer.addLayout(content, 1)

        # Separator line
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        outer.addWidget(sep)

        # Save / Cancel
        dialog_bar = QHBoxLayout()
        dialog_bar.setSpacing(10)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        self.buttons.accepted.connect(self._on_accept)
        self.buttons.rejected.connect(self.reject)
        ok_btn = self.buttons.button(QDialogButtonBox.Ok)
        ok_btn.setText("Save preset")

        dialog_bar.addStretch(1)
        dialog_bar.addWidget(self.buttons)

        outer.addLayout(dialog_bar)

        self._refresh_list()
        self._set_form_defaults()

    # ----------------------------
    # UI helpers
    # ----------------------------

    def _refresh_list(self, select_key: Optional[str] = None) -> None:
        self.list.blockSignals(True)
        self.list.clear()

        for k in sorted(self._data.keys(), key=str):
            it = QListWidgetItem(str(k))
            it.setData(Qt.UserRole, str(k))
            self.list.addItem(it)

        self.list.blockSignals(False)

        if select_key is not None:
            for row in range(self.list.count()):
                it = self.list.item(row)
                if it.data(Qt.UserRole) == select_key:
                    self.list.setCurrentRow(row)
                    return

        # If nothing selected, clear selection state
        if self.list.count() == 0:
            self.list.setCurrentRow(-1)
            self._current_key = None
            self.edit_btn.setEnabled(False)
            self.rm_btn.setEnabled(False)
        else:
            # keep current row if any
            if self.list.currentRow() < 0:
                self.list.setCurrentRow(0)

    def _set_form_defaults(self) -> None:
        self.laser_edit.setText(self.DEFAULTS["laser_wavelength"])
        self.label_edit.setText(self.DEFAULTS["label"])
        self.color_edit.setText(self.DEFAULTS["color"])

    def _load_form_from_entry(self, key: str) -> None:
        e = dict(self._data.get(key, {}))
        self.laser_edit.setText(str(e.get("laser_wavelength", key)))
        self.label_edit.setText(str(e.get("label", "")))
        self.color_edit.setText(str(e.get("color", "FFFFFF")))

    def _read_form(self) -> Dict[str, Any]:
        return {
            "laser_wavelength": self.laser_edit.text().strip(),
            "label": self.label_edit.text().strip(),
            "color": (self.color_edit.text().strip() or "FFFFFF")
        }

    def _unique_key(self, base: str) -> str:
        base = str(base)
        if base not in self._data:
            return base
        i = 2
        while f"{base}_{i}" in self._data:
            i += 1
        return f"{base}_{i}"

    def _validate_entry(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        # Uses your Pydantic ChannelEntry model
        try:
            m = ChannelEntry(**raw)
        except ValidationError as e:
            QMessageBox.warning(self, "Invalid entry", str(e))
            raise
        return m.model_dump()
    
    def _pick_color(self) -> None:
        current = self.color_edit.text().strip()
        if current:
            qcolor = QColor("#" + current)
            color = QColorDialog.getColor(qcolor, self)
        else:
            color = QColorDialog.getColor(parent=self)

        if not color.isValid():
            return

        self.color_edit.setText(color.name()[1:].upper())

    # ----------------------------
    # Slots
    # ----------------------------

    def _on_select(self, current: QListWidgetItem, previous: QListWidgetItem) -> None:
        if not current:
            self._current_key = None
            self.edit_btn.setEnabled(False)
            self.rm_btn.setEnabled(False)
            self._set_form_defaults()
            return

        key = current.data(Qt.UserRole)
        self._current_key = key
        self.edit_btn.setEnabled(True)
        self.rm_btn.setEnabled(True)
        self._load_form_from_entry(key)

    def _add_entry(self) -> None:
        raw = self._read_form()

        try:
            validated = self._validate_entry(raw)
        except ValidationError:
            return

        base_key = str(validated["laser_wavelength"])
        new_key = self._unique_key(base_key)

        validated["laser_wavelength"] = base_key
        self._data[new_key] = validated

        # refresh list but do NOT keep it selected
        self._refresh_list(select_key=None)

        # explicitly clear selection so future click triggers _on_select reliably
        self.list.blockSignals(True)
        self.list.setCurrentRow(-1)
        self.list.clearSelection()
        self.list.blockSignals(False)

        self._current_key = None
        self.edit_btn.setEnabled(False)
        self.rm_btn.setEnabled(False)

        # reset form to defaults (ready for next add)
        self._set_form_defaults()

    def _edit_entry(self) -> None:
        if not self._current_key:
            return

        raw = self._read_form()
        try:
            validated = self._validate_entry(raw)
        except ValidationError:
            return

        old_key = self._current_key
        desired_key = str(validated["laser_wavelength"])

        # If user changed laser_wavelength, rename the dict key
        if desired_key != old_key:
            # If desired_key already exists (and it's not the same entry), make it unique
            if desired_key in self._data and desired_key != old_key:
                desired_key = self._unique_key(desired_key)

            self._data.pop(old_key, None)
            self._data[desired_key] = validated
            self._current_key = desired_key
            self._refresh_list(select_key=desired_key)
        else:
            self._data[old_key] = validated
            self._refresh_list(select_key=old_key)

    def _remove_entry(self) -> None:
        if not self._current_key:
            return
        key = self._current_key
        self._data.pop(key, None)
        self._current_key = None
        self._refresh_list()
        self._set_form_defaults()

    def _on_accept(self) -> None:
        # Validate all entries before OK
        out: Dict[str, Any] = {}
        try:
            for k, v in self._data.items():
                vv = dict(v)
                vv["laser_wavelength"] = str(vv.get("laser_wavelength", k) or k)
                out[str(k)] = ChannelEntry(**vv).model_dump()
        except ValidationError as e:
            QMessageBox.warning(self, "Invalid preset", str(e))
            return

        self._data = out
        self.accept()

    def result_data(self) -> Dict[str, Any]:
        return dict(self._data)


class ChannelSettingsDialog(QDialog):
    def __init__(self, parent, settings_dir: Path):
        super().__init__(parent)
        self.setWindowTitle("Channel Settings")
        self.setModal(True)
        self.resize(950, 520)

        self.settings_dir = settings_dir
        self.settings_dir.mkdir(parents=True, exist_ok=True)

        root = QVBoxLayout(self)

        self.current_file_label = QLabel("")
        self.current_file_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.current_file_label)

        main = QHBoxLayout()
        root.addLayout(main, 1)

        # left: presets list
        left = QVBoxLayout()
        left.addWidget(QLabel("<b>Saved presets</b>"))
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_select)
        left.addWidget(self.list, 1)

        # buttons row
        btns = QHBoxLayout()
        self.new_btn = QPushButton("New…")
        self.edit_btn = QPushButton("Edit")
        self.del_btn = QPushButton("Delete")

        self.new_btn.clicked.connect(self._on_new)
        self.edit_btn.clicked.connect(self._on_edit)
        self.del_btn.clicked.connect(self._on_delete)

        btns.addWidget(self.new_btn)
        btns.addWidget(self.edit_btn)
        btns.addWidget(self.del_btn)
        left.addLayout(btns)

        main.addLayout(left, 1)

        # right: details
        right = QVBoxLayout()
        right.addWidget(QLabel("<b>Details</b>"))
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Laser", "Label", "Color"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        right.addWidget(self.table, 1)
        main.addLayout(right, 2)

        self._refresh_list()
        self._set_selected_enabled(False)

    def _set_selected_enabled(self, enabled: bool):
        self.edit_btn.setEnabled(enabled)
        self.del_btn.setEnabled(enabled)

    def _preset_files(self) -> list[Path]:
        out = []
        for p in sorted(self.settings_dir.glob("channel_color_*.json")):
            if p.is_file() and PRESET_RE.match(p.name):
                out.append(p)
        return out

    def _refresh_list(self):
        self.list.blockSignals(True)
        self.list.clear()
        for p in self._preset_files():
            m = PRESET_RE.match(p.name)
            name = m.group(1) if m else p.name
            it = QListWidgetItem(name)
            it.setData(Qt.UserRole, str(p))
            it.setToolTip(str(p))
            self.list.addItem(it)
        self.list.blockSignals(False)

        if self.list.count() > 0:
            self.list.setCurrentRow(0)
        else:
            self._on_select(None, None)

    def _selected_path(self) -> Path | None:
        it = self.list.currentItem()
        if not it:
            return None
        return Path(it.data(Qt.UserRole))

    def _on_select(self, current, previous):
        p = self._selected_path()
        if not p:
            self.current_file_label.setText("Saved file: (none selected)")
            self.details.clear()
            self._set_selected_enabled(False)
            return

        self.current_file_label.setText(f"Saved file: {p}")
        self._set_selected_enabled(True)
        self._render_table(p)

    def _read_json(self, p: Path) -> dict:
        return json.loads(p.read_text(encoding="utf-8"))

    def _render_table(self, p: Path):
        self.table.setRowCount(0)

        try:
            data = self._read_json(p)
        except Exception as e:
            # show one row with error text
            self.table.setRowCount(1)
            it = QTableWidgetItem(f"Could not read JSON: {e}")
            self.table.setItem(0, 0, it)
            self.table.setSpan(0, 0, 1, 4)
            return

        # data is expected like: { "561": {...}, "640": {...} }
        keys = sorted(data.keys(), key=lambda x: str(x))

        self.table.setRowCount(len(keys))
        for r, laser_key in enumerate(keys):
            entry = data.get(laser_key, {}) or {}

            laser = str(entry.get("laser_wavelength", laser_key))
            label = str(entry.get("label", ""))
            color = str(entry.get("color", "FFFFFF")).lstrip("#").upper()

            self.table.setItem(r, 0, QTableWidgetItem(laser))
            self.table.setItem(r, 1, QTableWidgetItem(label))

            # Color cell: show hex + background swatch
            color_item = QTableWidgetItem(color)
            try:
                qc = QColor("#" + color)
                if qc.isValid():
                    color_item.setBackground(qc)
                    # choose readable text color
                    luminance = 0.2126 * qc.red() + 0.7152 * qc.green() + 0.0722 * qc.blue()
                    color_item.setForeground(QColor("#000000" if luminance > 140 else "#FFFFFF"))
            except Exception:
                pass
            self.table.setItem(r, 2, color_item)

    def _on_edit(self):
        p = self._selected_path()
        if not p:
            return

        try:
            data = self._read_json(p)
        except Exception as e:
            QMessageBox.warning(self, "Could not read preset", str(e))
            return

        editor = ChannelPresetEditorDialog(self, initial_data=data)
        if editor.exec() != QDialog.DialogCode.Accepted:
            return

        new_data = editor.result_data()

        try:
            p.write_text(json.dumps(new_data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            QMessageBox.warning(self, "Could not save preset", str(e))
            return

        self._render_table(p)

    def _on_delete(self):
        p = self._selected_path()
        if not p:
            return

        reply = QMessageBox.question(
            self,
            "Delete preset?",
            f"Delete this preset?\n\n{p.name}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            p.unlink()
        except Exception as e:
            QMessageBox.warning(self, "Could not delete preset", str(e))
            return

        self._refresh_list()

    def _on_new(self):
        name, ok = QInputDialog.getText(
            self,
            "New preset",
            "Preset name (will create channel_color_{name}.json):",
        )
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            QMessageBox.warning(self, "Invalid name", "Name cannot be empty.")
            return

        p = self.settings_dir / f"channel_color_{name}.json"
        if p.exists():
            QMessageBox.warning(self, "Already exists", f"{p.name} already exists.")
            return

        # start from empty
        editor = ChannelPresetEditorDialog(self, initial_data={})
        if editor.exec() != QDialog.DialogCode.Accepted:
            return

        new_data = editor.result_data()
        try:
            p.write_text(json.dumps(new_data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            QMessageBox.warning(self, "Could not create preset", str(e))
            return

        self._refresh_list()
        # select newly created
        for row in range(self.list.count()):
            it = self.list.item(row)
            if Path(it.data(Qt.UserRole)).name == p.name:
                self.list.setCurrentRow(row)
                break