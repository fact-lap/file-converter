import os
import shutil
import subprocess
import tempfile
from pathlib import Path


NOTATION_INPUTS = ["musicxml", "xml", "mxl", "mscz", "mid", "midi"]
AUDIO_TRANSCRIPTION_INPUTS = ["mp3", "wav", "flac", "aac", "ogg", "m4a", "opus", "wma"]
RENDER_AUDIO_OUTPUTS = ["wav", "mp3", "flac", "ogg"]
SUPPORTED_INPUTS = NOTATION_INPUTS + AUDIO_TRANSCRIPTION_INPUTS

CONVERSIONS = {
    "musicxml": ["pdf", "mid", "midi", "mscz"] + RENDER_AUDIO_OUTPUTS,
    "xml": ["pdf", "mid", "midi", "mscz"] + RENDER_AUDIO_OUTPUTS,
    "mxl": ["pdf", "mid", "midi", "musicxml", "mscz"] + RENDER_AUDIO_OUTPUTS,
    "mscz": ["pdf", "mid", "midi", "musicxml"] + RENDER_AUDIO_OUTPUTS,
    "mid": ["pdf", "musicxml", "mscz"] + RENDER_AUDIO_OUTPUTS,
    "midi": ["pdf", "musicxml", "mscz"] + RENDER_AUDIO_OUTPUTS,
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


def _ffmpeg_convert(in_path: str, out_path: str, output_ext: str) -> bytes:
    _require_cmd("ffmpeg", "FFmpeg 未安裝，無法輸出音頻")
    codec_args = {
        "mp3": ["-codec:a", "libmp3lame", "-q:a", "2"],
        "wav": ["-codec:a", "pcm_s16le"],
        "flac": ["-codec:a", "flac"],
        "ogg": ["-codec:a", "libvorbis", "-q:a", "4"],
    }.get(output_ext, [])
    _run(["ffmpeg", "-y", "-i", in_path] + codec_args + [out_path])
    with open(out_path, "rb") as f:
        return f.read()


def _render_to_audio(in_path: str, out_path: str, output_ext: str, tmpdir: str) -> bytes:
    wav_path = out_path if output_ext == "wav" else os.path.join(tmpdir, "render.wav")
    _musescore_convert(in_path, wav_path)
    if output_ext == "wav":
        with open(wav_path, "rb") as f:
            return f.read()
    return _ffmpeg_convert(wav_path, out_path, output_ext)


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
    split_stem = "vocals" if stem == "instrumental" else stem
    cmd = [
        "demucs",
        "-d",
        device,
        "--two-stems",
        split_stem,
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


def _quantize_time(value: float, grid: float) -> float:
    return max(0.0, round(value / grid) * grid)


def _cleanup_melody_midi(in_path: str, out_path: str, quantize: str) -> None:
    import pretty_midi

    pm = pretty_midi.PrettyMIDI(in_path)
    notes = []
    for instrument in pm.instruments:
        if instrument.is_drum:
            continue
        notes.extend(instrument.notes)

    notes = [n for n in notes if n.end - n.start >= 0.06 and 35 <= n.pitch <= 96]
    notes.sort(key=lambda n: (n.start, -n.velocity, -n.pitch))

    grid = {"eighth": 0.5, "sixteenth": 0.25}.get(quantize)
    cleaned = []
    last = None
    for note in notes:
        start = _quantize_time(note.start, grid) if grid else note.start
        end = _quantize_time(note.end, grid) if grid else note.end
        if end <= start:
            end = start + (grid or 0.08)

        if last and start < last.end:
            if note.velocity <= last.velocity:
                continue
            last.end = max(last.start + 0.04, start)

        if last and note.pitch == last.pitch and start - last.end <= 0.08:
            last.end = max(last.end, end)
            last.velocity = max(last.velocity, note.velocity)
            continue

        new_note = pretty_midi.Note(
            velocity=max(40, min(110, note.velocity)),
            pitch=note.pitch,
            start=start,
            end=end,
        )
        cleaned.append(new_note)
        last = new_note

    try:
        tempo = pm.estimate_tempo()
    except ValueError:
        tempo = 120
    out_pm = pretty_midi.PrettyMIDI(initial_tempo=tempo or 120)
    melody = pretty_midi.Instrument(program=pretty_midi.instrument_name_to_program("Acoustic Grand Piano"))
    melody.notes = cleaned
    out_pm.instruments.append(melody)
    out_pm.write(out_path)


def convert(
    file_bytes: bytes,
    input_ext: str,
    output_ext: str,
    *,
    transcription_mode: str = "direct",
    stem: str = "vocals",
    melody_mode: bool = False,
    quantize: str = "none",
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
            if internal_output_ext in RENDER_AUDIO_OUTPUTS:
                return _render_to_audio(in_path, out_path, internal_output_ext, tmpdir)
            return _musescore_convert(in_path, out_path)

        wav_path = os.path.join(tmpdir, "normalized.wav")
        _normalize_audio(in_path, wav_path)
        pitch_input = wav_path
        if transcription_mode == "demucs":
            pitch_input = _demucs_stem(wav_path, tmpdir, stem)

        midi_path = _basic_pitch(pitch_input, tmpdir)
        if melody_mode:
            clean_path = os.path.join(tmpdir, "melody_clean.mid")
            _cleanup_melody_midi(midi_path, clean_path, quantize)
            midi_path = clean_path

        if internal_output_ext == "mid":
            with open(midi_path, "rb") as f:
                return f.read()

        out_path = os.path.join(tmpdir, f"output.{internal_output_ext}")
        return _musescore_convert(midi_path, out_path)
