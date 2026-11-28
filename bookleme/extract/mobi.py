"""MOBI/AZW3 extraction.

Primary path uses Calibre's ebook-convert (best fidelity). When Calibre is not
installed, an optional pure-Python fallback via the ``mobi`` package is used so
batch runs are not blocked by a large GUI-tool download.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess


def _python_fallback(path: Path) -> dict:
    """Extract via the optional ``mobi`` package (MOBI7 -> HTML, MOBI8 -> EPUB)."""
    try:
        from mobi import extract as mobi_extract
    except Exception as exc:  # pragma: no cover - environment dependent
        return {"raw_text": "", "toc": [], "status": "deferred",
                "figure_text_lost": True, "ocr_used": False,
                "reason": "Calibre ebook-convert not found and optional 'mobi' package "
                          f"unavailable: {exc!r}. Install Calibre or `pip install mobi`; "
                          "or convert to EPUB/TXT and retry.",
                "source_id": path.name, "path": str(path)}

    tmp_dir, out_file = mobi_extract(str(path))
    out_path = Path(out_file)
    try:
        if out_path.suffix.lower() == ".epub":
            from . import epub as _epub
            result = _epub.extract(out_path)
        else:
            from . import html as _html
            result = _html.extract(out_path)
    finally:
        shutil.rmtree(Path(tmp_dir), ignore_errors=True)
    result["source_id"] = path.name
    result["path"] = str(path)
    result["extraction_backend"] = "mobi-python"
    return result


def extract(path: Path) -> dict:
    exe = shutil.which("ebook-convert")
    if exe:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "converted.txt"
            proc = subprocess.run([exe, str(path), str(out)], capture_output=True, text=True, timeout=180)
            if proc.returncode == 0 and out.exists():
                return {"raw_text": out.read_text(encoding="utf-8", errors="replace"),
                        "toc": [], "status": "ok", "figure_text_lost": True,
                        "ocr_used": False, "source_id": path.name, "path": str(path),
                        "extraction_backend": "calibre-ebook-convert"}
            # Fall through to the Python backend on conversion failure.
    return _python_fallback(path)
