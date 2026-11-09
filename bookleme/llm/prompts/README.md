# Prompt 版本化目录（占位）

本批 M0–M2 未接入任何 LLM 调用：`capabilities/extract.py` 使用确定性抽取器，
`router/ambiguity.py` 使用确定性兜底并显式标记 `llm_judge_invoked: false`。

后续批次接入时，每个 prompt 单独成文件、带版本号，`state.json` 的
`model_fingerprint` 与 `evals/baseline.json` 绑定同一版本，防止换模型漂移。
