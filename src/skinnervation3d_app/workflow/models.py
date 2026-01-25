from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Protocol, Sequence

from pydantic import BaseModel

from skinnervation3d_app.tasks.spec import TaskSpec


class TaskCallable(Protocol):
    def __call__(self, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class PlanItem:
    """
    One workflow step: the TaskSpec + validated parameter model instance.
    """
    task: TaskSpec
    params: BaseModel


@dataclass(frozen=True)
class WorkflowPlan:
    items: Sequence[PlanItem]

    def __len__(self) -> int:
        return len(self.items)


@dataclass
class WorkflowResult:
    ok: bool
    final: str
    last_paths: Optional[list[Path]] = None
    last_output: Any = None