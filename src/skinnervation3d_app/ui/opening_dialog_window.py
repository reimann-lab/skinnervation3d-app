from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QFileDialog,
    QHBoxLayout,
    QMessageBox,
)

from skinnervation3d_app.config import ANALYSIS_DIR_INIT
from skinnervation3d_app.services.server import DocsServer


class OpeningDialog(QDialog):
    dir_selected = Signal(Path)

    def __init__(
        self,
        docs_server: DocsServer | None = None,
    ):
        super().__init__()
        self.setWindowTitle("SkInnervation3D\n Workflow Manager")
        self._intro_doc_path = "app"
        self._docs_server = docs_server

        title = QLabel("<h2>SkInnervation3D - Workflow Manager</h2>")
        desc = QLabel(
            "Select a directory to start processing files in it.\n"
            "Once selected, the workflow manager window will open."
        )
        desc.setWordWrap(True)

        self.dir_line = QLineEdit()
        self.dir_line.setReadOnly(True)

        # Default path (shown immediately)
        self.default_dir = ANALYSIS_DIR_INIT
        self.dir_line.setPlaceholderText("No directory selected")

        choose_btn = QPushButton("Choose directory…")
        choose_btn.clicked.connect(self.choose_dir)

        self.intro_btn = QPushButton("Introduction")
        self.intro_btn.clicked.connect(self._open_intro_docs)
        self.intro_btn.setEnabled(
        self._docs_server is not None and self._intro_doc_path is not None
    )

        # --- Top bar (button aligned right)
        top_bar = QHBoxLayout()
        top_bar.addStretch()
        top_bar.addWidget(self.intro_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(top_bar)

        layout.addWidget(title)
        layout.addWidget(desc)
        layout.addSpacing(12)
        layout.addWidget(self.dir_line)

        choose_btn = QPushButton("Choose directory…")
        choose_btn.clicked.connect(self.choose_dir)

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

    def _open_intro_docs(self) -> None:
        if self._docs_server is None or self._intro_doc_path is None:
            return

        try:
            if not self._docs_server.is_running:
                self._docs_server.start()

            url = self._docs_server.make_url_crossplatform(self._intro_doc_path)
            QDesktopServices.openUrl(QUrl(url))

        except Exception as e:
            QMessageBox.warning(
                self,
                "Could not open introduction",
                f"Could not open intro documentation:\n{e}",
            )