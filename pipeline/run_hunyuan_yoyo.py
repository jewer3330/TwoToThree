"""Generate a geometry-only candidate with Hunyuan3D 2.1 (hy3dgen).

适配说明：原 hy3dshape 包已合并入官方 Hunyuan3D-2 仓库的 hy3dgen 包。
2.1 权重（hunyuan3d-dit-v2-1/model.fp16.ckpt + config.yaml）由
Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(subfolder='hunyuan3d-dit-v2-1',
use_safetensors=False) 加载；dit ckpt 内已含 model/vae/conditioner 三个分量。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import torch
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
# 远程（SSH/selfreg）执行时工作目录不是仓库根，先把它加进 sys.path
sys.path.insert(0, str(ROOT))

from studio_paths import LOCAL_ROOT  # noqa: E402

try:
    from hy3dgen.rembg import BackgroundRemover
    from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline
except ImportError:
    # 节点可能未把官方 hy3dgen 装入 venv，而是放在 LOCAL_ROOT/<runtime>/hy3dgen
    # （如 Hunyuan3D-2mv-runtime，单图 2.1 与多视图共用同一官方包）。这里补路径
    # 再导入，避免 ModuleNotFoundError 直接终止 GPU 任务。
    for runtime in ('Hunyuan3D-2mv-runtime', 'Hunyuan3D-2-runtime', 'hunyuan-runtime'):
        candidate = LOCAL_ROOT / runtime
        if (candidate / 'hy3dgen').is_dir():
            sys.path.insert(0, str(candidate))
            break
    from hy3dgen.rembg import BackgroundRemover
    from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path, default=ROOT / "public" / "yoyo-reference.png")
    parser.add_argument("--model", type=Path, default=LOCAL_ROOT / "Hunyuan3D-2.1-model")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "public" / "models" / "yoyo-hunyuan-shape-v1.glb",
    )
    parser.add_argument("--steps", type=int, default=30)
    parser.add_argument("--resolution", type=int, default=256)
    parser.add_argument("--seed", type=int, default=20260812)
    parser.add_argument("--processed-image-output", type=Path)
    return parser.parse_args()


def remove_small_alpha_components(image: Image.Image, minimum_fraction: float = 0.002) -> tuple[Image.Image, int]:
    """Remove disconnected labels/specks while preserving the main character silhouette."""
    alpha = image.getchannel("A")
    width, height = alpha.size
    pixels = alpha.load();visited = bytearray(width * height);components: list[list[int]] = []
    for y in range(height):
        for x in range(width):
            start = y * width + x
            if visited[start] or pixels[x, y] <= 8:
                visited[start] = 1
                continue
            visited[start] = 1;stack = [start];component = []
            while stack:
                current = stack.pop();component.append(current);cx = current % width;cy = current // width
                for nx, ny in ((cx-1,cy),(cx+1,cy),(cx,cy-1),(cx,cy+1)):
                    if 0 <= nx < width and 0 <= ny < height:
                        index = ny * width + nx
                        if not visited[index]:
                            visited[index] = 1
                            if pixels[nx, ny] > 8:stack.append(index)
            components.append(component)
    if not components:return image, 0
    largest = max(len(component) for component in components);threshold = max(24, round(largest * minimum_fraction));removed = 0
    cleaned = alpha.copy();cleaned_pixels = cleaned.load()
    for component in components:
        if len(component) >= threshold:continue
        removed += 1
        for index in component:cleaned_pixels[index % width, index // width] = 0
    result = image.copy();result.putalpha(cleaned)
    return result, removed


def remove_bottom_view_label(image: Image.Image) -> tuple[Image.Image, int | None]:
    """Trim a narrow text tail below the figure, such as FRONT/LEFT/BACK labels."""
    alpha = image.getchannel("A");bbox = alpha.point(lambda value: 255 if value > 32 else 0).getbbox()
    if not bbox:return image, None
    left, top, right, bottom = bbox;counts = [sum(1 for x in range(left, right) if alpha.getpixel((x, y)) > 32) for y in range(top, bottom)]
    peak = max(counts, default=0);start = round(len(counts) * 0.7);cutoff = None
    for index in range(start, len(counts)-1):
        current, following = counts[index], counts[index+1]
        if current > peak * 0.08 and following < current * 0.65 and following < peak * 0.3:
            cutoff = top + index
            break
    if cutoff is None:return image, None
    cleaned = alpha.copy();cleaned.paste(0, (0, cutoff, image.width, image.height));result = image.copy();result.putalpha(cleaned)
    return result, cutoff


def prepare_condition_image(image: Image.Image, size: int = 512, occupancy: float = 0.88) -> tuple[Image.Image, dict]:
    """Remove background, crop to the alpha foreground, and center it on a square canvas."""
    image = image.convert("RGBA")
    if image.getextrema()[3] == (255, 255):
        image = BackgroundRemover()(image.convert("RGB")).convert("RGBA")
    image, removed_components = remove_small_alpha_components(image)
    image, label_cutoff = remove_bottom_view_label(image)
    alpha = image.getchannel("A")
    bbox = alpha.point(lambda value: 255 if value > 8 else 0).getbbox()
    if not bbox:
        raise RuntimeError("前景提取失败：透明度蒙版为空")
    crop = image.crop(bbox)
    target = max(1, round(size * occupancy))
    scale = min(target / crop.width, target / crop.height)
    resized = crop.resize((max(1, round(crop.width * scale)), max(1, round(crop.height * scale))), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    offset = ((size - resized.width) // 2, (size - resized.height) // 2)
    canvas.alpha_composite(resized, offset)
    return canvas, {
        "sourceSize": list(image.size),
        "foregroundBox": list(bbox),
        "foregroundSize": list(crop.size),
        "outputSize": [size, size],
        "occupancy": occupancy,
        "removedSmallComponents": removed_components,
        "bottomLabelCutoff": label_cutoff,
    }


def main() -> None:
    args = parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    image, preprocessing = prepare_condition_image(Image.open(args.image))
    processed_output = args.processed_image_output or args.output.with_name("condition-front.png")
    processed_output.parent.mkdir(parents=True, exist_ok=True)
    image.save(processed_output)
    print(f"processed_image={processed_output}")
    print(f"preprocessing={preprocessing}")

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
