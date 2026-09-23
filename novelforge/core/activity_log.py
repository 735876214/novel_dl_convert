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
from contextvars import ContextVar
from datetime import datetime

# ---- 操作类型 ----
ACTION_CONVERT = "转换"   # txt → epub
ACTION_ADD = "添加"       # 非 txt 文件直接导出到 output
ACTION_SKIP = "跳过"      # 被忽略规则排除
# 工具页（实体管理 / 重排册号 / 重复书籍 / 库布局）对成品文件与元数据的改动。
# 这两个取值是新增的，但与既有取值同构：同样只写「动作 + 文件名 + 成败」，
# 前端日志表的「动作」列直接展示原值，无需改动。
# ⚠️ 「重命名」现在由两条路径产生：实体改名（**只写元数据**，见
# fileops.apply_entity_rename）与同名冲突修复 / 库布局（真改文件名）。
ACTION_RENAME = "重命名"  # 改名：实体改名（元数据）/ 冲突修复与布局（真改文件）
ACTION_RECYCLE = "清理"   # 移入回收目录（不真删）
ACTION_FONT = "字体"      # 阅读字体的上传 / 删除（第 3 期新增）
# 偏好模式的变更（新建/更新/删除）。**设备上报不写日志** —— 每次启动都会发生、
# 没有审计价值，写进去只会把审计流水淹掉。
ACTION_PREFS = "偏好"     # 偏好模式变更（第 3 期新增）
ACTION_LAYOUT = "整理"    # 整理为 Komga 库布局（第 4 期新增）
ACTION_METADATA = "元数据"  # 元数据抓取补全（第 5 期新增）
# 刮削出版（第 18 期）：把刮削结果写进成品目录的**硬链接副本**。
# 也用于「副本被删除，原文件待确认」这类**待办提示** —— 用户要能在这条流水里
# 看到「谁被删了、要不要连原文件一起删」，故单独一个动作而不是混进「元数据」。
ACTION_SCRAPE = "刮削"
# 重置阅读状态（第 34 期）：「从头开始」删掉会话 / 进度 / 状态三处**读出来的痕迹**。
# 它不可撤销（会话删了算不回来），属于要有审计留痕的动作 —— 与「清理」同性质，
# 但「清理」在界面上指的是移入回收目录，语义不同，故单列一个取值。
ACTION_RESET = "重置"
# 外部服务同步（第 52 期）：把阅读状态 / 评分书评 / 书摘推给 Hardcover / Readwise。
# 它是**写向第三方**的动作，属于要有审计留痕的一类，故单列一个取值。
ACTION_SYNC = "同步"

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


# ---------------- 操作者（actor）----------------
# 由 server 的鉴权中间件在每次请求开始时设置（见 server._auth_middleware）。
# 深层调用（如 core/fileops 的改名 / 清理）没有 request 参数，靠它自动带上操作者，
# 无需把这些函数的签名逐个改掉。
# 后台任务（watcher、下载）不在请求上下文里 → 取到空串，由写入端记「系统」。
_ACTOR: ContextVar[str] = ContextVar("novelforge_actor", default="")


def set_actor(actor: str) -> None:
    """设置当前请求的操作者（登录账号名）。"""
    _ACTOR.set((actor or "").strip())


def current_actor() -> str:
    """取当前操作者；无请求上下文时返回空串。"""
    return _ACTOR.get()


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
        size=None, duration_ms=None, source: str = "", actor: str = "") -> dict:
    """写一条活动日志，返回该条记录（dict）。

    action: ACTION_CONVERT / ACTION_ADD / ACTION_SKIP
    status: STATUS_OK / STATUS_FAIL
    actor:  操作者（登录账号名）。无请求上下文的后台任务写「系统」；
            历史条目没有该字段，读取端按「未知」渲染，不影响兼容性。
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
        # 显式传入优先；否则取当前请求的操作者（由鉴权中间件设置）。
        # 后台任务取不到 → 空串，界面按「未记录」渲染。
        "actor": (actor or current_actor()).strip(),
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

def recent(limit: int = 200, action: str = "", status: str = "", q: str = "",
           actor: str = "") -> list:
    """读取最近的活动记录（新→旧），支持按操作 / 结果 / 关键字 / 操作者过滤。

    内存缓冲只含**本次进程**写入的记录。原实现仅在「内存为空」时才回填 jsonl，
    于是重启后只要发生一次新写入，内存就不再为空，历史条目被整体遮蔽 ——
    对审计视图是致命的（只看得到重启之后发生的事）。
    现改为：内存不足 limit 条时，用 jsonl 尾部**重建**缓冲。
    jsonl 是追加式且包含本进程刚写的那几条，因此重建结果既完整又有序。
    """
    need = limit if limit and limit > 0 else 0
    if need and len(_memory) < need:
        tail = _read_tail(max(need, _memory.maxlen or 2000))   # 旧 → 新
        if tail:
            _memory.clear()
            for e in tail:
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
    if actor:
        # 精确匹配（操作者是账号名或「系统」，不是搜索词）—— 与 q 的子串语义刻意不同
        items = [e for e in items if str(e.get("actor") or "").strip() == actor]
    return items[:limit] if limit and limit > 0 else items


def actors(scan: int = 1000) -> list:
    """出现过的操作者清单（去重 + 排序），供审计视图的操作者下拉用。

    取最近 scan 条 —— 与 `api_notifications` 的 `unread_total` 同一口径（内存缓冲
    2000 条，一半足以覆盖实际使用）。**不受当前筛选影响**：否则选中一个操作者后
    候选清单会塌缩成一项，再也切不回去。

    ⚠️ 空 actor（历史条目 / 未鉴权路径）不列入 —— 那是「没有记录」，不是一个可选项。
    """
    seen = {str(e.get("actor") or "").strip() for e in recent(limit=scan)}
    seen.discard("")
    return sorted(seen)


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
