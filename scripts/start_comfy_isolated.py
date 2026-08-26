import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from studio_paths import LOCAL_ROOT

CONFLICTING_SITE_PACKAGES = str(LOCAL_ROOT / "hunyuan-bootstrap/Lib/site-packages")
COMFY_MAIN = str(LOCAL_ROOT / "ComfyUI/main.py")

if CONFLICTING_SITE_PACKAGES in sys.path:
    sys.path.remove(CONFLICTING_SITE_PACKAGES)

sys.path.insert(0, str(Path(COMFY_MAIN).parent))
sys.argv[0] = COMFY_MAIN
runpy.run_path(COMFY_MAIN, run_name="__main__")
