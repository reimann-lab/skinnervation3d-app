from __future__ import annotations
import os
import logging
os.environ["QT_API"] = "pyside6"
import sys
from typing import Optional
from pathlib import Path
from PySide6.QtWidgets import QApplication, QDialog
from skinnervation3d_app.ui.workflow_window import WorkflowWindow
from skinnervation3d_app.ui.opening_dialog_window import OpeningDialog
from skinnervation3d_app.services.napari import launch_napari_in_conda_env
from skinnervation3d_app.services.server import DocsServer
from skinnervation3d_app.tasks.registry import TASKS

logger = logging.getLogger(__name__)

class AppController:
    def __init__(self, tasks):
        self.tasks = tasks
        self.workflow_win: Optional[WorkflowWindow] = None

        app_root = Path(__file__).resolve().parents[2]
        docs_root = app_root / "resources" / "docs"

        self.docs_server = DocsServer(docs_root=docs_root)

    def start(self) -> None:
        self._show_opening_dialog()

    def _show_opening_dialog(self) -> None:
        welcome = OpeningDialog()
        chosen_dir: Optional[Path] = None

        def on_dir_selected(p: Path) -> None:
            nonlocal chosen_dir
            chosen_dir = p

        welcome.dir_selected.connect(on_dir_selected)
        
        if welcome.exec() != QDialog.Accepted or chosen_dir is None:
            return  # user cancelled -> quit app 

        self._show_workflow_window(chosen_dir)

    def _show_workflow_window(self, analysis_dir: Path):
        if self.workflow_win is not None:
            self.workflow_win.close()
            self.workflow_win.deleteLater()
            self.workflow_win = None

        win = WorkflowWindow(
            analysis_dir=analysis_dir, 
            tasks=self.tasks, 
            docs_server=self.docs_server)
        win.request_change_analysis_dir.connect(self._on_change_analysis_dir)
        win.request_open_napari.connect(self._on_open_napari)
        win.show()
        self.workflow_win = win

    def _on_change_analysis_dir(self):
        
        # close workflow and go back to opening dialog
        if self.workflow_win is not None:
            self.workflow_win.close()
            self.workflow_win.deleteLater()
            self.workflow_win = None
        self._show_opening_dialog()

    def _on_open_napari(self, analysis_dir: Path, selected_zarr: str | None):
        launch_napari_in_conda_env(
            analysis_dir=analysis_dir,
            zarr_paths=[selected_zarr],
        )

def run_app() -> int:
    app = QApplication(sys.argv)

    controller = AppController(TASKS)

    # Stop docs server when the app is quitting
    app.aboutToQuit.connect(controller.docs_server.stop)

    controller.start()

    # If user cancelled in the opening dialog, no window will be shown.
    # Exit cleanly.
    if QApplication.topLevelWidgets() == []:
        return 0

    return sys.exit(app.exec())

if __name__ == "__main__":
    run_app()
