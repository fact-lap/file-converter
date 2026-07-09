import os
import re
import json
import datetime
import urllib.parse
import urllib.request
from flask import Flask, request, jsonify, send_file, render_template, Response
from werkzeug.utils import secure_filename
import io

from converters import image as img_converter
from converters import document as doc_converter
from converters import audio as audio_converter
from converters import notation as notation_converter
from converters import stems as stem_converter
from converters import pitch as pitch_converter

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
    "mid": "audio/midi",
    "midi": "audio/midi",
    "musicxml": "application/vnd.recordare.musicxml+xml",
    "xml": "application/xml",
    "mxl": "application/vnd.recordare.musicxml",
    "mscz": "application/vnd.musescore",
    "zip": "application/zip",
}


def get_supported_formats():
    result = {}
    for ext in img_converter.SUPPORTED_INPUTS:
        targets = [f for f in img_converter.CONVERTIBLE_TO if f != ext and f != "jpeg"]
        result[ext] = targets
    for ext, targets in doc_converter.CONVERSIONS.items():
        result[ext] = targets
    for ext in audio_converter.SUPPORTED_INPUTS:
        targets = [f for f in audio_converter.CONVERTIBLE_TO if f != ext]
        targets += [f for f in notation_converter.CONVERSIONS.get(ext, []) if f not in targets]
        result[ext] = targets
    for ext in notation_converter.NOTATION_INPUTS:
        result[ext] = notation_converter.CONVERSIONS.get(ext, [])
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
    transcription_mode = request.form.get("transcription_mode", "direct").lower()
    stem = request.form.get("stem", "vocals").lower()
    melody_mode = request.form.get("melody_mode", "false").lower() == "true"
    quantize = request.form.get("quantize", "none").lower()

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
        elif notation_converter.is_audio_transcription(input_ext, output_format):
            result = notation_converter.convert(
                file_bytes,
                input_ext,
                output_format,
                transcription_mode=transcription_mode,
                stem=stem,
                melody_mode=melody_mode,
                quantize=quantize,
            )
        elif input_ext in audio_converter.SUPPORTED_INPUTS:
            if output_format not in audio_converter.CONVERTIBLE_TO:
                return jsonify({"error": f"不支援音檔輸出格式 {output_format}"}), 400
            result = audio_converter.convert(file_bytes, input_ext, output_format)
        elif input_ext in notation_converter.NOTATION_INPUTS:
            allowed = notation_converter.CONVERSIONS.get(input_ext, [])
            if output_format not in allowed:
                return jsonify({"error": f"不支援 {input_ext} → {output_format}"}), 400
            result = notation_converter.convert(file_bytes, input_ext, output_format)
        elif input_ext in doc_converter.SUPPORTED_INPUTS:
            allowed = doc_converter.CONVERSIONS.get(input_ext, [])
            if output_format not in allowed:
                return jsonify({"error": f"不支援 {input_ext} → {output_format}"}), 400
            result = doc_converter.convert(file_bytes, input_ext, output_format)
        else:
            return jsonify({"error": f"不支援的輸入格式: {input_ext}"}), 400
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    return _send(
        result,
        notation_converter.output_filename_ext(output_format),
        base_name,
    )


@app.route("/stem-split", methods=["POST"])
def stem_split():
    if "file" not in request.files:
        return jsonify({"error": "沒有上傳檔案"}), 400
    file = request.files["file"]
    mode = request.form.get("stem_mode", "vocals_instrumental").lower()

    if not file.filename:
        return jsonify({"error": "缺少檔案"}), 400

    filename = secure_filename(file.filename)
    input_ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    base_name = filename.rsplit(".", 1)[0] if "." in filename else filename

    try:
        result = stem_converter.split_to_zip(file.read(), input_ext, base_name, mode)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    return _send(result, "zip", f"{base_name}_stems")


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


