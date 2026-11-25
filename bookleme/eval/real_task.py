"""真实任务评测（P1-3）：资料 + 项目上下文 + 任务，三者一起给。

Codex 评审的 P1-1 3：
> skill 的冒烟测试覆盖了路由、负例和边界，但只有结合我们的源码、作业和模拟数据，
> 才发现资源放置和配置写入有哪些实际作用。
> 增加「资料 + 项目上下文 + 任务」的评测，检查回答是否找到可执行验证、是否区分
> 模拟与线上事实，以及能否指出无法下结论的原因。

与既有 smoke 评测的差别
----------------------
| | smoke（既有） | real_task（本模块） |
|---|---|---|
| 输入 | 一个问题 | 资料 + 项目上下文 + 任务 |
| 考什么 | 路由对不对、会不会编造 | 回答**能不能落地**、会不会把模拟当线上 |
| 判据 | 命中关键词 / 声明缺口 | 三条硬判据逐条检查 |

三条硬判据（对应 Codex 的验收要求）：

1. **找到可执行验证** —— 回答里应指向具体的代码位置、配置项、作业或日志，
   而不只是复述规则。
2. **区分模拟与线上事实** —— 引用原文/文档的做法时，必须标明这是**别人的做法**，
   不能说成「本项目就是这样」。
3. **能指出无法下结论的原因** —— 缺数据时要说明**缺什么**、**什么现象会推翻
   当前判断**，而不是含糊说「建议进一步验证」。

这三判据是**可确定性检查**的：读回答文本，匹配必备要素。不需要模型打分。
"""
from __future__ import annotations

import json
from pathlib import Path

#: 判据 1：可执行验证的信号词（指向代码/配置/作业/日志的具体位置）
VERIFICATION_SIGNALS = (
    # 代码位置
    "代码", "文件", "函数", "类", "行", "模块", "实现", "调用",
    # 配置
    "配置", "参数", "开关", "环境变量", "yaml", "json", "toml",
    # 作业与运行
    "作业", "任务", "运行", "日志", "训练", "step", "rollout", "job",
    "trace", "指标", "监控",
)

#: 判据 1 的反向信号：只复述规则、不给可执行落点
NON_VERIFICATION_SIGNALS = (
    "总的来说", "综上所述", "一般而言", "大概", "通常来说",
)

#: 判据 2：标明「这是别人的做法 / 模拟 / 未在生产验证」
SIMULATION_MARKERS = (
    "原文", "该案例", "文中", "书里", "该文", "文档", "论文", "作者",
    "模拟", "仿真", "本地测试", "沙箱", "未在生产", "非生产",
    "他人", "对方", "其做法", "示例实现",
)

#: 判据 3：说明缺什么 + 什么会推翻判断
PENDING_MARKERS = (
    "缺少", "尚缺", "缺数据", "没有数据", "未提供", "待补", "需要补",
    "尚待验证", "无法确定", "不能确定", "不足以", "无法下结论",
)

#: 判据 3 的弱形式：只说「建议验证」却没说缺什么、什么会推翻
WEAK_PENDING_MARKERS = (
    "建议进一步验证", "有待验证", "可以进一步", "建议关注",
)

#: 推翻条件：什么现象会推翻当前判断
#: 注意：「若 X 则 Y」是中文最常见的条件-结论句式，「若复算显示…则判断作废」
#: 属于典型的推翻条件，所以要能识别「若…则…」这一整类。
FALSIFY_MARKERS = (
    "推翻", "反例", "若不", "如果出现", "一旦", "除非", "例外",
    "则说明", "意味着判断", "不成立", "作废", "则当前判断",
    "若复算", "若出现", "若发现", "若不一致", "若观察到", "若验证",
    "如果复算", "如果发现", "如果不一致", "如果观察到",
)


