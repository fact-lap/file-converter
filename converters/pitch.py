import io
import os
import shutil
import subprocess
import tempfile

import numpy as np
import soundfile as sf

SUPPORTED_INPUTS = ["mp3", "wav", "flac", "aac", "ogg", "m4a", "opus", "wma"]

SEMITONE_MIN = -8
SEMITONE_MAX = 8


def clamp_semitones(semitones) -> int:
    try:
        n = int(round(float(semitones)))
    except (TypeError, ValueError):
        raise RuntimeError("semitones 必須係整數（-8 ~ +8）")
    return max(SEMITONE_MIN, min(SEMITONE_MAX, n))


def _ffmpeg_decode_to_wav(file_bytes: bytes, input_ext: str, out_wav: str) -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg 未安裝")
    with tempfile.NamedTemporaryFile(suffix=f".{input_ext}", delete=False) as tf:
        tf.write(file_bytes)
        in_path = tf.name
    try:
        cmd = ["ffmpeg", "-y", "-i", in_path, "-ac", "2", "-ar", "44100", out_wav]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg 解碼失敗: {result.stderr[-400:]}")
    finally:
        try:
            os.unlink(in_path)
        except OSError:
            pass


def _ffmpeg_encode(in_wav: str, out_path: str, output_ext: str) -> None:
    from converters import audio as audio_converter  # local import to avoid cycle

    codec_args = audio_converter.FFMPEG_CODEC.get(output_ext, [])
    cmd = ["ffmpeg", "-y", "-i", in_wav] + codec_args + [out_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg 編碼失敗: {result.stderr[-400:]}")


def _shift_with_rubberband(y: np.ndarray, sr: int, semitones: int, preserve_formants: bool) -> np.ndarray:
    try:
        import pyrubberband as pyrb
    except ImportError:
        raise RuntimeError("pyrubberband 未安裝")
    if not shutil.which("rubberband"):
        raise RuntimeError("rubberband CLI 未安裝（apt: rubberband-cli）")
    rbargs = {}
    if preserve_formants:
        rbargs["--formant"] = ""
    # pyrb.pitch_shift 用 CLI --pitch n（half-steps）
    return pyrb.pitch_shift(y, sr, n_steps=semitones, rbargs=rbargs)


def _shift_with_librosa(y: np.ndarray, sr: int, semitones: int) -> np.ndarray:
    try:
        import librosa
    except ImportError:
        raise RuntimeError("librosa 未安裝")
    # librosa 要 mono/stereo → 逐 channel 處理
    if y.ndim == 1:
        return librosa.effects.pitch_shift(y=y, sr=sr, n_steps=semitones)
    out = np.zeros_like(y)
    for ch in range(y.shape[1]):
        out[:, ch] = librosa.effects.pitch_shift(y=y[:, ch], sr=sr, n_steps=semitones)
    return out


def pitch_shift(
    file_bytes: bytes,
    input_ext: str,
    semitones: int,
    preserve_formants: bool = False,
) -> tuple[bytes, str, str]:
    """
    Shift pitch by `semitones` (clamped to -8..+8) using Rubber Band; fall back to librosa.
    Returns (output_bytes, output_ext, engine_used).
    """
    input_ext = (input_ext or "").lower().lstrip(".")
    if input_ext not in SUPPORTED_INPUTS:
        raise RuntimeError(f"不支援的音檔格式: {input_ext}")

    n = clamp_semitones(semitones)
    output_ext = input_ext if input_ext != "wma" else "mp3"

    with tempfile.TemporaryDirectory() as tmpdir:
        wav_in = os.path.join(tmpdir, "in.wav")
        wav_out = os.path.join(tmpdir, "shifted.wav")
        _ffmpeg_decode_to_wav(file_bytes, input_ext, wav_in)

        y, sr = sf.read(wav_in, always_2d=True)  # shape (frames, ch)
        y = y.astype(np.float32, copy=False)

        engine = "rubberband"
        if n == 0:
            shifted = y
            engine = "passthrough"
        else:
            try:
                shifted = _shift_with_rubberband(y, sr, n, preserve_formants)
            except RuntimeError:
                engine = "librosa"
                shifted = _shift_with_librosa(y, sr, n)

        # Clip to avoid overflow after shift; keep same dtype
        shifted = np.clip(shifted, -1.0, 1.0).astype(np.float32, copy=False)
        sf.write(wav_out, shifted, sr, subtype="PCM_16")

        out_path = os.path.join(tmpdir, f"out.{output_ext}")
        if output_ext == "wav":
            shutil.copyfile(wav_out, out_path)
        else:
            _ffmpeg_encode(wav_out, out_path, output_ext)

        with open(out_path, "rb") as f:
            return f.read(), output_ext, engine
