"""Generate geometry from true front/left/back inputs with Tencent Hunyuan3D-2mv."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import torch
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".local" / "Hunyuan3D-2mv-runtime"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(RUNTIME))

from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline  # noqa: E402
from pipeline.run_hunyuan_yoyo import prepare_condition_image  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--front", type=Path, required=True)
    parser.add_argument("--side", type=Path, required=True)
    parser.add_argument("--back", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--processed-dir", type=Path)
    parser.add_argument("--steps", type=int, default=30)
    parser.add_argument("--resolution", type=int, default=256)
    parser.add_argument("--seed", type=int, default=12345)
    parser.add_argument("--front-weight", type=float, default=1.8)
    parser.add_argument("--side-weight", type=float, default=1.0)
    parser.add_argument("--back-weight", type=float, default=0.7)
    return parser.parse_args()


def main() -> None:
    args = parse_args();args.output.parent.mkdir(parents=True, exist_ok=True)
    processed_dir = args.processed_dir or args.output.parent / "multiview-conditions";processed_dir.mkdir(parents=True, exist_ok=True)
    sources = {"front": args.front, "left": args.side, "back": args.back}
    images: dict[str, Image.Image] = {};report = {}
    for official_role, source in sources.items():
        image, metadata = prepare_condition_image(Image.open(source));path = processed_dir / f"condition-{official_role}.png";image.save(path)
        images[official_role] = image;report[official_role] = {"source": str(source), "processed": str(path), **metadata}
        print(f"processed_{official_role}={path}")
    print("preprocessing=" + json.dumps(report, ensure_ascii=False))

    pipeline = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
        str(args.model), subfolder="hunyuan3d-dit-v2-mv", variant="fp16", device="cuda", dtype=torch.float16
    )
    view_weights = [args.front_weight, args.side_weight, args.back_weight]
    original_forward = pipeline.conditioner.forward
    def weighted_forward(*forward_args, **forward_kwargs):
        encoded = original_forward(*forward_args, **forward_kwargs)
        def weight_tensor(tensor):
            if not isinstance(tensor, torch.Tensor) or tensor.ndim != 3:
                return tensor
            if tensor.shape[1] % len(view_weights) != 0:
                return tensor
            tokens_per_view = tensor.shape[1] // len(view_weights)
            scale = torch.tensor(view_weights, device=tensor.device, dtype=tensor.dtype)
            return tensor * scale.repeat_interleave(tokens_per_view).view(1, -1, 1)
        if isinstance(encoded, dict):
            return {name: weight_tensor(value) for name, value in encoded.items()}
        return weight_tensor(encoded)
    pipeline.conditioner.forward = weighted_forward
    print("view_weights=" + json.dumps(dict(zip(("front", "side", "back"), view_weights))))
    mesh = pipeline(
        image=images,
        num_inference_steps=args.steps,
        octree_resolution=args.resolution,
        num_chunks=4000,
        generator=torch.manual_seed(args.seed),
        output_type="trimesh",
    )[0]
    mesh.export(args.output)
    print(f"exported={args.output}")
    print(f"vertices={len(mesh.vertices)} faces={len(mesh.faces)}")


if __name__ == "__main__":
    main()
