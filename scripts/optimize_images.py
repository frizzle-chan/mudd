#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow>=10.0.0"]
# ///
"""Optimize images from img-src/ to img-dist/.

Resizes images to max 1000px on longest side, strips metadata,
and runs optimization tools (pngquant for PNG, jpegoptim for JPEG, gifsicle for GIF).
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).parent.parent
SRC_DIR = REPO_ROOT / "img-src"
DIST_DIR = REPO_ROOT / "img-dist"
MAX_DIMENSION = 1000
SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif"}


def normalize_filename(name: str) -> str:
    """Normalize filename to lowercase snake_case with only alphanumeric chars."""
    # Lowercase
    name = name.lower()
    # Replace spaces and hyphens with underscores
    name = re.sub(r"[\s\-]+", "_", name)
    # Remove non-alphanumeric chars (keep underscores)
    name = re.sub(r"[^a-z0-9_]", "", name)
    # Collapse multiple underscores
    name = re.sub(r"_+", "_", name)
    # Strip leading/trailing underscores
    name = name.strip("_")
    return name


def check_dependencies() -> bool:
    """Check that required external tools are installed."""
    missing = []
    if not shutil.which("pngquant"):
        missing.append("pngquant")
    if not shutil.which("jpegoptim"):
        missing.append("jpegoptim")
    if not shutil.which("gifsicle"):
        missing.append("gifsicle")

    if missing:
        print(f"Error: Missing required tools: {', '.join(missing)}", file=sys.stderr)
        print(
            "Install with: apt-get install gifsicle jpegoptim pngquant",
            file=sys.stderr,
        )
        return False
    return True


def resize_image(img: Image.Image) -> None:
    """Resize image in-place if either dimension exceeds MAX_DIMENSION."""
    img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.LANCZOS)


def optimize_png(path: Path) -> None:
    """Run pngquant on a PNG file."""
    subprocess.run(
        ["pngquant", "--force", "--ext", ".png", str(path)],
        check=True,
        capture_output=True,
    )


def optimize_jpeg(path: Path) -> None:
    """Run jpegoptim on a JPEG file."""
    subprocess.run(
        ["jpegoptim", "--strip-all", str(path)],
        check=True,
        capture_output=True,
    )


def process_gif(src_path: Path, dest_path: Path) -> None:
    """Process a GIF: resize and optimize with gifsicle."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "gifsicle",
            "--resize-fit",
            f"{MAX_DIMENSION}x{MAX_DIMENSION}",
            "-O3",
            str(src_path),
            "-o",
            str(dest_path),
        ],
        check=True,
        capture_output=True,
    )


def process_image(src_path: Path, dest_path: Path) -> None:
    """Process a single image: resize, strip metadata, save, and optimize."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(src_path) as img:
        # Convert to RGB if necessary (handles RGBA PNGs, palette images, etc.)
        if img.mode in ("RGBA", "LA") or (
            img.mode == "P" and "transparency" in img.info
        ):
            # Keep alpha for PNG
            if src_path.suffix.lower() == ".png":
                img = img.convert("RGBA")
            else:
                img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")

        resize_image(img)

        # Save without EXIF/metadata
        if src_path.suffix.lower() == ".png":
            img.save(dest_path, "PNG", optimize=True)
            optimize_png(dest_path)
        else:
            img.save(dest_path, "JPEG", quality=85, optimize=True)
            optimize_jpeg(dest_path)


def main() -> int:
    """Process all images from img-src/ to img-dist/."""
    if not check_dependencies():
        return 1

    if not SRC_DIR.exists():
        print(f"Error: Source directory {SRC_DIR} does not exist", file=sys.stderr)
        print("Create it and add images to optimize.", file=sys.stderr)
        return 1

    # Find all supported images
    images = [
        p
        for p in SRC_DIR.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    ]

    if not images:
        print(f"No images found in {SRC_DIR}")
        return 0

    # Ensure dist directory exists
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    processed = 0
    for src_path in images:
        rel_path = src_path.relative_to(SRC_DIR)
        # Normalize extension: .jpeg -> .jpg
        suffix = rel_path.suffix.lower()
        if suffix == ".jpeg":
            suffix = ".jpg"
        # Normalize filename to lowercase snake_case
        normalized_stem = normalize_filename(rel_path.stem)
        rel_path = rel_path.with_stem(normalized_stem).with_suffix(suffix)
        dest_path = DIST_DIR / rel_path

        print(f"Processing: {rel_path}")
        try:
            if src_path.suffix.lower() == ".gif":
                process_gif(src_path, dest_path)
            else:
                process_image(src_path, dest_path)
            processed += 1
        except Exception as e:  # noqa: BLE001 - report and continue the batch
            print(f"  Error: {e}", file=sys.stderr)

    print(f"\nProcessed {processed} image(s) to {DIST_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
