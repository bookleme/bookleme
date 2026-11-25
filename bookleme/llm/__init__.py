"""LLM adapter: OpenAI-compatible chat completions over stdlib urllib.

零第三方依赖。**用户不需要知道 BookLeme 的专有变量名**——按以下顺序自动解析：

1. 显式环境变量 `BOOKLEME_LLM_BASE_URL` / `_API_KEY` / `_MODEL`（最高优先，留给高级用户）
2. 配置文件 `~/.bookleme/config.json` 的 `llm` 段（可写 `api_key_env` 指向别的环境变量，
   避免把密钥落盘）
3. **自动识别常见厂商的标准环境变量**（`OPENAI_API_KEY` / `MOONSHOT_API_KEY` /
   `DEEPSEEK_API_KEY` / `DASHSCOPE_API_KEY` / `ARK_API_KEY` / `ZHIPU_API_KEY` /
   `SILICONFLOW_API_KEY` / `OPENROUTER_API_KEY` / `GROQ_API_KEY` / `XAI_API_KEY`），
   端点用各厂默认的 OpenAI 兼容地址

任何一项缺失 → `available()` 为 False，调用方回退确定性路径，**流水线绝不中断**。

诚实标注约定：
  - 每次真实 HTTP 调用计一次 llm_calls（含失败的调用）；
  - model_fingerprint = sha256(model + prompt_version)，与 prompt 版本绑定，
    防止换模型/换 prompt 后指标被误当成同一实验（见 prompts/README.md）；
  - LLM 产出的引文一律回原文逐字校验（find），不得直接信任模型输出。

另外：编译期调模型**从来不是必需项**。产物是给智能体用的技能包，读图这类多模态
理解默认交给运行时的智能体做（见 render/skill.py 的「读图任务」区块），
LLM 只用于可选的「编译期预填」。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

ENV_BASE = "BOOKLEME_LLM_BASE_URL"
ENV_KEY = "BOOKLEME_LLM_API_KEY"
ENV_MODEL = "BOOKLEME_LLM_MODEL"
ENV_TIMEOUT = "BOOKLEME_LLM_TIMEOUT"
ENV_VISION_MODEL = "BOOKLEME_LLM_VISION_MODEL"  # 可选：视觉模型；缺省回退文本模型

CONFIG_PATH = Path.home() / ".bookleme" / "config.json"

#: 常见厂商的标准环境变量 → 默认 OpenAI 兼容端点。自动识别，用户零配置。
PROVIDERS: tuple[tuple[str, str, str], ...] = (
    ("OPENAI_API_KEY", "https://api.openai.com/v1", "openai"),
    ("MOONSHOT_API_KEY", "https://api.moonshot.cn/v1", "kimi"),
    ("DEEPSEEK_API_KEY", "https://api.deepseek.com/v1", "deepseek"),
    ("DASHSCOPE_API_KEY", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen"),
    ("ARK_API_KEY", "https://ark.cn-beijing.volces.com/api/v3", "doubao"),
    ("ZHIPU_API_KEY", "https://open.bigmodel.cn/api/paas/v4", "zhipu"),
    ("SILICONFLOW_API_KEY", "https://api.siliconflow.cn/v1", "siliconflow"),
    ("OPENROUTER_API_KEY", "https://openrouter.ai/api/v1", "openrouter"),
    ("GROQ_API_KEY", "https://api.groq.com/openai/v1", "groq"),
    ("XAI_API_KEY", "https://api.x.ai/v1", "grok"),
)

llm_calls = 0  # 本进程累计真实调用次数


class LLMError(RuntimeError):
    """调用失败（未配置、网络错误、响应不可解析）。调用方应回退确定性路径。"""


def _file_config() -> dict:
    """读取 ~/.bookleme/config.json 的 llm 段（不存在即空）。"""
    try:
        if not CONFIG_PATH.is_file():
            return {}
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    llm = data.get("llm") if isinstance(data, dict) else None
    return llm if isinstance(llm, dict) else {}


def _resolve() -> dict:
    """解析出 {base_url, api_key, model, vision_model, source, missing, ignored}。

    **端点与密钥必须同源**：配置里指了 moonshot 的端点，就只认 moonshot 的密钥；
    绝不拿别家厂商的密钥去补这个端点（那等于把 A 的密钥发给 B 的服务器）。
    没有显式配置时，才从标准环境变量里自动认领一家（认领后端点/密钥/模型同属一家）。

    `missing` 列出「已设了但还差哪一项」——诊断要说清缺的那一项，而不是笼统地说
    「什么都没检测到」；`ignored` 列出「检测到但没被选中」的厂商密钥，避免静默错配。
    """
    cfg = _file_config()
    base = os.environ.get(ENV_BASE) or cfg.get("base_url") or ""
    key = os.environ.get(ENV_KEY) or cfg.get("api_key") or ""
    if not key and cfg.get("api_key_env"):
        key = os.environ.get(str(cfg["api_key_env"]), "")
    model = os.environ.get(ENV_MODEL) or cfg.get("model") or ""
    vision = os.environ.get(ENV_VISION_MODEL) or cfg.get("vision_model") or ""

    explicit = bool(os.environ.get(ENV_BASE) or os.environ.get(ENV_KEY)
                     or os.environ.get(ENV_MODEL))
    source = "环境变量 BOOKLEME_LLM_*" if explicit else (
        f"配置文件 {CONFIG_PATH}" if cfg else "")
    ignored: list[str] = []

    if not (base and key and model):
        # 已指定端点但缺密钥/模型 → 只认与该端点同族的厂商，绝不跨厂商补齐
        matched = [(env_name, default_base, label) for env_name, default_base, label in PROVIDERS
                   if default_base == base]
        if base and matched:
            for env_name, default_base, label in matched:
                pk = os.environ.get(env_name, "")
                if pk and not key:
                    key = pk
                    source = source or f"自动识别 {label}（{env_name}，与已指定端点同源）"
                elif pk:
                    ignored.append(f"{label}（{env_name}）")
        elif not base:
            # 什么都没指定 → 认领一家（端点/密钥/模型同属一家）
            for env_name, default_base, label in PROVIDERS:
                pk = os.environ.get(env_name, "")
                if not pk:
                    continue
                base = default_base
                key = pk
                model = model or _default_model(label)
                source = source or f"自动识别 {label}（{env_name}）"
                break
            for env_name, default_base, label in PROVIDERS:
                if os.environ.get(env_name) and label not in source:
                    ignored.append(f"{label}（{env_name}）")
    found = {"base_url": base, "api_key": key, "model": model}
    missing = [name for name, val in found.items() if not val]
    # 「什么都没配」与「配了一半」要说不一样的话：前者是起步指引，后者是补齐指引
    configured_any = bool(base or key or model or cfg or explicit)
    return {"base_url": base, "api_key": key, "model": model,
            "vision_model": vision, "source": source,
            "missing": missing, "ignored": ignored,
            "configured_any": configured_any}


def config_fingerprint() -> str:
    """生效配置的指纹（**不含密钥明文**）——换模型/换端点必须能被检出。"""
    s = settings()
    raw = "|".join([s.get("base_url", ""), s.get("model", ""),
                    s.get("vision_model", ""), "key" if s.get("api_key") else "nokey"])
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _default_model(label: str) -> str:
    """各厂商一个稳妥的默认模型名（仅作兜底，用户在配置里可覆盖）。"""
    return {
        "openai": "gpt-4o-mini", "kimi": "moonshot-v1-8k", "deepseek": "deepseek-chat",
        "qwen": "qwen-plus", "doubao": "doubao-pro-32k", "zhipu": "glm-4-flash",
        "siliconflow": "Qwen/Qwen2.5-7B-Instruct", "openrouter": "openai/gpt-4o-mini",
        "groq": "llama-3.3-70b-versatile", "grok": "grok-2-latest",
    }.get(label, "")


_RESOLVED: dict | None = None


def settings() -> dict:
    """当前生效的 LLM 配置（带缓存；环境变量变更后调用 reset_counters 可刷新）。"""
    global _RESOLVED
    if _RESOLVED is None:
        _RESOLVED = _resolve()
    return _RESOLVED


def available() -> bool:
    s = settings()
    return bool(s["base_url"] and s["api_key"] and s["model"])


def describe() -> dict:
    """给 `bookleme doctor` 用的可读描述（不含密钥明文）。"""
    s = settings()
    ok = available()
    missing = s.get("missing") or []
    host_hint = ("首选：宿主 Agent 承接——BookLeme 是 harness，在场调它的那个智能体"
                 "本身就是大模型。编译时导出 judge 工单，宿主判完回填，"
                 "groundedness / V2 / V3 就变成真值，全程零配置。"
                 "命令：`bookleme judge`")
    if ok:
        source = s["source"] or "已配置"
        hint = ("编译期 judge / 抽取可用（走外部模型 API）。"
                "不配也能编译——judge 改由宿主 Agent 承接即可。")
    elif not s.get("configured_any"):
        source = "未检测到任何 LLM 配置（不影响使用）"
        hint = ("零配置即可用：" + host_hint +
                " 外部模型通道是可选项，配了任意常见厂商的密钥环境变量"
                "（如 OPENAI_API_KEY）就会被自动识别。")
    elif missing:
        source = s["source"] or "部分配置"
        hint = (f"已检测到部分配置，还缺：{'、'.join(missing)}。"
                "但**不影响使用**——" + host_hint +
                " 想走外部模型通道再补齐即可。")
    else:
        source = "未检测到任何 LLM 配置（不影响使用）"
        hint = ("零配置即可用：" + host_hint +
                " 外部模型通道是可选项，配了任意常见厂商的密钥环境变量"
                "（如 OPENAI_API_KEY）就会被自动识别。")
    return {
        "available": ok,
        "source": source,
        "missing": missing,
        "ignored_providers": s.get("ignored") or [],
        "base_url": s["base_url"],
        "model": s["model"],
        "vision_model": s["vision_model"] or ("(同文本模型)" if ok else ""),
        "config_path": str(CONFIG_PATH),
        "hint": hint,
    }


# 兼容旧引用：模块加载时的静态快照，动态判定请用 available()。
LLM_AVAILABLE = available()


def model_fingerprint(prompt_version: str) -> str:
    model = settings()["model"]
    return hashlib.sha256(f"{model}:{prompt_version}".encode()).hexdigest()[:16]


def reset_counters() -> None:
    global llm_calls, _RESOLVED
    llm_calls = 0
    _RESOLVED = None   # 一并刷新配置缓存（改了环境变量后可立即生效）


PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")


def load_prompt(name: str) -> str:
    """读取版本化 prompt 全文（含 System/User 两段，占位符为 ${...}）。"""
    path = os.path.join(PROMPTS_DIR, f"{name}.md")
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def split_prompt(text: str) -> tuple[str, str]:
    """返回 (system, user_template)。文件以 '## System' / '## User' 分段。"""
    m = re.split(r"^##\s*System\s*$", text, maxsplit=1, flags=re.M)
    if len(m) < 2:
        raise LLMError("prompt 缺少 '## System' 分段")
    m2 = re.split(r"^##\s*User\s*$", m[1], maxsplit=1, flags=re.M)
    if len(m2) < 2:
        raise LLMError("prompt 缺少 '## User' 分段")
    return m2[0].strip(), m2[1].strip()


def _parse_json(content: str) -> dict:
    """稳健解析：剥 ```json 围栏，取最外层花括号对象。"""
    text = content.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise LLMError(f"响应中没有 JSON 对象：{content[:120]!r}")
    return json.loads(text[start:end + 1])


def vision_model() -> str:
    """视觉模型名：优先独立配置的视觉模型，回退文本模型（多数模型本身支持多模态）。"""
    s = settings()
    return s["vision_model"] or s["model"]


def vision_available() -> bool:
    """视觉能力可用性：需文本三件套齐备 + 解析出模型名。"""
    return available() and bool(vision_model())


def _post(url: str, payload: dict, key: str, to: float) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=to) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_with_temp_retry(url: str, payload: dict, key: str, to: float) -> dict:
    """一次 chat/completions 往返；遇 400 温度错误自动以 temperature=1 重试一次。

    记账约定：每一次真实 HTTP 尝试计一次 llm_calls（含失败与被重试的那次），
    与模块文档一致（旧实现漏记成功调用，已修正）。
    """
    global llm_calls

    def attempt() -> dict:
        global llm_calls
        llm_calls += 1
        return _post(url, payload, key, to)

    try:
        return attempt()
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace")
        except OSError:
            pass
        if exc.code == 400 and "temperature" in body:
            payload["temperature"] = 1
            try:
                return attempt()
            except (urllib.error.URLError, OSError, ValueError) as exc2:
                raise LLMError(f"LLM 调用失败（温度重试后）：{exc2}") from exc2
        raise LLMError(f"LLM 调用失败：HTTP {exc.code} {body[:200]}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise LLMError(f"LLM 调用失败：{exc}") from exc


def chat_json(user: str, system: str = "", temperature: float = 0.0,
              max_tokens: int = 2000, timeout: float | None = None) -> dict:
    """一次 chat/completions 调用，返回解析后的 JSON 对象。失败抛 LLMError。"""
    base = settings()["base_url"].rstrip("/")
    key = settings()["api_key"]
    model = settings()["model"]
    if not (base and key and model):
        raise LLMError("未检测到 LLM 配置（见 `bookleme doctor`）")
    url = base if base.endswith("/chat/completions") else base + "/chat/completions"
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})
    payload = {"model": model, "temperature": temperature,
               "max_tokens": max_tokens, "messages": messages}
    to = timeout or float(os.environ.get(ENV_TIMEOUT, "120"))
    data = _post_with_temp_retry(url, payload, key, to)
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"响应结构异常：{str(data)[:120]}") from exc
    return _parse_json(content)


def _data_url(image_path) -> str:
    """本地图片转 data URL（OpenAI 兼容 vision 接口的 image_url.url）。"""
    import base64
    from pathlib import Path
    p = Path(image_path)
    data = p.read_bytes()
    ext = p.suffix.lower().lstrip(".") or "png"
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp"}.get(
        ext, "application/octet-stream")
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def chat_vision_json(user: str, system: str = "", image_path=None, temperature: float = 0.0,
                     max_tokens: int = 1200, timeout: float | None = None) -> dict:
    """视觉版 chat/completions：user 内容为 [文本, image_url] 两段（OpenAI 兼容格式）。

    用于「读图」：把原文图示作为图片输入，让模型解读图里的信息。
    模型名取 BOOKLEME_LLM_VISION_MODEL，未设则回退 BOOKLEME_LLM_MODEL。
    """
    if not image_path:
        raise LLMError("视觉调用缺少图片路径")
    base = settings()["base_url"].rstrip("/")
    key = settings()["api_key"]
    model = vision_model()
    if not (base and key and model):
        raise LLMError("未检测到 LLM 配置（见 `bookleme doctor`）")
    url = base if base.endswith("/chat/completions") else base + "/chat/completions"
    content = [{"type": "text", "text": user},
               {"type": "image_url", "image_url": {"url": _data_url(image_path)}}]
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": content})
    payload = {"model": model, "temperature": temperature,
               "max_tokens": max_tokens, "messages": messages}
    to = timeout or float(os.environ.get(ENV_TIMEOUT, "120"))
    data = _post_with_temp_retry(url, payload, key, to)
    try:
        content_text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"视觉响应结构异常：{str(data)[:120]}") from exc
    return _parse_json(content_text)
