import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path


SUPPORTED_INPUTS = ["mp3", "wav", "flac", "aac", "ogg", "m4a", "opus", "wma"]
STEM_MODES = {
    "vocals_instrumental": ["vocals", "instrumental"],
    "four_stems": ["vocals", "drums", "bass", "other"],
}


def _run(cmd: list[str], timeout: int = 1800) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout)[-900:]
        raise RuntimeError(f"Stem split 失敗: {detail}")


def _demucs_cmd(in_path: str, out_dir: str, mode: str) -> list[str]:
    device = os.environ.get("DEMUCS_DEVICE", "cuda")
    cmd = ["demucs", "-d", device, "-o", out_dir]
    if mode == "vocals_instrumental":
        cmd += ["--two-stems", "vocals"]
    cmd.append(in_path)
    return cmd


def split_to_zip(file_bytes: bytes, input_ext: str, base_name: str, mode: str = "vocals_instrumental") -> bytes:
    if input_ext not in SUPPORTED_INPUTS:
        raise RuntimeError(f"不支援 stem split 輸入格式: {input_ext}")
    if mode not in STEM_MODES:
        raise RuntimeError(f"不支援 stem split 模式: {mode}")
    if not shutil.which("demucs"):
        raise RuntimeError("demucs 未安裝，無法拆 stem")

    with tempfile.TemporaryDirectory() as tmpdir:
        in_path = os.path.join(tmpdir, f"input.{input_ext}")
        out_dir = os.path.join(tmpdir, "demucs")
        zip_path = os.path.join(tmpdir, f"{base_name}_stems.zip")
        with open(in_path, "wb") as f:
            f.write(file_bytes)

        cmd = _demucs_cmd(in_path, out_dir, mode)
        try:
            _run(cmd)
        except RuntimeError:
            if cmd[2] == "cuda":
                cmd[2] = "cpu"
                _run(cmd)
            else:
                raise

        stem_root = Path(out_dir) / "htdemucs"
        candidates = list(stem_root.glob("*"))
        if not candidates:
            raise RuntimeError("demucs 完成但找不到 stem 輸出")
        song_dir = candidates[0]

        expected_files = []
        if mode == "vocals_instrumental":
            expected_files = [song_dir / "vocals.wav", song_dir / "no_vocals.wav"]
        else:
            expected_files = [song_dir / f"{stem}.wav" for stem in STEM_MODES[mode]]

        found = [path for path in expected_files if path.exists()]
        if not found:
            raise RuntimeError("demucs 完成但沒有可下載 stem")

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in found:
                name = "instrumental.wav" if path.name == "no_vocals.wav" else path.name
                zf.write(path, arcname=f"{base_name}_{name}")

        with open(zip_path, "rb") as f:
            return f.read()
