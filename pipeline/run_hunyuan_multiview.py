"""Generate geometry from true front/left/back inputs with Tencent Hunyuan3D-2mv."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import torch
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from studio_paths import LOCAL_ROOT  # noqa: E402

RUNTIME = LOCAL_ROOT / "Hunyuan3D-2mv-runtime"
sys.path.insert(0, str(RUNTIME))

from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline  # noqa: E402
from pipeline.run_hunyuan_yoyo import prepare_condition_image  # noqa: E402
from pipeline.multiview_visual_conditioning import build_candidates  # noqa: E402


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
    parser.add_argument("--visual-conditioning", choices=("auto","original","contour","rgb_depth"), default="auto")
    parser.add_argument("--style", choices=("realistic","cartoon","chibi"), default="realistic")
    parser.add_argument("--depth-blend", type=float, default=.15)
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

    conditioned=build_candidates({"front":images["front"],"side":images["left"],"back":images["back"]},processed_dir/"visual-candidates",args.visual_conditioning,args.style,args.depth_blend)
    images={"front":Image.open(conditioned["images"]["front"]),"left":Image.open(conditioned["images"]["side"]),"back":Image.open(conditioned["images"]["back"])}
    print("visual_conditioning="+json.dumps({"selectedMode":conditioned["report"]["selectedMode"],"reportPath":str(conditioned["reportPath"])},ensure_ascii=False))
    # Load the 1.1B multiview pipeline on CPU first.  Loading all components
    # directly onto an 8 GB GPU can crash nvcuda64.dll before PyTorch can raise
    # a recoverable OOM (Windows exit 0xC0000409).
    print("memory_mode=cpu_load_model_offload", flush=True)
    pipeline = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
        str(args.model), subfolder="hunyuan3d-dit-v2-mv", variant="fp16", device="cpu", dtype=torch.float16
    )
    pipeline.components = {
        "conditioner": pipeline.conditioner,
        "model": pipeline.model,
        "vae": pipeline.vae,
    }
    pipeline.enable_model_cpu_offload()
    # This custom pipeline still uses self.device for latents and scheduler
    # tensors; offload hooks independently control where each model resides.
    pipeline.device = torch.device("cuda")
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
        generator=torch.Generator(device="cuda").manual_seed(args.seed),
        output_type="trimesh",
    )[0]
    mesh.export(args.output)
    print(f"exported={args.output}")
    print(f"vertices={len(mesh.vertices)} faces={len(mesh.faces)}")


if __name__ == "__main__":
    main()
