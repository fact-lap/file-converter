import subprocess
import tempfile
import os
import shutil
import json

SUPPORTED_INPUTS = ["mp3", "wav", "flac", "aac", "ogg", "m4a", "opus", "wma"]

CONVERTIBLE_TO = ["mp3", "wav", "flac", "aac", "ogg", "m4a", "opus"]

FFMPEG_CODEC = {
    "mp3":  ["-codec:a", "libmp3lame", "-q:a", "2"],
    "wav":  ["-codec:a", "pcm_s16le"],
    "flac": ["-codec:a", "flac"],
    "aac":  ["-codec:a", "aac", "-b:a", "192k"],
    "ogg":  ["-codec:a", "libvorbis", "-q:a", "4"],
    "m4a":  ["-codec:a", "aac", "-b:a", "192k"],
    "opus": ["-codec:a", "libopus", "-b:a", "128k"],
}


def convert(file_bytes: bytes, input_ext: str, output_ext: str) -> bytes:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg 未安裝")

    with tempfile.TemporaryDirectory() as tmpdir:
        in_path = os.path.join(tmpdir, f"input.{input_ext}")
        out_path = os.path.join(tmpdir, f"output.{output_ext}")

        with open(in_path, "wb") as f:
            f.write(file_bytes)

        codec_args = FFMPEG_CODEC.get(output_ext, [])
        cmd = ["ffmpeg", "-y", "-i", in_path] + codec_args + [out_path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg 轉換失敗: {result.stderr[-500:]}")

        with open(out_path, "rb") as f:
            return f.read()


def _get_duration(in_path: str) -> float | None:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", in_path],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
        for stream in data.get("streams", []):
            if "duration" in stream:
                return float(stream["duration"])
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def compress(file_bytes: bytes, input_ext: str, target_ratio: float) -> tuple[bytes, int, int]:
    """
    壓縮音頻到目標大小比例。
    對 WAV/FLAC 等無損格式，自動轉為 MP3 輸出。
    Returns (compressed_bytes, original_size, compressed_size).
    """
    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg 未安裝")

    original_size = len(file_bytes)
    target_size = max(1, int(original_size * target_ratio))
    output_ext = input_ext if input_ext in ("mp3", "aac", "ogg", "m4a", "opus") else "mp3"

    with tempfile.TemporaryDirectory() as tmpdir:
        in_path = os.path.join(tmpdir, f"input.{input_ext}")
        out_path = os.path.join(tmpdir, f"output.{output_ext}")
        with open(in_path, "wb") as f:
            f.write(file_bytes)

        duration = _get_duration(in_path)
        if not duration or duration <= 0:
            raise RuntimeError("無法讀取音頻時長")

        # 目標碼率（bps），限制在 32k–320k 範圍
        target_bitrate = int((target_size * 8) / duration)
        target_bitrate = max(32_000, min(target_bitrate, 320_000))

        cmd = ["ffmpeg", "-y", "-i", in_path, "-b:a", str(target_bitrate), out_path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg 壓縮失敗: {result.stderr[-300:]}")

        with open(out_path, "rb") as f:
            compressed = f.read()

    return compressed, original_size, len(compressed)
