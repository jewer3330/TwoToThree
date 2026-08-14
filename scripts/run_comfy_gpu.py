"""Launch the isolated ComfyUI environment with local packages taking priority.

The environment reuses only CUDA PyTorch from the existing SF3D runtime.  The
Python interpreter used to create the venv otherwise exposes Hunyuan packages
before the venv, so reorder paths before importing ComfyUI.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMFY = ROOT / ".local" / "ComfyUI"
LOCAL_SITE = COMFY / ".venv-gpu" / "Lib" / "site-packages"
TORCH_SITE = ROOT / ".local" / "stable-fast-3d" / ".venv-runtime" / "Lib" / "site-packages"

for path in (str(LOCAL_SITE), str(TORCH_SITE)):
    while path in sys.path:
        sys.path.remove(path)
sys.path.insert(0, str(TORCH_SITE))
sys.path.insert(0, str(LOCAL_SITE))
sys.path.insert(0, str(COMFY))

sys.argv[0] = str(COMFY / "main.py")
runpy.run_path(sys.argv[0], run_name="__main__")
