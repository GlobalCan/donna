"""Compat shim — re-export from exec_py so `from donna.tools import exec` works.
(`exec` is a Python builtin; the real module is `exec_py`.)"""
from .exec_py import run_python  # noqa: F401
