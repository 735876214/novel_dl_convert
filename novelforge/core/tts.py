"""TTS（文本转语音）—— **自托管 / 局域网**的 OpenAI-compatible 引擎（第 235 期）。

## 范围（受限版，按既定决策）

上游那套「服务商管理 + 音色策展 + 发现 + 试听 + 排序」是**多服务商**的产品形态。
本项目只做**受限版**：

- **只接自托管 / 局域网的 OpenAI-compatible 引擎**（地址由后端配置）；
- **默认关**（要用户自己开）；
- **超时 / 失败 ⇒ 回落静音并如实提示**（不假装在读）；
- **不落书文件**（合成的音频只进缓存目录）；
- **不做外网云厂商的默认通道**（本项目默认不出网，见 AGENTS.md 第 1 节）。

## 为什么不引一个 TTS 依赖

合成走的是 **HTTP + SSE 流式返回音频**（OpenAI-compatible 的 `/v1/audio/speech`），
用现成的 `httpx` 就够；引一个本地合成引擎（piper / coqui 之类）意味着镜像里多几百 MB
模型文件 —— 与「单用户 NAS 自托管」的形态不匹配。所以**引擎由用户自己跑**，
本项目只做客户端。

## 判据只有这一处

`/v1/audio/speech` 的请求体与响应体格式**由这里定义**（`_speech_payload` / `_audio_bytes`），
别在别处再拼一份 —— 换了引擎（不同实现的字段名有差异）只需改这里。

⚠️ **分块**：长文本一次合成会超时（自托管引擎尤其慢）⇒ 按句切块
（`_chunks`，切在句末，句子太长再按逗号 / 空格退让），逐块合成后按顺序拼接。
"""
from __future__ import annotations

import json
import pathlib
import re
import time

import httpx

#: 默认的 OpenAI-compatible 语音端点（**自托管 / 局域网**用）。
DEFAULT_BASE = "http://127.0.0.1:8000"
DEFAULT_VOICE = "alloy"
DEFAULT_MODEL = "tts-1"

#: 单次合成请求的文本上限（字符）。太长 ⇒ 服务端超时。
MAX_CHARS = 500


def cfg() -> dict:
    """TTS 配置（**从后端配置读**，前端只看到开关与几个字段）。

    键（都在 `tts` 段下）：
    - `enabled`（默认**关**）
    - `base_url`（默认 `http://127.0.0.1:8000`）
    - `api_key`（可空 —— 局域网自托管通常不要 key）
    - `model`（默认 `tts-1`）
    - `voice`（默认 `alloy`）
    - `speed`（0.5–2，默认 1）
    - `timeout`（秒，默认 60）
    """
    from .. import config

    try:
        raw = (config.load_config() or {}).get("tts") or {}
    except Exception:                       # noqa: BLE001 —— 读不到配置就当「关」
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    try:
        speed = float(raw.get("speed", 1) or 1)
    except (TypeError, ValueError):
        speed = 1.0
    try:
        timeout = float(raw.get("timeout", 60) or 60)
    except (TypeError, ValueError):
        timeout = 60.0
    return {
        "enabled": bool(raw.get("enabled", False)),
        "base_url": str(raw.get("base_url") or DEFAULT_BASE).rstrip("/"),
        "api_key": str(raw.get("api_key") or ""),
        "model": str(raw.get("model") or DEFAULT_MODEL),
        "voice": str(raw.get("voice") or DEFAULT_VOICE),
        "speed": max(0.5, min(2.0, speed)),
        "timeout": max(5.0, min(600.0, timeout)),
    }


def status() -> dict:
    """给界面看的状态（**不含** api_key —— 那是凭据）。"""
    c = cfg()
    return {
        "enabled": c["enabled"],
        "base_url": c["base_url"],
        "model": c["model"],
        "voice": c["voice"],
        "speed": c["speed"],
        "has_key": bool(c["api_key"]),
    }


