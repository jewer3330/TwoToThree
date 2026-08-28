"""Generate a geometry-only candidate with Hunyuan3D 2.1 (hy3dgen).

适配说明：原 hy3dshape 包已合并入官方 Hunyuan3D-2 仓库的 hy3dgen 包。
2.1 权重（hunyuan3d-dit-v2-1/model.fp16.ckpt + config.yaml）由
Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(subfolder='hunyuan3d-dit-v2-1',
use_safetensors=False) 加载；dit ckpt 内已含 model/vae/conditioner 三个分量。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import torch
from PIL import Image

from hy3dgen.rembg import BackgroundRemover
from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline


ROOT = Path(__file__).resolve().parents[1]


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

    pipeline = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
        str(args.model),
        subfolder="hunyuan3d-dit-v2-1",
        use_safetensors=False,
        device="cuda",
        dtype=torch.float16,
    )
    generator = torch.Generator(device="cuda").manual_seed(args.seed)
    mesh = pipeline(
        image=image,
        num_inference_steps=args.steps,
        octree_resolution=args.resolution,
        num_chunks=4000,
        generator=generator,
    )[0]
    mesh.export(str(args.output))
    print(f"exported={args.output}")
    print(f"vertices={len(mesh.vertices)} faces={len(mesh.faces)}")


if __name__ == "__main__":
    main()
