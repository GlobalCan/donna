"""@tool decorator + registry + schema generation from type hints."""
from __future__ import annotations

import inspect
from functools import wraps
from typing import Any, Awaitable, Callable, get_args, get_origin, get_type_hints

from ..types import ConfirmationMode, ToolEntry

REGISTRY: dict[str, ToolEntry] = {}


def tool(
    *,
    scope: str,
    cost: str = "low",
    confirmation: ConfirmationMode | str = ConfirmationMode.NEVER,
    taints_job: bool = False,
    idempotent: bool = True,
    agents: tuple[str, ...] = ("*",),
    description: str | None = None,
) -> Callable:
    """Decorator — register a tool function with metadata."""
    if isinstance(confirmation, str):
        confirmation = ConfirmationMode(confirmation)

    def decorator(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        schema = _schema_from_function(fn, description=description)

        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await fn(*args, **kwargs)

        entry = ToolEntry(
            name=fn.__name__,
            fn=wrapper,
            schema=schema,
            description=description or (fn.__doc__ or "").strip(),
            scope=scope,
            cost=cost,
            confirmation=confirmation,  # type: ignore
            taints_job=taints_job,
            idempotent=idempotent,
            agents=agents,
        )
        REGISTRY[fn.__name__] = entry
        return wrapper

    return decorator


def _schema_from_function(fn: Callable, *, description: str | None) -> dict[str, Any]:
    sig = inspect.signature(fn)
    hints = get_type_hints(fn)
    desc = description or (fn.__doc__ or "").strip()

    props: dict[str, Any] = {}
    required: list[str] = []

    for pname, param in sig.parameters.items():
        if pname in ("self", "cls"):
            continue
        hint = hints.get(pname, str)
        props[pname] = _type_to_schema(hint)
        if param.default is inspect.Parameter.empty:
            required.append(pname)
        else:
            props[pname]["default"] = param.default

    return {
        "name": fn.__name__,
        "description": desc,
        "input_schema": {
            "type": "object",
            "properties": props,
            "required": required,
            "additionalProperties": False,
        },
    }


def _type_to_schema(t: Any) -> dict[str, Any]:
    origin = get_origin(t)
    args = get_args(t)
    # Optional[X] -> X
    if origin is type(None):
        return {"type": "null"}
    if origin is not None and type(None) in args:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            schema = _type_to_schema(non_none[0])
            schema["nullable"] = True
            return schema
    if t is str:
        return {"type": "string"}
    if t is int:
        return {"type": "integer"}
    if t is float:
        return {"type": "number"}
    if t is bool:
        return {"type": "boolean"}
    if origin in (list, tuple):
        item = args[0] if args else str
        return {"type": "array", "items": _type_to_schema(item)}
    if origin is dict:
        return {"type": "object"}
    # Literal
    if origin is None and hasattr(t, "__args__") and hasattr(t, "__name__") and t.__name__ == "Literal":
        return {"type": "string", "enum": list(t.__args__)}
    from typing import Literal  # noqa
    if origin is Literal:  # type: ignore
        return {"type": "string", "enum": list(args)}
    return {"type": "string"}


def anthropic_tool_defs(agent_scope: str = "*") -> list[dict[str, Any]]:
    """Render the registry as Anthropic's `tools` parameter, filtered by agent ACL."""
    out: list[dict[str, Any]] = []
    for entry in REGISTRY.values():
        if "*" not in entry.agents and agent_scope not in entry.agents:
            continue
        out.append({
            "name": entry.name,
            "description": entry.description,
            "input_schema": entry.schema["input_schema"],
        })
    return out


def get(name: str) -> ToolEntry | None:
    return REGISTRY.get(name)


def all_tool_names() -> list[str]:
    return list(REGISTRY.keys())
