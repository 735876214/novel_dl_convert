"""Calibre ``ebook-convert`` 封装：可选依赖，用于把 EPUB 派生为 MOBI / AZW3。

设计原则：
- **不强制依赖**。默认镜像不含 Calibre（体积很大），因此探测失败时一律返回结构化结果，
  由调用方决定降级（本项目策略：EPUB 照常产出，仅缺少派生格式并给出提示）。
- 探测顺序：环境变量 ``EBOOK_CONVERT_BIN``（可指向自备二进制）→ PATH 上的 ``ebook-convert``。
- 调用带超时兜底，避免大书把转换线程卡死。
"""
import os
import shutil
import subprocess
from pathlib import Path

# 单次转换超时（秒）；大书较慢，可用 opts['ebook_convert_timeout'] 覆盖
DEFAULT_TIMEOUT = 300
# 目标扩展名 → ebook-convert 可用（`.mobi` / `.azw3` 由其按扩展名推断）
SUPPORTED = ("mobi", "azw3")


def _env_bin() -> str:
    return (os.getenv("EBOOK_CONVERT_BIN") or "").strip()


def resolve() -> "str | None":
    """返回可用的 ebook-convert 可执行文件路径；未找到返回 None。"""
    env = _env_bin()
    if env:
        p = Path(env)
        if p.is_file():
            return str(p)
        return shutil.which(env)
    return shutil.which("ebook-convert")


def version() -> str:
    """取版本号首行（失败返回空串，不抛异常）。"""
    path = resolve()
    if not path:
        return ""
    try:
        proc = subprocess.run(
            [path, "--version"], capture_output=True, text=True, timeout=20
        )
        lines = (proc.stdout or proc.stderr or "").strip().splitlines()
        return lines[0].strip() if lines else ""
    except Exception:
        return ""


def capability() -> dict:
    """供接口返回的能力探测结果（界面据此提示「未安装 Calibre」）。"""
    path = resolve()
    return {
        "available": bool(path),
        "path": path or "",
        "version": version() if path else "",
        "env_var": "EBOOK_CONVERT_BIN",
        "supported": list(SUPPORTED),
    }


def convert(src, dst, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """把 ``src`` 转成 ``dst``（目标格式由 dst 扩展名决定）。

    返回 ``{"ok": bool, "output": str, "error": str}`` —— 任何失败都结构化返回，
    不抛异常，便于调用方降级。
    """
    binary = resolve()
    if not binary:
        return {
            "ok": False,
            "output": "",
            "error": "未找到 ebook-convert（可设置 EBOOK_CONVERT_BIN，或安装 Calibre）",
        }

    src_p, dst_p = Path(src), Path(dst)
    if not src_p.is_file():
        return {"ok": False, "output": "", "error": f"源文件不存在：{src_p}"}
    try:
        dst_p.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return {"ok": False, "output": "", "error": f"无法创建目标目录：{e}"}

    try:
        proc = subprocess.run(
            [binary, str(src_p), str(dst_p)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "output": "", "error": f"转换超时（>{timeout}s）"}
    except Exception as e:
        return {"ok": False, "output": "", "error": f"{type(e).__name__}: {e}"}

    if proc.returncode != 0 or not dst_p.is_file():
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        msg = tail[-1].strip() if tail else f"退出码 {proc.returncode}"
        return {"ok": False, "output": "", "error": msg}

    return {"ok": True, "output": str(dst_p), "error": ""}
