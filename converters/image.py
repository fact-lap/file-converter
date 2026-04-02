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


def convert(file_bytes: bytes, input_ext: str, output_ext: str) -> bytes:
    img = Image.open(io.BytesIO(file_bytes))

    # RGBA 轉 JPEG 時需要先轉 RGB
    pil_format = OUTPUT_FORMATS[output_ext]
    if pil_format == "JPEG" and img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")

    out = io.BytesIO()
    save_kwargs = {}
    if pil_format == "JPEG":
        save_kwargs["quality"] = 90
    elif pil_format == "WEBP":
        save_kwargs["quality"] = 90

    img.save(out, format=pil_format, **save_kwargs)
    return out.getvalue()
