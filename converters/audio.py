import subprocess
import tempfile
import os
import shutil

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
