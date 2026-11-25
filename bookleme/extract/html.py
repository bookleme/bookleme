"""HTML/XHTML extraction using only the standard library.

复用 bookleme.fetch.PageParser —— 网页抓取与本地 HTML 文件必须走同一套
正文提取规则，否则同一页面从 URL 进和从文件进会得到两份不同的语料
（曾经的分叉：抓取跳过 script/style、本地文件也只跳过这两个，
后来又各自漂移）。单一真源 = fetch.PageParser。
"""

from __future__ import annotations

from pathlib import Path


def extract(path: Path) -> dict:
    from ..fetch import PageParser
    raw = path.read_bytes().decode("utf-8", errors="replace")
    parser = PageParser()
    parser.feed(raw)
    text = parser.result_text()
    # Reuse encoding-tolerant reader only for the error path; HTML is decoded above.
    return {"raw_text": text, "toc": parser.headings, "status": "ok",
            "figure_text_lost": False, "ocr_used": False, "encoding": "utf-8-replace",
            "source_id": path.name, "path": str(path)}