def _chunks(text: str, limit: int = MAX_CHARS) -> list:
    """长文本 → 块（**切在句末**；句子太长再按逗号 / 空格退让）。

    ⚠️ 切在句末是为了让每块都是**完整的一句话** ⇒ 合成出来的音频不会在句中截断。
    """
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if not s:
        return []
    limit = max(1, int(limit))
    out, cur = [], ""

    def flush():
        nonlocal cur
        if cur.strip():
            out.append(cur.strip())
        cur = ""

    for p in re.split(r"(?<=[。！？；.!?;])", s):
        p = p.strip()
        if not p:
            continue
        if len(p) > limit:
            # 单句超限 ⇒ 按逗号 / 顿号 / 空格硬切（尽量切在语义边界上）。
            # ⚠️ 用 `re.findall` 而不是 `re.split` + 零宽断言 ——
            # 两个零宽 lookbehind 用 `|` 连起来**不会切**（Python 的 re 不允许），
            # 那样这一档就永远不触发，单句超限的文本会被整块送出去（必超时）。
            flush()
            buf = ""
            for piece in re.findall(r"[^，,、 ]+[，,、 ]*", p):
                if buf and len(buf) + len(piece) > limit:
                    out.append(buf.strip())
                    buf = piece
                else:
                    buf += piece
                while len(buf) > limit:
                    out.append(buf[:limit].strip())
                    buf = buf[limit:]
            if buf.strip():
                out.append(buf.strip())
            continue
        if cur and len(cur) + len(p) > limit:
            flush()
            cur = p
        else:
            cur += p
    flush()
    return [x for x in out if x]


def _speech_payload(text: str, c: dict) -> dict:
    """请求体（**唯一一处** —— OpenAI-compatible 的字段名由这里定）。"""
    return {
        "model": c["model"],
        "voice": c["voice"],
        "speed": c["speed"],
        "input": text,
        "response_format": "mp3",
    }


def _audio_bytes(raw) -> bytes:
    """响应 → 音频字节（兼容「直接是音频」与「base64 JSON」两种实现）。

    ⚠️ 自托管引擎的实现不统一：OpenAI 官方返回二进制，但不少兼容实现返回
    ``{"audio": "<base64>"}``。两种都认（认不出就如实报错，不静默返回空音频）。
    """
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw)
    if isinstance(raw, str):
        # 可能是 data URI，也可能是裸 base64
        if raw.startswith("data:") and "," in raw:
            raw = raw.split(",", 1)[1]
        import base64
        try:
            return base64.b64decode(raw)
        except Exception:
            return raw.encode("utf-8", "ignore")
    if isinstance(raw, dict):
        for key in ("audio", "data", "content"):
            if raw.get(key):
                return _audio_bytes(raw[key])
    return b""


