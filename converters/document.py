import subprocess
import tempfile
import os
import shutil

SUPPORTED_INPUTS = ["pdf", "docx", "md", "html", "txt"]

# 來源 → 可轉換的目標格式
CONVERSIONS = {
    "md":   ["html", "pdf", "docx", "txt"],
    "html": ["md", "pdf", "docx", "txt"],
    "docx": ["html", "md", "pdf", "txt"],
    "pdf":  ["txt"],
    "txt":  ["html", "md"],
}

PANDOC_FORMAT_MAP = {
    "md":   "markdown",
    "html": "html",
    "docx": "docx",
    "txt":  "plain",
    "pdf":  "pdf",
}


def _pandoc_available():
    return shutil.which("pandoc") is not None


def _libreoffice_available():
    for cmd in ["libreoffice", "soffice"]:
        if shutil.which(cmd):
            return cmd
    return None


def convert(file_bytes: bytes, input_ext: str, output_ext: str) -> bytes:
    with tempfile.TemporaryDirectory() as tmpdir:
        in_path = os.path.join(tmpdir, f"input.{input_ext}")
        out_path = os.path.join(tmpdir, f"output.{output_ext}")

        with open(in_path, "wb") as f:
            f.write(file_bytes)

        # PDF → TXT：用 pypdf
        if input_ext == "pdf" and output_ext == "txt":
            return _pdf_to_txt(file_bytes)

        # DOCX → PDF：優先 LibreOffice，fallback Pandoc
        if input_ext == "docx" and output_ext == "pdf":
            lo_cmd = _libreoffice_available()
            if lo_cmd:
                return _libreoffice_docx_to_pdf(lo_cmd, in_path, tmpdir)
            # fallback: pandoc（需要 pdflatex，可能失敗）

        # 其他：Pandoc
        if not _pandoc_available():
            raise RuntimeError("Pandoc 未安裝，無法執行文件轉換")

        pandoc_in = PANDOC_FORMAT_MAP.get(input_ext)
        pandoc_out = PANDOC_FORMAT_MAP.get(output_ext)

        cmd = ["pandoc", in_path, "-f", pandoc_in, "-t", pandoc_out, "-o", out_path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Pandoc 轉換失敗: {result.stderr}")

        with open(out_path, "rb") as f:
            return f.read()


def _pdf_to_txt(file_bytes: bytes) -> bytes:
    try:
        import pypdf
        import io
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        return text.encode("utf-8")
    except ImportError:
        raise RuntimeError("pypdf 未安裝，無法提取 PDF 文字")


def _libreoffice_docx_to_pdf(lo_cmd: str, in_path: str, tmpdir: str) -> bytes:
    result = subprocess.run(
        [lo_cmd, "--headless", "--convert-to", "pdf", "--outdir", tmpdir, in_path],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"LibreOffice 轉換失敗: {result.stderr}")

    base = os.path.splitext(os.path.basename(in_path))[0]
    out_path = os.path.join(tmpdir, f"{base}.pdf")
    with open(out_path, "rb") as f:
        return f.read()
