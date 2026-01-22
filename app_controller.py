from __future__ import annotations
import os
import logging
os.environ["QT_API"] = "pyside6"
import sys
from typing import Optional
from pathlib import Path
from PySide6.QtWidgets import QApplication, QDialog
from main_pyside import WorkflowWindow, OpeningDialog, launch_napari_in_conda_env, TASKS

logger = logging.getLogger(__name__)

class AppController:
    def __init__(self, tasks):
        self.tasks = tasks
        self.workflow_win: Optional[WorkflowWindow] = None

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

        win = WorkflowWindow(analysis_dir=analysis_dir, tasks=self.tasks)
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
            env_name="napari-crop",
        )

def main():
    app = QApplication(sys.argv)

    controller = AppController(TASKS)
    controller.start()

    # If user cancelled in the opening dialog, no window will be shown.
    # Exit cleanly.
    if QApplication.topLevelWidgets() == []:
        return

    sys.exit(app.exec())

if __name__ == "__main__":
    main()