def synthesize(text: str, voice: str = "", speed: float = 0) -> dict:
    """合成一段文本 → 音频文件（落在**缓存目录**）。

    返回 ``{"ok", "path", "bytes", "chunks", "message"}``。
    ⚠️ **失败即失败**（`ok=False` + 中文原因）—— 不返回空音频假装成功。
    """
    c = cfg()
    if not c["enabled"]:
        return {"ok": False, "message": "TTS 未启用（设置里开启后才可用）",
                "path": "", "bytes": 0, "chunks": 0}
    blocks = _chunks(text)
    if not blocks:
        return {"ok": False, "message": "没有可朗读的文本", "path": "", "bytes": 0, "chunks": 0}
    if voice:
        c["voice"] = voice
    if speed:
        c["speed"] = max(0.5, min(2.0, float(speed)))

    url = c["base_url"] + "/v1/audio/speech"
    headers = {"Content-Type": "application/json"}
    if c["api_key"]:
        headers["Authorization"] = "Bearer " + c["api_key"]

    parts = []
    for i, b in enumerate(blocks):
        try:
            r = httpx.post(url, json=_speech_payload(b, c), headers=headers,
                           timeout=c["timeout"])
        except httpx.HTTPError as e:
            return {"ok": False, "message": f"合成失败（第 {i + 1}/{len(blocks)} 块）：{e}",
                    "path": "", "bytes": 0, "chunks": len(blocks)}
        if r.status_code >= 400:
            return {"ok": False,
                    "message": f"合成失败（第 {i + 1}/{len(blocks)} 块）：HTTP {r.status_code}",
                    "path": "", "bytes": 0, "chunks": len(blocks)}
        # ⚠️ **先判是不是 JSON**：兼容实现回的是 ``{"audio": "<base64>"}``，
        # 而那段 JSON 本身**非空** ⇒ 直接当二进制用会拿到一堆 JSON 字节当音频
        # （播出来是噪声，而且「看起来成功」）。
        data = b""
        # ⚠️ `httpx.Response.headers` 是 **Headers** 对象（不是 dict）⇒ 用 `get` 取；
        # 测试替身可能给 dict，也可能给 str ⇒ 两种都兜住。
        _h = getattr(r, "headers", None)
        if hasattr(_h, "get"):
            ctype = str(_h.get("content-type", "") or "")
        else:
            ctype = str(_h or "")
        body = r.content
        looks_json = ("json" in ctype) or (
            isinstance(body, (bytes, bytearray)) and body[:1] in (b"{", b"[")
        )
        if looks_json:
            try:
                data = _audio_bytes(r.json())
            except Exception:
                data = b""
        else:
            data = _audio_bytes(body)
            if not data:
                try:
                    data = _audio_bytes(r.json())
                except Exception:
                    data = b""
        if not data:
            return {"ok": False,
                    "message": f"合成失败（第 {i + 1}/{len(blocks)} 块）：响应里没有音频",
                    "path": "", "bytes": 0, "chunks": len(blocks)}
        parts.append(data)

    blob = b"".join(parts)
    path = _cache_path(blob)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
    except OSError as e:
        return {"ok": False, "message": f"音频落盘失败：{e}",
                "path": "", "bytes": len(blob), "chunks": len(blocks)}
    return {"ok": True, "path": str(path), "bytes": len(blob),
            "chunks": len(blocks), "message": ""}


def _cache_path(blob: bytes) -> pathlib.Path:
    """音频缓存路径（**按内容哈希**命名 ⇒ 同内容不重复占空间）。

    ⚠️ 落在 `CACHE_DIR` 下，**不落书文件**（AGENTS.md 第 1 节的硬约束）。
    """
    import hashlib

    from .. import config

    h = hashlib.sha256(blob).hexdigest()[:32]
    root = pathlib.Path(getattr(config, "CACHE_DIR", ".")) / "tts"
    return root / (h + ".mp3")


def probe() -> dict:
    """连通性探针（**打真请求**，不外呼则如实说）。

    ⚠️ 用一个极短的文本（``"。"``）—— 合成一整个词只为验证连通性太浪费。
    """
    c = cfg()
    if not c["enabled"]:
        return {"ok": False, "message": "TTS 未启用"}
    url = c["base_url"] + "/v1/audio/speech"
    headers = {"Content-Type": "application/json"}
    if c["api_key"]:
        headers["Authorization"] = "Bearer " + c["api_key"]
    try:
        r = httpx.post(url, json=_speech_payload("。", c), headers=headers,
                       timeout=min(20.0, c["timeout"]))
    except httpx.HTTPError as e:
        return {"ok": False, "message": f"连不上 {c['base_url']}：{e}"}
    if r.status_code >= 400:
        return {"ok": False, "message": f"HTTP {r.status_code}"}
    return {"ok": True, "message": f"连通正常（{c['base_url']}）"}


def speak_url(path: str) -> str:
    """缓存音频的对外 URL（前端拿它喂 `<audio>`）。

    ⚠️ 路径要在**缓存目录内**（不许穿越到别处）。
    """
    from .. import config

    root = pathlib.Path(getattr(config, "CACHE_DIR", ".")).resolve()
    try:
        p = pathlib.Path(str(path)).resolve()
    except Exception:                       # noqa: BLE001
        return ""
    try:
        p.relative_to(root)
    except ValueError:
        return ""
    return "/api/tts/audio/" + p.name