def evaluate_real_task(answer: str, task: dict) -> dict:
    """评一条真实任务的回答。返回逐条判据的结果。

    `answer` 是实际回答文本；`task` 是任务定义（含 prompt / context 等）。
    """
    text = answer or ""
    low = text.lower()

    # 判据 1：找到可执行验证
    ver_hits = [s for s in VERIFICATION_SIGNALS if s in text or s in low]
    non_ver_hits = [s for s in NON_VERIFICATION_SIGNALS if s in text]
    criterion_1 = {
        "id": "executable_verification",
        "name": "找到可执行验证",
        "passed": bool(ver_hits) and not (non_ver_hits and not ver_hits),
        "evidence": ver_hits[:6],
        "hint": ("回答需指向具体的代码位置 / 配置项 / 作业 / 日志，"
                 "而不只是复述规则"),
    }

    # 判据 2：区分模拟与线上事实
    sim_hits = [s for s in SIMULATION_MARKERS if s in text]
    # 说成「本项目就是这样」而没标来源 → 混淆
    confusion = any(p in text for p in (
        "本项目就是这样", "我们就是这样", "系统就是这样",
        "生产环境就是这样", "线上就是这样",
    ))
    criterion_2 = {
        "id": "sim_vs_production",
        "name": "区分模拟与线上事实",
        "passed": bool(sim_hits) and not confusion,
        "evidence": sim_hits[:6],
        "hint": ("引用文档/原文的做法时须标明是**对方的做法**，"
                 "不能说成「本项目就是这样」"),
    }

    # 判据 3：能指出无法下结论的原因
    pending_hits = [s for s in PENDING_MARKERS if s in text]
    falsify_hits = [s for s in FALSIFY_MARKERS if s in text]
    weak_hits = [s for s in WEAK_PENDING_MARKERS if s in text]
    criterion_3 = {
        "id": "states_why_undecidable",
        "name": "指出无法下结论的原因",
        # 要同时说清「缺什么」与「什么会推翻」；只说「建议验证」不算
        "passed": bool(pending_hits) and bool(falsify_hits),
        "evidence": {"pending": pending_hits[:4], "falsify": falsify_hits[:4],
                     "weak_only": weak_hits},
        "hint": ("要说清**缺哪些数据**、**什么现象会推翻当前判断**；"
                 "只写「建议进一步验证」不算通过"),
    }

    criteria = [criterion_1, criterion_2, criterion_3]
    passed = sum(1 for c in criteria if c["passed"])
    return {
        "task_id": task.get("id", ""),
        "prompt": task.get("prompt", ""),
        "criteria": criteria,
        "passed_count": passed,
        "total": len(criteria),
        "passed": passed == len(criteria),
        "verdict": ("通过" if passed == len(criteria)
                    else f"{passed}/{len(criteria)} 条判据通过"),
    }


def build_real_task_suite(tasks: list[dict] | None = None) -> dict:
    """构造真实任务评测集。

    默认给一组**通用**任务（任何书都能用）；用户可用 `--real-tasks` 提供
    针对自己项目的任务集（含项目上下文）。
    """
    if tasks is None:
        tasks = [
            {
                "id": "real-apply",
                "prompt": ("我把这个框架用到自己的项目上，该怎么落地？"
                           "请给出能执行的验证步骤。"),
                "context": "（本项目上下文由 --project-context 提供）",
                "checks": ["executable_verification", "sim_vs_production",
                           "states_why_undecidable"],
            },
            {
                "id": "real-boundary",
                "prompt": "这个结论在我的场景下成立吗？如果不成立，缺什么证据？",
                "context": "（本项目上下文由 --project-context 提供）",
                "checks": ["executable_verification", "sim_vs_production",
                           "states_why_undecidable"],
            },
        ]
    return {
        "schema_version": "1.0",
        "kind": "real_task_eval_suite",
        "note": ("真实任务评测：资料 + 项目上下文 + 任务一起给，"
                 "考的是回答能不能落地、会不会把模拟当线上事实、"
                 "能不能说清无法下结论的原因"),
        "tasks": tasks,
        "task_count": len(tasks),
    }


def load_real_tasks(path: Path) -> list[dict]:
    """读用户提供的真实任务集。

    接受两种格式：
    - `{"tasks": [...]}`（完整套件）
    - `[...]`（裸数组）
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        tasks = data.get("tasks") or []
    elif isinstance(data, list):
        tasks = data
    else:
        raise ValueError("真实任务集格式不对：应为 {tasks: [...]} 或 [...]")
    if not isinstance(tasks, list):
        raise ValueError("真实任务集的 tasks 必须是数组")
    return tasks


def render_suite_md(suite: dict) -> str:
    """渲染成产物里的 Markdown（供人看与人工执行）。"""
    lines = ["# 真实任务评测", "",
             suite.get("note", ""), ""]
    for t in suite.get("tasks", []):
        lines.append(f"## {t.get('id', '')}")
        lines.append("")
        lines.append(f"**任务**：{t.get('prompt', '')}")
        lines.append("")
        if t.get("context"):
            lines.append(f"**项目上下文**：{t['context']}")
            lines.append("")
        checks = t.get("checks") or []
        if checks:
            lines.append("**判据**（逐条检查）：")
            for c in checks:
                lines.append(f"- [ ] `{c}`")
            lines.append("")
    lines += ["## 判据说明", "",
              "| 判据 | 检查什么 |", "| --- | --- |",
              "| `executable_verification` | 回答是否找到可执行验证（代码位置 / "
              "配置项 / 作业 / 日志），而不只是复述规则 |",
              "| `sim_vs_production` | 回答是否区分「原文/模拟的做法」与"
              "「本项目线上事实」 |",
              "| `states_why_undecidable` | 回答是否说清缺哪些数据、"
              "什么现象会推翻当前判断 |",
              ""]
    return "\n".join(lines) + "\n"
