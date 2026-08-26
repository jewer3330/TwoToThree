from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
EXTERNAL_ROOT = Path(
    os.environ.get("STUDIO_EXTERNAL_ROOT", Path.home() / "AIData" / "3d")
).expanduser().resolve()
LOCAL_ROOT = EXTERNAL_ROOT / "local"
DATA_ROOT = EXTERNAL_ROOT / "data"
OUTPUT_ROOT = EXTERNAL_ROOT / "output"

