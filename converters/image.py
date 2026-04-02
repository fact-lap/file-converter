import io
from PIL import Image

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIC_SUPPORTED = True
except ImportError:
    HEIC_SUPPORTED = False

SUPPORTED_INPUTS = ["jpg", "jpeg", "png", "webp", "bmp", "tiff", "tif", "gif"]
if HEIC_SUPPORTED:
    SUPPORTED_INPUTS += ["heic", "heif"]

OUTPUT_FORMATS = {
    "jpg": "JPEG",
    "jpeg": "JPEG",
    "png": "PNG",
    "webp": "WEBP",
    "bmp": "BMP",
    "tiff": "TIFF",
    "gif": "GIF",
}

CONVERTIBLE_TO = ["jpg", "png", "webp", "bmp", "tiff"]


def _open(file_bytes: bytes) -> Image.Image:
    return Image.open(io.BytesIO(file_bytes))


def _save(img: Image.Image, fmt: str, quality: int = 85) -> bytes:
    pil_format = OUTPUT_FORMATS[fmt]
    if pil_format == "JPEG" and img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    out = io.BytesIO()
    kwargs = {}
    if pil_format in ("JPEG", "WEBP"):
        kwargs["quality"] = quality
    elif pil_format == "PNG":
        # PNG compression level 0-9; map quality 1-100 → level 9-0
        kwargs["compress_level"] = max(0, min(9, 9 - int(quality / 12)))
    img.save(out, format=pil_format, **kwargs)
    return out.getvalue()


def convert(file_bytes: bytes, input_ext: str, output_ext: str, quality: int = 85) -> bytes:
    img = _open(file_bytes)
    return _save(img, output_ext, quality)


def compress(file_bytes: bytes, input_ext: str, target_ratio: float) -> tuple[bytes, int, int]:
    """
    Compress image to target_ratio of original size (e.g. 0.3 = 30% of original).
    Returns (compressed_bytes, original_size, compressed_size).
    Uses binary search to find the right quality.
    """
    img = _open(file_bytes)
    original_size = len(file_bytes)
    target_size = int(original_size * target_ratio)

    # For lossless formats, convert to JPEG for compression
    out_ext = input_ext if input_ext in ("jpg", "jpeg", "webp") else "jpg"

    lo, hi = 1, 95
    best = _save(img, out_ext, hi)

    for _ in range(10):  # binary search, max 10 iterations
        mid = (lo + hi) // 2
        candidate = _save(img, out_ext, mid)
        if len(candidate) <= target_size:
            best = candidate
            lo = mid + 1
        else:
            hi = mid - 1
        if lo > hi:
            break

    return best, original_size, len(best)


def crop(file_bytes: bytes, input_ext: str, output_ext: str,
         x: int, y: int, width: int, height: int) -> bytes:
    img = _open(file_bytes)
    img_w, img_h = img.size
    right = min(x + width, img_w)
    bottom = min(y + height, img_h)
    img = img.crop((x, y, right, bottom))
    return _save(img, output_ext)


def crop_to_ratio(file_bytes: bytes, input_ext: str, output_ext: str,
                  ratio_w: int, ratio_h: int) -> bytes:
    """Center-crop to a given aspect ratio."""
    img = _open(file_bytes)
    img_w, img_h = img.size
    target_ratio = ratio_w / ratio_h

    if img_w / img_h > target_ratio:
        new_w = int(img_h * target_ratio)
        new_h = img_h
    else:
        new_w = img_w
        new_h = int(img_w / target_ratio)

    x = (img_w - new_w) // 2
    y = (img_h - new_h) // 2
    img = img.crop((x, y, x + new_w, y + new_h))
    return _save(img, output_ext)
