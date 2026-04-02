import os
import mimetypes
from flask import Flask, request, jsonify, send_file, render_template
from werkzeug.utils import secure_filename
import io
import tempfile

from converters import image as img_converter
from converters import document as doc_converter

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50MB

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
}


def get_supported_formats():
    result = {}

    # 圖片格式
    for ext in img_converter.SUPPORTED_INPUTS:
        result[ext] = img_converter.CONVERTIBLE_TO
        # 不要列出轉換到自身
        result[ext] = [f for f in result[ext] if f != ext and f != "jpeg"]

    # 文件格式
    for ext, targets in doc_converter.CONVERSIONS.items():
        result[ext] = targets

    return result


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

    if not file.filename:
        return jsonify({"error": "檔名為空"}), 400
    if not output_format:
        return jsonify({"error": "未指定輸出格式"}), 400

    filename = secure_filename(file.filename)
    input_ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    file_bytes = file.read()

    try:
        if input_ext in img_converter.SUPPORTED_INPUTS:
            if output_format not in img_converter.OUTPUT_FORMATS:
                return jsonify({"error": f"圖片不支援輸出格式 {output_format}"}), 400
            result_bytes = img_converter.convert(file_bytes, input_ext, output_format)
        elif input_ext in doc_converter.SUPPORTED_INPUTS:
            allowed = doc_converter.CONVERSIONS.get(input_ext, [])
            if output_format not in allowed:
                return jsonify({"error": f"不支援 {input_ext} → {output_format}"}), 400
            result_bytes = doc_converter.convert(file_bytes, input_ext, output_format)
        else:
            return jsonify({"error": f"不支援的輸入格式: {input_ext}"}), 400
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    base_name = filename.rsplit(".", 1)[0] if "." in filename else filename
    out_filename = f"{base_name}.{output_format}"
    mime = MIME_TYPES.get(output_format, "application/octet-stream")

    return send_file(
        io.BytesIO(result_bytes),
        mimetype=mime,
        as_attachment=True,
        download_name=out_filename,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    app.run(host="0.0.0.0", port=port)
