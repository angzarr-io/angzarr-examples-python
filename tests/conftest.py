"""pytest configuration: the router binding finds its cdylib through
ANGZARR_ROUTER_LIB, defaulting to the copy `just vendor-router` stages."""

import os
from pathlib import Path

os.environ.setdefault(
    "ANGZARR_ROUTER_LIB",
    str(
        Path(__file__).resolve().parents[1]
        / "vendor"
        / "angzarr-router-ffi"
        / "libangzarr_router_ffi.so"
    ),
)
