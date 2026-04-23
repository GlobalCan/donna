"""Tools — the @tool decorator + v1 tool implementations.

Importing this package triggers decorator side-effects that register every
@tool-decorated function into the REGISTRY.
"""
from . import (  # noqa: F401
    artifacts,
    attachments,
    communicate,
    exec_py,
    knowledge,
    registry,  # noqa: F401
    web,  # noqa: F401
)
from . import memory as memory_tools  # noqa: F401  (shadows stdlib-like name)


def register_all_v1_tools() -> None:
    """No-op — the import side-effects above do the registration.
    Exists so callers can be explicit: `register_all_v1_tools()`."""
    return None
