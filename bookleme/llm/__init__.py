"""LLM adapter: OpenAI-compatible chat completions over stdlib urllib.

零第三方依赖。通过环境变量配置（缺任一项 → available() 为 False，
调用方回退确定性抽取器，绝不中断流水线）：

  BOOKLEME_LLM_BASE_URL   如 https://api.kimi.com/coding/v1（自动补 /chat/completions）
  BOOKLEME_LLM_API_KEY    Bearer token
  BOOKLEME_LLM_MODEL      模型名
  BOOKLEME_LLM_TIMEOUT    可选，秒（默认 120）

诚实标注约定：
  - 每次真实 HTTP 调用计一次 llm_calls（含失败的调用）；
  - model_fingerprint = sha256(model + prompt_version)，与 prompt 版本绑定，
    防止换模型/换 prompt 后指标被误当成同一实验（见 prompts/README.md）；
  - LLM 产出的引文一律回原文逐字校验（find），不得直接信任模型输出。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request

ENV_BASE = "BOOKLEME_LLM_BASE_URL"
ENV_KEY = "BOOKLEME_LLM_API_KEY"
ENV_MODEL = "BOOKLEME_LLM_MODEL"
ENV_TIMEOUT = "BOOKLEME_LLM_TIMEOUT"
ENV_VISION_MODEL = "BOOKLEME_LLM_VISION_MODEL"  # 可选：视觉模型；缺省回退文本模型

llm_calls = 0  # 本进程累计真实调用次数


class LLMError(RuntimeError):
    """调用失败（未配置、网络错误、响应不可解析）。调用方应回退确定性路径。"""


def available() -> bool:
    return bool(os.environ.get(ENV_BASE) and os.environ.get(ENV_KEY)
                and os.environ.get(ENV_MODEL))


# 兼容旧引用：模块加载时的静态快照，动态判定请用 available()。
LLM_AVAILABLE = available()


def model_fingerprint(prompt_version: str) -> str:
    model = os.environ.get(ENV_MODEL, "")
    return hashlib.sha256(f"{model}:{prompt_version}".encode()).hexdigest()[:16]


def reset_counters() -> None:
    global llm_calls
    llm_calls = 0


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
    """视觉模型名：优先 BOOKLEME_LLM_VISION_MODEL，回退文本模型。"""
    return os.environ.get(ENV_VISION_MODEL) or os.environ.get(ENV_MODEL, "")


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
    base = os.environ.get(ENV_BASE, "").rstrip("/")
    key = os.environ.get(ENV_KEY, "")
    model = os.environ.get(ENV_MODEL, "")
    if not (base and key and model):
        raise LLMError(f"{ENV_BASE}/{ENV_KEY}/{ENV_MODEL} 未全部配置")
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
    base = os.environ.get(ENV_BASE, "").rstrip("/")
    key = os.environ.get(ENV_KEY, "")
    model = vision_model()
    if not (base and key and model):
        raise LLMError(f"{ENV_BASE}/{ENV_KEY}/{ENV_MODEL} 未全部配置")
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
