"""Alias module so step defs can `from projector import OutputProjector`.

The canonical projector lives in ``main.py``; this file re-exports it so the
behave suite's ``features/steps/projector_steps.py`` resolves cleanly, without
relying on ``sys.path`` module ordering (``hand-flow/main.py`` would otherwise
shadow ``prj-output/main.py``).
"""

import importlib.util as _importlib_util
import pathlib as _pathlib

_spec = _importlib_util.spec_from_file_location(
    "prj_output_main", _pathlib.Path(__file__).with_name("main.py")
)
_module = _importlib_util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

OutputProjector = _module.OutputProjector

__all__ = ["OutputProjector"]
