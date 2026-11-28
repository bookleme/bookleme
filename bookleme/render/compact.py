"""紧凑打包：把技能包压成应用商店友好的文件数。

典型约束：SkillPay 单包最多 20 个文件。行为类产物常有 14-27 张
references/framework-*.md，直接上传会超限。这里把它们合并为一份
references/frameworks.md，并重写 topic-index 的引用路径；同时移除
evals/ 与 coverage 说明，仅保留运行需要的文件。
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

_FRAMEWORK_RE = re.compile(r"references/framework-\d+\.md")


def _rewrite_refs(skill_dir: Path) -> int:
    count = 0
    for md in skill_dir.rglob("*.md"):
        text = md.read_text(encoding="utf-8")
        new = _FRAMEWORK_RE.sub("references/frameworks.md", text)
        if new != text:
            md.write_text(new, encoding="utf-8")
            count += 1
    return count


def compact_skill_dir(source: Path, output: Path) -> dict:
    """把 source 技能包压缩到 output；返回统计信息。

    已存在 output 时抛 FileExistsError，避免静默覆盖。
    """
    src = Path(source).resolve()
    dst = Path(output).expanduser().resolve()
    if not (src / "SKILL.md").is_file():
        raise ValueError(f"不是技能目录（缺 SKILL.md）：{src}")
    if dst.exists():
        raise FileExistsError(f"输出目录已存在：{dst}")
    dst.mkdir(parents=True)

    copied: list[str] = []
    skipped: list[str] = []
    for p in sorted(src.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(src)
        parts = rel.parts
        if parts[0] == "evals":
            skipped.append(str(rel))
            continue
        if rel == Path("references/coverage.md"):
            skipped.append(str(rel))
            continue
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, out)
        copied.append(str(rel))

    frames = sorted((dst / "references").glob("framework-*.md")) \
        if (dst / "references").is_dir() else []
    merged = 0
    if frames:
        body = "\n\n".join(f.read_text(encoding="utf-8") for f in frames)
        (dst / "references" / "frameworks.md").write_text(body, encoding="utf-8")
        for f in frames:
            f.unlink()
        merged = len(frames)
    rewritten = _rewrite_refs(dst)
    files = [p for p in dst.rglob("*") if p.is_file()]
    return {
        "source": str(src), "output": str(dst),
        "copied": len(copied), "skipped": len(skipped),
        "merged_frameworks": merged, "refs_rewritten": rewritten,
        "files_total": len(files),
    }
