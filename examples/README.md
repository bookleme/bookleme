# 样例产物

两个目录都由 `evals/cases/synthetic/coach_book.md`（项目自撰合成文本，零版权风险）经 BookLeme 端到端生成，未包含任何真实出版物内容。

- `coach/` — `behavior_skill` 引擎 / `coach_dialogue` 插件：带状态机、一问一答硬约束、具名输出契约、情绪护栏、跨轮状态文件与冒烟用例。
- `reference/` — `knowledge_pack` 引擎 / `knowledge_reference` 插件：Topic Index 路由表、按需加载的框架分片、决策速查与出处清单。

两者的 `SKILL.md` 都通过 `/Users/bertram/Desktop/skills/.system/skill-creator/scripts/quick_validate.py`（返回 `Skill is valid!`）以及本项目 `validate/lint.py` 的五段式/13 项自检。

`professional_analysis` 与 `decision_checklist` 两个体裁的样例将在 M4 补齐。

复核命令：

```bash
python3 -m bookleme validate examples/coach
python3 -m bookleme validate examples/reference
```
