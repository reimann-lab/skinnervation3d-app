# =============================================================================
#  Define TaskSpec class and how to build it (auto-model from function signature)
# =============================================================================

import inspect
import re
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, get_type_hints
from pydantic import BaseModel, create_model
from dataclasses import dataclass


HIDDEN_WORKFLOW_FIELDS = {"zarr_dir", "zarr_url", "zarr_urls"}

@dataclass(frozen=True)
class TaskSpec:
    key: str
    title: str
    description: str
    fn: Callable[..., Any]
    model: Type[BaseModel]  # auto-generated from fn signature
    param_descriptions: dict[str, Any]
    category: str
    package: str
    module: str
    doc_path: Optional[str]

def _parse_doc_fn_description(fn: Callable[..., Any]) -> str:
    doc = inspect.getdoc(fn) or ""
    if doc:
        doc_lines = doc.split("\n")
        l = 0
        while (l < len(doc_lines)) and (not doc_lines[l].startswith("Parameters")):
            l += 1
        return "\n".join(doc_lines[:l])
    else:
        return ""
    
def _parse_doc_param_description(
        fn: Callable[..., Any] | type[BaseModel]) -> dict[str, str]:
    doc = inspect.getdoc(fn) or ""
    possible_headers = ("Args:", "Arguments:", "Parameters:", "Attributes:")
    if not doc:
        return {}

    lines = doc.splitlines()
    
    # Find the first relevant section header
    start = None
    for i, line in enumerate(lines):
        if line.strip() in possible_headers:
            start = i + 1
            break
    if start is None:
        return {}

    out = {}
    param_line_re = re.compile(
        r"""
        ^(?P<indent>\s+)                      # indentation
        (?P<name>[A-Za-z_][A-Za-z0-9_]*)      # param name
        (?:\s*\([^)]*\))?                     # optional "(type)" - ignored
        \s*:\s*
        (?P<desc>.*\S.*)?                     # initial description (optional, may be empty)
        $""",
        re.VERBOSE,
    )
    current_name = None
    current_desc_parts = []
    base_indent = None

    def flush():
        nonlocal current_name, current_desc_parts
        if current_name:
            # Normalize whitespace, keep it readable
            desc = " ".join(s.strip() for s in current_desc_parts if s.strip()).strip()
            if desc:
                out[current_name] = desc
        current_name = None
        current_desc_parts = []

    # Parse until we hit a non-indented line (next section) or end
    for line in lines[start:]:
        # Stop at the next top-level section header
        if line and not line.startswith(" "):  # non-indented => new section likely
            break

        if not line.strip():
            # Blank line inside Args section treated as paragraph break
            if current_name:
                current_desc_parts.append("")
            continue

        m = param_line_re.match(line)
        if m:
            flush()
            current_name = m.group("name")
            base_indent = len(m.group("indent"))
            first = (m.group("desc") or "").strip()
            if first:
                current_desc_parts.append(first)
            continue

        # Continuation line: must belong to current param and be more indented than the param line
        if current_name is not None and base_indent is not None:
            indent_len = len(line) - len(line.lstrip(" "))
            if indent_len > base_indent:
                current_desc_parts.append(line.strip())
                continue

    flush()
    return out

def build_model_from_signature(fn: Callable[..., Any]) -> Type[BaseModel]:
    """
    Create a Pydantic model from a callable signature:
      - respects type hints
      - uses defaults
      - keyword-only args are included normally
    """
    sig = inspect.signature(fn)
    type_hints = get_type_hints(fn, include_extras=True)

    fields: Dict[str, Tuple[Any, Any]] = {}

    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue

        ann = type_hints.get(name, Any)

        if param.default is inspect._empty:
            # required
            fields[name] = (ann, ...)
        else:
            # default
            # If there's no type info, still accept Any
            fields[name] = (ann, param.default)

    model_name = f"{fn.__name__}_Params"
    return create_model(model_name, **fields)  # type: ignore[arg-type]

def build_task_specs(fns: List[Callable[..., Any]], category: str) -> List[TaskSpec]:
    specs: List[TaskSpec] = []
    for fn in fns:
        package = fn.__module__.split(".")[0]
        specs.append(
            TaskSpec(
                key=fn.__name__,
                title=fn.__name__.replace("_", " ").capitalize(),
                description=_parse_doc_fn_description(fn),
                fn=fn,
                model=build_model_from_signature(fn),
                param_descriptions=_parse_doc_param_description(fn),
                category=category,
                module=fn.__module__,
                package=package,
                doc_path=None
            )
        )
    return specs
