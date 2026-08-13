"""Generate a geometry-only YOYO candidate with Hunyuan3D 2.1."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import torch
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / ".local" / "Hunyuan3D-2.1-space" / "hy3dshape"
sys.path.insert(0, str(SOURCE_ROOT))

from hy3dshape.pipelines import Hunyuan3DDiTFlowMatchingPipeline  # noqa: E402
from hy3dshape.rembg import BackgroundRemover  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path, default=ROOT / "public" / "yoyo-reference.png")
    parser.add_argument("--model", type=Path, default=ROOT / ".local" / "Hunyuan3D-2.1-model")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "public" / "models" / "yoyo-hunyuan-shape-v1.glb",
    )
    parser.add_argument("--steps", type=int, default=30)
    parser.add_argument("--resolution", type=int, default=256)
    parser.add_argument("--seed", type=int, default=20260812)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    image = Image.open(args.image).convert("RGBA")
    if image.getextrema()[3] == (255, 255):
        image = BackgroundRemover()(image.convert("RGB"))

    # Load on CPU first: loading the complete 3.3B pipeline directly on an
    # 8 GB GPU can OOM before Accelerate has a chance to install offload hooks.
    pipeline = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
        str(args.model), device="cpu", dtype=torch.float16
    )
    # Hunyuan3D 2.1 ships a lightweight custom pipeline rather than a
    # Diffusers DiffusionPipeline subclass, while its offload helper expects
    # the standard component mapping.
    pipeline.components = {
        "conditioner": pipeline.conditioner,
        "model": pipeline.model,
        "vae": pipeline.vae,
    }
    pipeline.enable_model_cpu_offload()
    # Offload hooks move modules on demand, but this custom pipeline still
    # reads self.device when creating latents and scheduler tensors.
    pipeline.device = torch.device("cuda")
    generator = torch.Generator(device="cuda").manual_seed(args.seed)
    mesh = pipeline(
        image=image,
        num_inference_steps=args.steps,
        octree_resolution=args.resolution,
        num_chunks=4000,
        generator=generator,
    )[0]
    mesh.export(args.output)
    print(f"exported={args.output}")
    print(f"vertices={len(mesh.vertices)} faces={len(mesh.faces)}")


if __name__ == "__main__":
    main()
