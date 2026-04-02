import os
from flask import Flask, request, jsonify, send_file, render_template, Response
from werkzeug.utils import secure_filename
import io

from converters import image as img_converter
from converters import document as doc_converter
from converters import audio as audio_converter

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100MB

MIME_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
    "gif": "image/gif",
    "heic": "image/heic",
    "heif": "image/heif",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "html": "text/html",
    "md": "text/markdown",
    "txt": "text/plain",
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "flac": "audio/flac",
    "aac": "audio/aac",
    "ogg": "audio/ogg",
    "m4a": "audio/mp4",
    "opus": "audio/opus",
}


def get_supported_formats():
    result = {}
    for ext in img_converter.SUPPORTED_INPUTS:
        targets = [f for f in img_converter.CONVERTIBLE_TO if f != ext and f != "jpeg"]
        result[ext] = targets
    for ext, targets in doc_converter.CONVERSIONS.items():
        result[ext] = targets
    for ext in audio_converter.SUPPORTED_INPUTS:
        result[ext] = [f for f in audio_converter.CONVERTIBLE_TO if f != ext]
    return result


def _send(data: bytes, fmt: str, base_name: str, extra_headers: dict = None):
    mime = MIME_TYPES.get(fmt, "application/octet-stream")
    resp = send_file(
        io.BytesIO(data),
        mimetype=mime,
        as_attachment=True,
        download_name=f"{base_name}.{fmt}",
    )
    if extra_headers:
        for k, v in extra_headers.items():
            resp.headers[k] = v
    return resp


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/formats")
def formats():
    return jsonify({"supported": get_supported_formats()})


@app.route("/convert", methods=["POST"])
def convert():
    if "file" not in request.files:
        return jsonify({"error": "沒有上傳檔案"}), 400
    file = request.files["file"]
    output_format = request.form.get("output_format", "").lower().strip(".")
    quality = int(request.form.get("quality", 85))

    if not file.filename or not output_format:
        return jsonify({"error": "缺少必要參數"}), 400

    filename = secure_filename(file.filename)
    input_ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    file_bytes = file.read()
    base_name = filename.rsplit(".", 1)[0] if "." in filename else filename

    try:
        if input_ext in img_converter.SUPPORTED_INPUTS:
            if output_format not in img_converter.OUTPUT_FORMATS:
                return jsonify({"error": f"不支援圖片輸出格式 {output_format}"}), 400
            result = img_converter.convert(file_bytes, input_ext, output_format, quality)
        elif input_ext in audio_converter.SUPPORTED_INPUTS:
            if output_format not in audio_converter.CONVERTIBLE_TO:
                return jsonify({"error": f"不支援音檔輸出格式 {output_format}"}), 400
            result = audio_converter.convert(file_bytes, input_ext, output_format)
        elif input_ext in doc_converter.SUPPORTED_INPUTS:
            allowed = doc_converter.CONVERSIONS.get(input_ext, [])
            if output_format not in allowed:
                return jsonify({"error": f"不支援 {input_ext} → {output_format}"}), 400
            result = doc_converter.convert(file_bytes, input_ext, output_format)
        else:
            return jsonify({"error": f"不支援的輸入格式: {input_ext}"}), 400
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    return _send(result, output_format, base_name)


@app.route("/compress", methods=["POST"])
def compress():
    if "file" not in request.files:
        return jsonify({"error": "沒有上傳檔案"}), 400
    file = request.files["file"]
    target_pct = int(request.form.get("target_pct", 50))  # 壓到原本的 x%

    filename = secure_filename(file.filename)
    input_ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    base_name = filename.rsplit(".", 1)[0] if "." in filename else filename

    if input_ext not in img_converter.SUPPORTED_INPUTS:
        return jsonify({"error": "壓縮僅支援圖片格式"}), 400

    file_bytes = file.read()
    target_ratio = max(0.05, min(0.95, target_pct / 100))

    try:
        result, orig_size, compressed_size = img_converter.compress(
            file_bytes, input_ext, target_ratio
        )
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    out_ext = input_ext if input_ext in ("jpg", "jpeg", "webp") else "jpg"
    return _send(result, out_ext, f"{base_name}_compressed", {
        "X-Original-Size": str(orig_size),
        "X-Compressed-Size": str(compressed_size),
        "Access-Control-Expose-Headers": "X-Original-Size, X-Compressed-Size",
    })


@app.route("/crop", methods=["POST"])
def crop():
    if "file" not in request.files:
        return jsonify({"error": "沒有上傳檔案"}), 400
    file = request.files["file"]
    output_format = request.form.get("output_format", "jpg").lower()

    filename = secure_filename(file.filename)
    input_ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    base_name = filename.rsplit(".", 1)[0] if "." in filename else filename

    if input_ext not in img_converter.SUPPORTED_INPUTS:
        return jsonify({"error": "Crop 僅支援圖片格式"}), 400

    file_bytes = file.read()
    mode = request.form.get("mode", "custom")  # "custom" or "ratio"

    try:
        if mode == "ratio":
            rw = int(request.form.get("ratio_w", 1))
            rh = int(request.form.get("ratio_h", 1))
            result = img_converter.crop_to_ratio(file_bytes, input_ext, output_format, rw, rh)
        else:
            x = int(request.form.get("x", 0))
            y = int(request.form.get("y", 0))
            w = int(request.form.get("width", 100))
            h = int(request.form.get("height", 100))
            result = img_converter.crop(file_bytes, input_ext, output_format, x, y, w, h)
    except (ValueError, RuntimeError) as e:
        return jsonify({"error": str(e)}), 500

    return _send(result, output_format, f"{base_name}_cropped")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    app.run(host="0.0.0.0", port=port)
