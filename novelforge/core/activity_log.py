"""活动日志：统一记录每一次「转换 / 添加」的时间、文件名、操作类型与成败。

落盘两份（同目录）：
- ``activity.log``   人类可读文本，按行追加，可在 NAS 上直接 tail / 下载查看
- ``activity.jsonl`` 结构化 JSON Line，供 Web API 与前端表格消费

日志目录由环境变量 ``LOG_DIR`` 控制，默认 ``<CONFIG_DIR>/logs``（随配置目录挂载持久化）。
无法写入时自动降级到系统临时目录，绝不因日志失败打断主流程。
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import tempfile
import threading
import time
from collections import deque
from datetime import datetime

# ---- 操作类型 ----
ACTION_CONVERT = "转换"   # txt → epub
ACTION_ADD = "添加"       # 非 txt 文件直接导出到 output
ACTION_SKIP = "跳过"      # 被忽略规则排除
# 工具页（实体管理 / 批量重命名 / 重复书籍）对成品文件的改动。
# 这两个取值是新增的，但与既有取值同构：同样只写「动作 + 文件名 + 成败」，
# 前端日志表的「动作」列直接展示原值，无需改动。
ACTION_RENAME = "重命名"  # 成品文件改名
ACTION_RECYCLE = "清理"   # 移入回收目录（不真删）

# ---- 结果 ----
STATUS_OK = "成功"
STATUS_FAIL = "失败"

LOG_FILENAME = "activity.log"
JSONL_FILENAME = "activity.jsonl"
TS_FORMAT = "%Y-%m-%d %H:%M:%S"

_logger = logging.getLogger("novelforge.activity")

# 用可重入锁：log() / clear() 在持锁时还会调用 log_dir()，普通 Lock 会自锁
_lock = threading.RLock()
_memory: "deque[dict]" = deque(maxlen=2000)   # 内存环形缓冲，避免每次读盘
_dir: pathlib.Path | None = None
_dir_ready = False


# ---------------- 目录 ----------------

def _candidate_dirs() -> list:
    """按优先级给出候选日志目录。"""
    env = os.getenv("LOG_DIR")
    cands = []
    if env:
        cands.append(pathlib.Path(env))
    try:
        from .. import config
        cands.append(pathlib.Path(config.CONFIG_DIR) / "logs")
    except Exception:
        pass
    cands.append(pathlib.Path(tempfile.gettempdir()) / "novelforge-logs")
    return cands


def log_dir() -> pathlib.Path:
    """当前生效的日志目录（首个可创建并可写的候选）。"""
    global _dir, _dir_ready
    if _dir_ready and _dir is not None:
        return _dir
    with _lock:
        if _dir_ready and _dir is not None:
            return _dir
        for cand in _candidate_dirs():
            try:
                cand.mkdir(parents=True, exist_ok=True)
                probe = cand / ".write_probe"
                with open(probe, "a", encoding="utf-8"):
                    pass
                probe.unlink(missing_ok=True)
                _dir = cand
                break
            except Exception:
                continue
        if _dir is None:                       # 理论上不可达：临时目录必然可写
            _dir = pathlib.Path(tempfile.gettempdir())
        _dir_ready = True
    return _dir


def set_dir(path) -> pathlib.Path:
    """显式指定日志目录（测试 / CLI 用）。"""
    global _dir, _dir_ready
    p = pathlib.Path(path)
    p.mkdir(parents=True, exist_ok=True)
    with _lock:
        _dir, _dir_ready = p, True
    return p


def log_path() -> pathlib.Path:
    return log_dir() / LOG_FILENAME


def jsonl_path() -> pathlib.Path:
    return log_dir() / JSONL_FILENAME


# ---------------- 写入 ----------------

def _fmt_size(size) -> str:
    try:
        size = float(size)
    except Exception:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return ""


def _text_line(e: dict) -> str:
    """人类可读的一行日志：时间 | 操作 | 结果 | 文件名[ → 输出] | 备注"""
    parts = [
        e.get("ts", ""),
        e.get("action", ""),
        e.get("status", ""),
        e.get("file", ""),
    ]
    out = e.get("output")
    if out:
        parts[-1] = f"{parts[-1]} → {out}"
    line = " | ".join(p for p in parts if p)
    extra = []
    if e.get("size"):
        extra.append(_fmt_size(e["size"]))
    if e.get("duration_ms"):
        extra.append(f"{e['duration_ms'] / 1000:.1f}s")
    detail = (e.get("detail") or "").strip()
    if detail:
        extra.append(detail)
    if extra:
        line += " | " + "，".join(extra)
    return line


def log(action: str, file: str, status: str, output: str = "", detail: str = "",
        size=None, duration_ms=None, source: str = "") -> dict:
    """写一条活动日志，返回该条记录（dict）。

    action: ACTION_CONVERT / ACTION_ADD / ACTION_SKIP
    status: STATUS_OK / STATUS_FAIL
    """
    now = datetime.now()
    entry = {
        "ts": now.strftime(TS_FORMAT),
        "ts_epoch": round(time.time(), 3),
        "action": action,
        "status": status,
        "file": file,
        "output": output or "",
        "detail": (detail or "").strip(),
        "size": int(size) if size is not None else None,
        "duration_ms": int(duration_ms) if duration_ms else None,
        "source": source or "",
    }
    line_txt = _text_line(entry)
    try:
        line_json = json.dumps(entry, ensure_ascii=False)
    except Exception:
        line_json = "{}"

    with _lock:
        _memory.append(entry)
        d = log_dir()
        try:
            with open(d / LOG_FILENAME, "a", encoding="utf-8") as f:
                f.write(line_txt + "\n")
        except Exception:
            pass
        try:
            with open(d / JSONL_FILENAME, "a", encoding="utf-8") as f:
                f.write(line_json + "\n")
        except Exception:
            pass

    # 同步输出到标准日志（docker logs 可见）
    if status == STATUS_FAIL:
        _logger.error(line_txt)
    else:
        _logger.info(line_txt)
    return entry


# 便捷写法：语义化封装，调用处不必记常量
def log_convert_ok(file, output, **kw):
    return log(ACTION_CONVERT, file, STATUS_OK, output=output, **kw)


def log_convert_fail(file, detail, **kw):
    return log(ACTION_CONVERT, file, STATUS_FAIL, detail=detail, **kw)


def log_add_ok(file, output, **kw):
    return log(ACTION_ADD, file, STATUS_OK, output=output, **kw)


def log_add_fail(file, detail, **kw):
    return log(ACTION_ADD, file, STATUS_FAIL, detail=detail, **kw)


# ---------------- 读取 ----------------

def recent(limit: int = 200, action: str = "", status: str = "", q: str = "") -> list:
    """读取最近的活动记录（新→旧），支持按操作 / 结果 / 关键字过滤。

    优先用内存缓冲；内存为空（如刚重启）时回落到 jsonl 文件尾部。
    """
    if not _memory:
        # 刚重启时内存为空：从 jsonl 尾部回填（deque 有上限，不会无限增长）
        for e in _read_tail(_memory.maxlen or 2000):
            _memory.append(e)
    items = list(reversed(_memory))        # 新 → 旧

    if action:
        items = [e for e in items if e.get("action") == action]
    if status:
        items = [e for e in items if e.get("status") == status]
    if q:
        ql = q.lower()
        items = [e for e in items
                 if ql in str(e.get("file", "")).lower()
                 or ql in str(e.get("output", "")).lower()
                 or ql in str(e.get("detail", "")).lower()]
    return items[:limit] if limit and limit > 0 else items


def _read_tail(n: int) -> list:
    """从 jsonl 尾部读 n 条（旧→新）。"""
    p = jsonl_path()
    if not p.is_file():
        return []
    try:
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()[-n:]
    except Exception:
        return []
    out = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


def count() -> dict:
    """成功 / 失败计数（基于内存缓冲，进程内有效）。"""
    ok = sum(1 for e in _memory if e.get("status") == STATUS_OK)
    fail = sum(1 for e in _memory if e.get("status") == STATUS_FAIL)
    return {"total": len(_memory), "success": ok, "failed": fail}


def clear() -> bool:
    """清空日志文件与内存缓冲。"""
    with _lock:
        _memory.clear()
    try:
        for name in (LOG_FILENAME, JSONL_FILENAME):
            p = log_dir() / name
            if p.is_file():
                p.unlink()
        return True
    except Exception:
        return False
