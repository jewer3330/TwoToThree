"""Submit a conservative eye-depth inpainting smoke test to local ComfyUI."""

from __future__ import annotations

import argparse
import json
import shutil
import time
import urllib.request
import uuid
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
COMFY = ROOT / ".local" / "ComfyUI"


def request_json(url: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--server", default="http://127.0.0.1:8188")
    parser.add_argument("--seed", type=int, default=20260814)
    parser.add_argument("--denoise", type=float, default=0.28)
    parser.add_argument("--eye-box", default="350,395,420,485")
    args = parser.parse_args()

    image = Image.open(args.source).convert("RGBA")
    x1, y1, x2, y2 = (int(v) for v in args.eye_box.split(","))
    alpha = Image.new("L", image.size, 255)
    ImageDraw.Draw(alpha).ellipse((x1, y1, x2, y2), fill=0)
    image.putalpha(alpha)
    input_name = f"comment-eye-depth-{uuid.uuid4().hex[:8]}.png"
    input_path = COMFY / "input" / input_name
    input_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(input_path)

    positive = (
        "preserve the exact same cute acorn character and side-view illustration, "
        "the visible eye is a simple flat dark-brown vertical oval matching the original design, "
        "it sits slightly recessed into a shallow eye socket with a thin subtle eyelid rim, "
        "the eye surface does not protrude beyond the facial contour, no glossy highlights, "
        "same face width, same pupil height, same expression, same hand-drawn line art and colors"
    )
    negative = (
        "closed eye, missing eye, black hollow socket, deep hole, deformed face, changed identity, "
        "changed head shape, changed hair, changed nose, extra eye, anime eye, glossy eye, "
        "white eye, gray eye, photorealistic, blurry"
    )
    workflow = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd-v1-5-inpainting.ckpt"}},
        "2": {"class_type": "LoadImage", "inputs": {"image": input_name}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["1", 1]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["1", 1]}},
        "5": {"class_type": "VAEEncodeForInpaint", "inputs": {"pixels": ["2", 0], "vae": ["1", 2], "mask": ["2", 1], "grow_mask_by": 6}},
        "6": {"class_type": "KSampler", "inputs": {"seed": args.seed, "steps": 24, "cfg": 7.0, "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": args.denoise, "model": ["1", 0], "positive": ["3", 0], "negative": ["4", 0], "latent_image": ["5", 0]}},
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["1", 2]}},
        "8": {"class_type": "SaveImage", "inputs": {"filename_prefix": "comment_reference_drafts/eye-depth", "images": ["7", 0]}},
    }
    queued = request_json(f"{args.server}/prompt", {"prompt": workflow, "client_id": uuid.uuid4().hex})
    prompt_id = queued["prompt_id"]
    deadline = time.monotonic() + 1200
    while time.monotonic() < deadline:
        history = request_json(f"{args.server}/history/{prompt_id}")
        if prompt_id in history:
            record = history[prompt_id]
            if record.get("status", {}).get("status_str") == "error":
                raise RuntimeError(json.dumps(record.get("status"), ensure_ascii=False))
            images = record.get("outputs", {}).get("8", {}).get("images", [])
            if images:
                item = images[0]
                source = COMFY / "output" / item.get("subfolder", "") / item["filename"]
                target_dir = ROOT / "output" / "comment-reference-drafts"
                target_dir.mkdir(parents=True, exist_ok=True)
                target = target_dir / item["filename"]
                shutil.copy2(source, target)
                print(json.dumps({"promptId": prompt_id, "source": str(args.source), "maskedInput": str(input_path), "output": str(target), "seed": args.seed, "denoise": args.denoise}, ensure_ascii=False))
                return
        time.sleep(2)
    raise TimeoutError(f"ComfyUI prompt {prompt_id} did not finish")


if __name__ == "__main__":
    main()