@app.route("/compress-audio", methods=["POST"])
def compress_audio():
    if "file" not in request.files:
        return jsonify({"error": "沒有上傳檔案"}), 400
    file = request.files["file"]
    target_pct = int(request.form.get("target_pct", 50))

    filename = secure_filename(file.filename)
    input_ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    base_name = filename.rsplit(".", 1)[0] if "." in filename else filename

    if input_ext not in audio_converter.SUPPORTED_INPUTS:
        return jsonify({"error": "不支援的音頻格式"}), 400

    file_bytes = file.read()
    target_ratio = max(0.05, min(0.95, target_pct / 100))

    try:
        result, orig_size, compressed_size = audio_converter.compress(
            file_bytes, input_ext, target_ratio
        )
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    out_ext = input_ext if input_ext in ("mp3", "aac", "ogg", "m4a", "opus") else "mp3"
    return _send(result, out_ext, f"{base_name}_compressed", {
        "X-Original-Size": str(orig_size),
        "X-Compressed-Size": str(compressed_size),
        "Access-Control-Expose-Headers": "X-Original-Size, X-Compressed-Size",
    })


@app.route("/pitch-shift", methods=["POST"])
def pitch_shift():
    """
    移調 endpoint：±8 semitones，Rubber Band 為主、librosa fallback。
    Params (multipart form):
      file            (required) 音檔
      semitones       (required) int/float，會 clamp 到 -8..+8
      preserve_formants (optional bool) "true"/"1" 開 formant preservation
    """
    if "file" not in request.files:
        return jsonify({"error": "沒有上傳檔案"}), 400
    file = request.files["file"]
    raw_semi = request.form.get("semitones", "").strip()
    preserve_formants = request.form.get("preserve_formants", "false").strip().lower() in ("1", "true", "yes", "on")

    if not file.filename:
        return jsonify({"error": "缺少檔案"}), 400
    if raw_semi == "":
        return jsonify({"error": "缺少 semitones 參數"}), 400

    filename = secure_filename(file.filename)
    input_ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    base_name = filename.rsplit(".", 1)[0] if "." in filename else filename

    if input_ext not in pitch_converter.SUPPORTED_INPUTS:
        return jsonify({"error": f"不支援的音檔格式: {input_ext}"}), 400

    try:
        n = pitch_converter.clamp_semitones(raw_semi)
        result, out_ext, engine = pitch_converter.pitch_shift(
            file.read(), input_ext, n, preserve_formants=preserve_formants
        )
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    sign = "+" if n >= 0 else ""
    out_name = f"{base_name}_pitch{sign}{n}st"
    return _send(result, out_ext, out_name, {
        "X-Pitch-Semitones": str(n),
        "X-Pitch-Engine": engine,
        "X-Pitch-Formants": "1" if preserve_formants else "0",
        "Access-Control-Expose-Headers": "X-Pitch-Semitones, X-Pitch-Engine, X-Pitch-Formants",
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


# ─────────────────────────────────────────────────────────────────────────────
# YouTube lane — UI front door for the Mac/HF Space/Drive pipeline.
#
# Architecture:
#   This Flask app runs on HF Space.  It MUST NOT download from YouTube
#   (HF datacenter IPs are bot-walled).  Instead, on UI submit it creates a
#   Notion task; the Mac residential-IP poller (poll-youtube.mjs) picks it up,
#   runs ystem.sh, and writes status/stems back to the same task page.
#   This endpoint is the UI ⇄ Notion bridge for: create + poll status + list stems.
# ─────────────────────────────────────────────────────────────────────────────

NOTION_INTAKE_TOKEN = os.environ.get("NOTION_INTAKE_TOKEN", "")
INTAKE_TASKS_DB_ID = os.environ.get("INTAKE_TASKS_DB_ID", "")
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

YT_URL_RE = re.compile(
    r"^https?://(?:(?:www|m)\.)?(?:youtube\.com/(?:watch\?[^\s]*v=[\w-]+|shorts/[\w-]+|live/[\w-]+)|youtu\.be/[\w-]+)\S*$"
)
STATUS_LINE_RE = re.compile(r"^📊\s*status:\s*([a-z_]+)(?:\s*\|\s*(.+))?(?:\s*@\s*\S+)?", re.IGNORECASE)
STEM_LINE_RE = re.compile(r"^🎵\s*(\S+(?:\s*\S+)*?)(?:\s*\|\s*in:\s*(.+))?$")
DEST_LINE_RE = re.compile(r"^🎧\s*stems\s*→\s*(.+)$")


def _notion(method, path, body=None):
    if not NOTION_INTAKE_TOKEN:
        raise RuntimeError("NOTION_INTAKE_TOKEN not set on HF Space")
    req = urllib.request.Request(
        NOTION_API + path,
        method=method,
        headers={
            "Authorization": f"Bearer {NOTION_INTAKE_TOKEN}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json"
        }
    )
    data = json.dumps(body).encode("utf-8") if body is not None else None
    with urllib.request.urlopen(req, data=data, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_youtube_title(url: str) -> str:
    """oEmbed gives the video title without hitting the bot-walled download path."""
    try:
        oembed = "https://www.youtube.com/oembed?" + urllib.parse.urlencode({"url": url, "format": "json"})
        with urllib.request.urlopen(oembed, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        title = (data.get("title") or "").strip()
        return title or url
    except Exception:
        return url


def _block_text(block: dict) -> str:
    if block.get("type") != "paragraph":
        return ""
    return "".join(t.get("plain_text", "") for t in block.get("paragraph", {}).get("rich_text", []))


@app.route("/youtube-intake", methods=["POST"])
def youtube_intake():
    if not NOTION_INTAKE_TOKEN or not INTAKE_TASKS_DB_ID:
        return jsonify({
            "error": "Server not configured: NOTION_INTAKE_TOKEN / INTAKE_TASKS_DB_ID missing on HF Space"
        }), 500

    payload = request.get_json(silent=True) or request.form
    url = (payload.get("url") or "").strip()
    mode = (payload.get("mode") or "two").strip().lower()
    if mode not in ("two", "four"):
        mode = "two"
    if not YT_URL_RE.match(url):
        return jsonify({"error": "請貼 YouTube URL（youtube.com / youtu.be / shorts / live）"}), 400

    title = _fetch_youtube_title(url)
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    page_body = {
        "parent": {"database_id": INTAKE_TASKS_DB_ID},
        "properties": {
            "煩瑣": {"title": [{"text": {"content": title[:200]}}]},
            "狀態": {"status": {"name": "⏭️ 下一步要做"}}
        },
        "children": [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"🎬 YT｜{url}｜mode:{mode}"}}]}
            },
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"📊 status: queued @ {ts}"}}]}
            }
        ]
    }

    try:
        page = _notion("POST", "/pages", page_body)
    except urllib.error.HTTPError as e:
        return jsonify({"error": f"Notion {e.code}: {e.read().decode('utf-8')[:300]}"}), 502
    except Exception as e:
        return jsonify({"error": f"Notion intake failed: {e}"}), 502

    return jsonify({
        "task_id": page["id"],
        "task_url": page.get("url"),
        "video_title": title,
        "mode": mode
    })


