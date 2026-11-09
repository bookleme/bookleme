# 贡献指南

## 红线

1. **绝不提交任何书籍原文、封面、扫描件或第三方 Prompt 原文。** `evals/cases/user_books/`、`*.pdf`、`*.epub` 已被 `.gitignore` 排除；CI 的 `copyright_gate` 会扫描全仓。
2. **绝不导入上游仓库代码。** `_reference/book-to-skill/` 只用于研究对齐。
3. **不把未验证假设写成既成事实。** PD-05 为 `UNVERIFIED`，PD-04 / PD-06~PD-12 为 `BLOCKED`；上游的 24×–51× 是其自测、2.4×–15.6× 是其模型估算，不得转写成本项目结论。heuristic 指标未接入 judge 时必须为 `null`。
4. 产物 `SKILL.md` 的 frontmatter 顶层键只能用 `{name, description, license, allowed-tools, metadata}`；不要照抄本机 `research-team-workflow/SKILL.md` 里 `version: 5.1` 的历史遗留写法。

## 提交前检查

```bash
cd /Users/bertram/Desktop/BookLeme
python3 -m unittest discover -s tests -v
python3 -m bookleme schema --state
python3 -m bookleme plugin validate bookleme/plugins/builtin/coach_dialogue.py
python3 -m bookleme plugin validate bookleme/plugins/builtin/knowledge_reference.py
python3 -m bookleme run --input evals/cases/synthetic/coach_book.md --title "人生设计练习册（合成）" --run-id local-check
```

`validation_report.json` 的 `all_passed` 必须为 `true`；任一硬门失败不得安装或发布。

## 新增体裁

在 `bookleme/plugins/user/<genre_id>.py` 写一个文件，定义 `PLUGIN = GenrePlugin(...)`；`genre_id` 用 `^[a-z0-9][a-z0-9_-]*$` 且与文件名严格同名，并同步在 `configs/router.json` 增加该体裁的 `weights` / `prior` / `default_engines`。字段清单见 `docs/PLUGIN_SPEC.md`。用户插件会覆盖同 id 的内置插件，覆盖记录见 `out/<run_id>/plugin_resolution.json`。

## 版本与状态

里程碑不跳号，每次 run 追加 `ITERATION_LOG.md`；`state.json` 写前读、幂等；`evals/baseline.json` 按 `bookleme_version + model_fingerprint + plugin_hash` 版本化。
