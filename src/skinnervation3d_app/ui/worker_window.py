# src/skinnervation3d_app/ui/worker.py
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal, Slot

from skinnervation3d_app.workflow.engine import EngineHooks, InterruptFlag, run_workflow
from skinnervation3d_app.workflow.models import WorkflowPlan, WorkflowResult
from skinnervation3d_app.services.napari import launch_napari_in_conda_env

class WorkflowWorker(QObject):
    log = Signal(str)
    task_started = Signal(int, int, str)
    task_finished = Signal(int, int, str)
    finished = Signal(bool, str)

    def __init__(
        self,
        *,
        analysis_dir: Path,
        selected_image: Optional[Path],
        plan: WorkflowPlan,
        auto_visualize: bool,
        visualize_fn=launch_napari_in_conda_env,
    ):
        super().__init__()
        self.analysis_dir = analysis_dir
        self.selected_image = selected_image
        self.plan = plan
        self.auto_visualize = auto_visualize
        self._interrupt = InterruptFlag()
        self._visualize_fn = visualize_fn

    def interrupt(self) -> None:
        self._interrupt.interrupt()

    @Slot()
    def run(self) -> None:
        hooks = EngineHooks(
            on_log=self.log.emit,
            on_task_started=self.task_started.emit,
            on_task_finished=self.task_finished.emit,
        )
        result: WorkflowResult = run_workflow(
            plan=self.plan,
            analysis_dir=self.analysis_dir,
            selected_image=self.selected_image,
            auto_visualize=self.auto_visualize,
            hooks=hooks,
            interrupt=self._interrupt,
            visualize_fn=self._visualize_fn
        )
        self.finished.emit(result.ok, result.final)