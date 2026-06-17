import os
import shutil
import subprocess
import tempfile
from pathlib import Path


NOTATION_INPUTS = ["musicxml", "xml", "mxl", "mscz", "mid", "midi"]
AUDIO_TRANSCRIPTION_INPUTS = ["mp3", "wav", "flac", "aac", "ogg", "m4a", "opus", "wma"]
SUPPORTED_INPUTS = NOTATION_INPUTS + AUDIO_TRANSCRIPTION_INPUTS

CONVERSIONS = {
    "musicxml": ["pdf", "mid", "midi", "mscz"],
    "xml": ["pdf", "mid", "midi", "mscz"],
    "mxl": ["pdf", "mid", "midi", "musicxml", "mscz"],
    "mscz": ["pdf", "mid", "midi", "musicxml"],
    "mid": ["pdf", "musicxml", "mscz"],
    "midi": ["pdf", "musicxml", "mscz"],
}

for _audio_ext in AUDIO_TRANSCRIPTION_INPUTS:
    CONVERSIONS[_audio_ext] = ["mid", "midi", "musicxml", "pdf"]


def output_filename_ext(output_ext: str) -> str:
    return "mid" if output_ext == "midi" else output_ext


def is_audio_transcription(input_ext: str, output_ext: str) -> bool:
    return input_ext in AUDIO_TRANSCRIPTION_INPUTS and output_ext in CONVERSIONS[input_ext]


def _musescore_cmd() -> str:
    configured = os.environ.get("MUSESCORE_BIN")
    candidates = [configured] if configured else []
    candidates += ["musescore4", "mscore", "musescore3", "musescore", "MuseScore"]
    for candidate in candidates:
        if candidate and shutil.which(candidate):
            return candidate
    raise RuntimeError("MuseScore CLI 未安裝，無法執行樂譜轉換")


def _require_cmd(name: str, message: str) -> str:
    cmd = shutil.which(name)
    if not cmd:
        raise RuntimeError(message)
    return cmd


def _run(cmd: list[str], env: dict | None = None, timeout: int = 900) -> None:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=merged_env,
        timeout=timeout,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout)[-900:]
        raise RuntimeError(f"轉換失敗: {detail}")


def _musescore_convert(in_path: str, out_path: str) -> bytes:
    cmd = _musescore_cmd()
    _run(
        [cmd, "-o", out_path, in_path],
        env={
            "QT_QPA_PLATFORM": os.environ.get("QT_QPA_PLATFORM", "offscreen"),
            "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", "/tmp/runtime-root"),
        },
    )
    with open(out_path, "rb") as f:
        return f.read()


def _normalize_audio(in_path: str, wav_path: str) -> None:
    _require_cmd("ffmpeg", "FFmpeg 未安裝，無法準備音頻")
    _run([
        "ffmpeg",
        "-y",
        "-i",
        in_path,
        "-ar",
        "22050",
        "-ac",
        "1",
        wav_path,
    ])


def _demucs_stem(in_path: str, tmpdir: str, stem: str) -> str:
    _require_cmd("demucs", "demucs 未安裝，無法拆 stem")
    out_dir = os.path.join(tmpdir, "demucs")
    device = os.environ.get("DEMUCS_DEVICE", "cuda")
    cmd = [
        "demucs",
        "-d",
        device,
        "--two-stems",
        stem,
        "-o",
        out_dir,
        in_path,
    ]
    try:
        _run(cmd, timeout=1200)
    except RuntimeError:
        if device == "cuda":
            cmd[2] = "cpu"
            _run(cmd, timeout=1200)
        else:
            raise

    stem_dir = Path(out_dir) / "htdemucs"
    matches = list(stem_dir.glob(f"*/{stem}.wav"))
    if stem == "instrumental" and not matches:
        matches = list(stem_dir.glob("*/no_vocals.wav"))
    if not matches:
        raise RuntimeError("demucs 完成但找不到 stem 輸出")
    return str(matches[0])


def _basic_pitch(in_path: str, tmpdir: str) -> str:
    _require_cmd("basic-pitch", "basic-pitch 未安裝，無法做 audio → MIDI")
    out_dir = os.path.join(tmpdir, "basic_pitch")
    os.makedirs(out_dir, exist_ok=True)
    _run(["basic-pitch", out_dir, in_path], timeout=1200)
    matches = list(Path(out_dir).glob("*_basic_pitch.mid"))
    if not matches:
        raise RuntimeError("basic-pitch 完成但找不到 MIDI 輸出")
    return str(matches[0])


def convert(
    file_bytes: bytes,
    input_ext: str,
    output_ext: str,
    *,
    transcription_mode: str = "direct",
    stem: str = "vocals",
) -> bytes:
    input_ext = input_ext.lower().strip(".")
    output_ext = output_ext.lower().strip(".")
    if output_ext == "midi":
        internal_output_ext = "mid"
    else:
        internal_output_ext = output_ext

    if output_ext not in CONVERSIONS.get(input_ext, []):
        raise RuntimeError(f"不支援 {input_ext} → {output_ext}")

    with tempfile.TemporaryDirectory() as tmpdir:
        in_path = os.path.join(tmpdir, f"input.{input_ext}")
        with open(in_path, "wb") as f:
            f.write(file_bytes)

        if input_ext in NOTATION_INPUTS:
            out_path = os.path.join(tmpdir, f"output.{internal_output_ext}")
            return _musescore_convert(in_path, out_path)

        wav_path = os.path.join(tmpdir, "normalized.wav")
        _normalize_audio(in_path, wav_path)
        pitch_input = wav_path
        if transcription_mode == "demucs":
            pitch_input = _demucs_stem(wav_path, tmpdir, stem)

        midi_path = _basic_pitch(pitch_input, tmpdir)
        if internal_output_ext == "mid":
            with open(midi_path, "rb") as f:
                return f.read()

        out_path = os.path.join(tmpdir, f"output.{internal_output_ext}")
        return _musescore_convert(midi_path, out_path)
