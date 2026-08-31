from pathlib import Path
from studio_paths import OUTPUT_ROOT

from PIL import Image, ImageChops, ImageOps


SOURCES = [
    Path(r"C:\Users\vip\Desktop\2886196_20251012185030473223_0.jpg"),
    Path(r"C:\Users\vip\Desktop\3786496_20251206233102218200_0.jpg"),
]
OUTPUT_DIR = OUTPUT_ROOT / "three_views_512x1024"
VIEW_NAMES = ("front", "side", "back")
CANVAS_SIZE = (512, 1024)


def content_bbox(image: Image.Image, threshold: int = 245):
    rgb = image.convert("RGB")
    # Treat near-white JPEG noise as background.
    mask = ImageOps.grayscale(ImageChops.difference(rgb, Image.new("RGB", rgb.size, "white")))
    mask = mask.point(lambda value: 255 if value > 255 - threshold else 0)
    return mask.getbbox()


def split_and_resize(source: Path):
    image = Image.open(source).convert("RGB")
    width, height = image.size
    results = []

    for index, name in enumerate(VIEW_NAMES):
        left = round(index * width / 3)
        right = round((index + 1) * width / 3)
        panel = image.crop((left, 0, right, height))
        bbox = content_bbox(panel)
        if bbox is None:
            raise RuntimeError(f"No foreground found in {source.name}, view {name}")

        padding = 8
        x0 = max(0, bbox[0] - padding)
        y0 = max(0, bbox[1] - padding)
        x1 = min(panel.width, bbox[2] + padding)
        y1 = min(panel.height, bbox[3] + padding)
        subject = panel.crop((x0, y0, x1, y1))

        max_width = int(CANVAS_SIZE[0] * 0.88)
        max_height = int(CANVAS_SIZE[1] * 0.88)
        scale = min(max_width / subject.width, max_height / subject.height)
        resized = subject.resize(
            (round(subject.width * scale), round(subject.height * scale)),
            Image.Resampling.LANCZOS,
        )

        canvas = Image.new("RGB", CANVAS_SIZE, "white")
        position = (
            (CANVAS_SIZE[0] - resized.width) // 2,
            (CANVAS_SIZE[1] - resized.height) // 2,
        )
        canvas.paste(resized, position)

        output = OUTPUT_DIR / f"{source.stem}_{index + 1}_{name}_512x1024.png"
        canvas.save(output, "PNG", optimize=True)
        results.append(output)
    return results


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for source in SOURCES:
        for output in split_and_resize(source):
            print(output)


if __name__ == "__main__":
    main()