@app.route("/job-status", methods=["GET"])
def job_status():
    """UI polls this — returns latest 📊 status line + (when done) stems list."""
    if not NOTION_INTAKE_TOKEN:
        return jsonify({"error": "Server not configured"}), 500
    task_id = (request.args.get("task") or "").strip()
    if not task_id:
        return jsonify({"error": "missing task"}), 400

    try:
        page = _notion("GET", f"/pages/{task_id}")
        blocks = _notion("GET", f"/blocks/{task_id}/children?page_size=100")
    except urllib.error.HTTPError as e:
        return jsonify({"error": f"Notion {e.code}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 502

    last_state = "queued"
    last_status_text = ""
    stems = []
    drive_dest = ""
    for block in blocks.get("results", []):
        text = _block_text(block).strip()
        if not text:
            continue
        m = STATUS_LINE_RE.match(text)
        if m:
            last_state = m.group(1).lower()
            last_status_text = text
            continue
        m = STEM_LINE_RE.match(text)
        if m:
            stems.append({"name": m.group(1).strip(), "location": (m.group(2) or "").strip()})
            continue
        m = DEST_LINE_RE.match(text)
        if m:
            drive_dest = m.group(1).strip()

    # Tasks DB title property
    title_prop = page.get("properties", {}).get("煩瑣") or page.get("properties", {}).get("Name") or {}
    video_title = "".join(t.get("plain_text", "") for t in title_prop.get("title", []))

    done_flag = page.get("properties", {}).get("搞掂", {}).get("checkbox", False)
    if done_flag and last_state != "done":
        last_state = "done"

    return jsonify({
        "task_id": task_id,
        "task_url": page.get("url"),
        "video_title": video_title,
        "state": last_state,
        "status_text": last_status_text,
        "stems": stems,
        "drive_dest": drive_dest,
        "done": done_flag
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    app.run(host="0.0.0.0", port=port)
