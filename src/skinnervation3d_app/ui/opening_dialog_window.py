from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog, QLabel, QLineEdit, QPushButton, QVBoxLayout, QFileDialog)

from skinnervation3d_app.config import ANALYSIS_DIR_INIT

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
        self.default_dir = ANALYSIS_DIR_INIT
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
