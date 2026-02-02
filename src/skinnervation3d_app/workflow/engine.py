from __future__ import annotations

import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from pydantic import BaseModel

from .models import WorkflowPlan, WorkflowResult
from .outputs import extract_output_paths


@dataclass(frozen=True)
class EngineHooks:
    """
    Optional callbacks for UI/CLI integration.
    All are optional; engine runs fine without any hooks.
    """
    on_log: Optional[Callable[[str], None]] = None
    on_task_started: Optional[Callable[[int, int, str], None]] = None
    on_task_finished: Optional[Callable[[int, int, str], None]] = None


class InterruptFlag:
    """
    Minimal interrupt interface.
    Your Qt worker can hold one of these and call .interrupt().
    """
    def __init__(self) -> None:
        self._flag = False

    def interrupt(self) -> None:
        self._flag = True

    def is_interrupted(self) -> bool:
        return self._flag


def _log(hooks: EngineHooks, msg: str) -> None:
    if hooks.on_log:
        hooks.on_log(msg)


def _chain_zarr_url(task_model_cls: type[BaseModel], params: BaseModel, last_paths: Optional[list[Path]]) -> BaseModel:
    """
    If the next task accepts `zarr_url` and we have a last output path,
    inject it and re-validate using the task's model class.
    """
    if last_paths is None:
        return params
    
    if len(last_paths) > 1:
        raise ValueError("Multiple output paths detected. Only one is supported.")

    if "zarr_url" not in getattr(task_model_cls, "model_fields", {}):
        return params

    data = dict(params.model_dump())
    data["zarr_url"] = str(last_paths[0])
    return task_model_cls(**data)

def pretty_dict_display(d: dict[str, Any]) -> str:
    text = ""
    for k, v in d.items():
        if isinstance(v, dict):
            text = text + f"  {k}:\n"
            text = text + f"    {pretty_dict_display(v)}"
        else:
            text += f"  {k}: {v}\n"
    return text

def run_workflow(
    *,
    plan: WorkflowPlan,
    analysis_dir: Path,
    selected_image: Optional[Path] = None,
    auto_visualize: bool = False,
    hooks: Optional[EngineHooks] = None,
    interrupt: Optional[InterruptFlag] = None,
    # external actions (wire later)
    visualize_fn: Callable[[Path, list[Path]], None],
    email_fn: Optional[Callable[[str, str], None]] = None,
) -> WorkflowResult:
    """
    Pure-Python workflow runner.

    - Executes tasks sequentially.
    - Supports interruption via InterruptFlag.
    - Chains last output zarr_url into next task if supported.
    - Leaves "visualize" and "email" to injected callables (optional).

    Returns WorkflowResult with ok/final/last_paths.
    """
    hooks = hooks or EngineHooks()
    interrupt = interrupt or InterruptFlag()

    total = len(plan)
    ok = True
    final = "Success"
    last_paths: Optional[list[Path]] = None
    last_output: Any = None

    _log(hooks, f"\n=== Workflow started ({total} task(s)) ===")
    _log(hooks, f"Directory: {analysis_dir}")

    try:
        for idx, item in enumerate(plan.items, start=1):
            if interrupt.is_interrupted():
                ok = False
                final = "Interrupted"
                _log(hooks, "Workflow interruption requested. Stopping before next task.")
                break

            task = item.task
            params_model = item.params

            if idx > 1:

                # Chain zarr_url output to zarr_url input if applicable
                params_model = _chain_zarr_url(task.model, params_model, last_paths)

            if hooks.on_task_started:
                hooks.on_task_started(idx, total, task.title)
            _log(hooks, f"[{idx}/{total}] START {task.title}")
            _log(hooks, f"Parameters:\n")
            _log(hooks, f"{pretty_dict_display(params_model.model_dump())}")
            _log(hooks, "-" * 79 + "\n")

            # Execute
            out = task.fn(**params_model.model_dump())
            last_output = out

            # Extract outputs for chaining / visualization
            last_paths = extract_output_paths(out)

            _log(hooks, f"[{idx}/{total}] DONE  {task.title}")
            if hooks.on_task_finished:
                hooks.on_task_finished(idx, total, task.title)

        # Optional auto-visualize (external)
        if ok and auto_visualize: #and visualize_fn is not None:
            if last_paths is None:
                if selected_image is None:
                    _log(hooks, "Output visualization enabled, but no output detected.")
                    raise ValueError("No output detected and no image selected.")
                else:
                    paths_to_open = [selected_image.parent / selected_image.name]
            else:
                paths_to_open = [p.parent / p.name for p in last_paths]
            paths_str = ", ".join(map(str, paths_to_open))
            _log(hooks, f"Output visualization: opening in Napari: " + paths_str)
            try:
                visualize_fn(analysis_dir=analysis_dir, 
                             zarr_paths=paths_to_open) 
                
            except Exception as e:
                _log(hooks, f"Output visualization failed: {e!r}")

            #if to_open:
            #    _log(hooks, "Output visualization: opening external viewer…")
            #    visualize_fn(analysis_dir, to_open)
            #else:
            #    _log(hooks, "Output visualization enabled, but no output detected.")

        # Optional email (external)
        if email_fn is not None:
            subject = f"Workflow finished: {final}"
            body = f"Directory: {analysis_dir}\nResult: {final}\n"
            try:
                email_fn(subject, body)
                _log(hooks, "Email notification sent.")
            except Exception as e:
                _log(hooks, f"Email notification failed: {e!r}")

    except Exception:
        ok = False
        final = "Failed"
        last_paths = None
        _log(hooks, "ERROR:\n" + traceback.format_exc())

    _log(hooks, f"=== Workflow finished: {final} ===\n")
    return WorkflowResult(ok=ok, final=final, last_paths=last_paths, last_output=last_output)