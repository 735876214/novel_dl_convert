"""输入目录监听：上传到 input 的文件自动处理并导出到 output。

规则（需求）：
1. ``.txt``  → 走转换管线生成 EPUB，导出到导出目录（日志记为「转换」）
2. 非 ``.txt`` → 原样复制到导出目录（日志记为「添加」）
3. 每一次处理都写活动日志：时间 / 文件名 / 操作 / 成功或失败

实现说明：
- 采用**轮询**而非 inotify：NAS 上 input 常是 SMB / NFS 网络挂载，inotify 事件不可靠
  （甚至完全不触发），轮询 + 「文件大小稳定判定」在跨机器挂载下最稳。
- **状态持久化**（mtime + size）：已处理过的文件重启后不会重复转换；文件被覆盖更新
  （size/mtime 变化）才会重新处理。
- 失败按 ``max_retries`` 重试，超过上限后记为失败并跳过，避免坏文件反复刷日志。
"""
from __future__ import annotations

import fnmatch
import json
import shutil
import threading
import time
from pathlib import Path

from . import activity_log, pipeline
from .. import config

STATE_FILENAME = "watcher_state.json"

# 默认忽略：隐藏文件、下载/编辑临时文件、增量更新 sidecar、日志文件
DEFAULT_IGNORE = [
    ".*",
    "*.tmp", "*.temp", "*.part", "*.crdownload", "*.partial", "*.download",
    "*.swp", "*.swx", "~$*",
    "*.meta.json", "*.log", "*.jsonl",
]


class FolderWatcher:
    """监听输入目录，自动转换 / 添加文件到导出目录。"""

    def __init__(self, input_dir=None, output_dir=None, cfg=None, **kw):
        self.input_dir = Path(input_dir or config.INPUT_DIR)
        self.output_dir = Path(output_dir or config.OUTPUT_DIR)
        self.cfg = cfg if cfg is not None else config.load_config()
        w = (self.cfg or {}).get("watcher", {}) or {}

        self.interval = float(kw.get("interval") or w.get("interval") or 5.0)
        self.recursive = bool(kw.get("recursive", w.get("recursive", False)))
        self.settle_seconds = float(w.get("settle_seconds", 1.0))
        self.stable_rounds = max(1, int(w.get("stable_rounds", 2)))
        self.copy_non_txt = bool(w.get("copy_non_txt", True))
        self.process_existing = bool(w.get("process_existing", True))
        self.max_retries = max(0, int(w.get("max_retries", 3)))
        self.ignore = list(w.get("ignore") or DEFAULT_IGNORE)

        self.state_file = Path(
            kw.get("state_file") or config.CACHE_DIR / STATE_FILENAME
        )
        self.state: dict = self._load_state()

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._primed = False
        self.last_scan = 0.0
        self.stats = {"converted": 0, "added": 0, "failed": 0, "scans": 0}

    # ---------------- 状态持久化 ----------------

    def _load_state(self) -> dict:
        try:
            if self.state_file.is_file():
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        return {}

    def _save_state(self):
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_file.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False)
            tmp.replace(self.state_file)
        except Exception:
            pass

    def _sig(self, p: Path) -> tuple:
        try:
            st = p.stat()
            return (int(st.st_size), round(float(st.st_mtime), 3))
        except OSError:
            return ()

    def mark_processed(self, path) -> None:
        """把某文件登记为「已处理」，避免监听线程重复处理（上传 / 下载接口用）。"""
        p = Path(path)
        sig = self._sig(p)
        if not sig:
            return
        try:
            key = str(p.relative_to(self.input_dir))
        except Exception:
            key = p.name
        with self._lock:
            self.state[key] = {"size": sig[0], "mtime": sig[1], "failed": 0}
            self._save_state()

    def mark_recent(self, seconds: float = 30.0, suffix: str = ".txt") -> int:
        """把「最近 N 秒内刚写入」的文件登记为已处理。

        用于下载等内部流程：它们已经自己生成了成品，不该再被监听线程重复转换一次。
        """
        now = time.time()
        marked = 0
        for p in self._iter_files():
            if suffix and p.suffix.lower() != suffix:
                continue
            try:
                if now - p.stat().st_mtime <= seconds:
                    self.mark_processed(p)
                    marked += 1
            except OSError:
                continue
        return marked

    # ---------------- 文件筛选 ----------------

    def _ignored(self, p: Path) -> bool:
        name = p.name
        for pat in self.ignore:
            if fnmatch.fnmatch(name, pat):
                return True
        return False

    def _iter_files(self):
        if not self.input_dir.is_dir():
            return []
        it = self.input_dir.rglob("*") if self.recursive else self.input_dir.iterdir()
        try:
            return [p for p in it if p.is_file()]
        except Exception:
            return []

    def _wait_stable(self, p: Path) -> bool:
        """连续 stable_rounds 次读到相同大小才认为写入完成。"""
        last = -1
        for _ in range(self.stable_rounds + 1):
            try:
                size = p.stat().st_size
            except OSError:
                return False
            if size == last:
                return True
            last = size
            if self._stop.wait(self.settle_seconds):
                return False
        return False

    # ---------------- 处理 ----------------

    def _opts(self) -> dict:
        return {
            "traditionalize": bool((self.cfg or {}).get("traditionalize", False)),
            "force": True,      # 内容有变化就重转，保证 output 是最新
            "merge": True,
            "cfg": self.cfg,
        }

    def handle_file(self, p: Path) -> tuple:
        """处理单个文件，返回 (结果类型, 详情)。结果类型：converted / added / failed / skipped"""
        try:
            size = p.stat().st_size
        except OSError as e:
            return ("failed", str(e))
        if size == 0:
            return ("skipped", "空文件")

        t0 = time.time()
        dur = lambda: int((time.time() - t0) * 1000)

        if p.suffix.lower() == ".txt":
            try:
                out = pipeline.convert_txt(p, self.output_dir, self._opts())
                activity_log.log_convert_ok(
                    p.name, Path(out).name, size=size, duration_ms=dur(), source="watcher"
                )
                return ("converted", str(out))
            except Exception as e:
                activity_log.log_convert_fail(
                    p.name, f"{type(e).__name__}: {e}", size=size, duration_ms=dur(), source="watcher"
                )
                return ("failed", str(e))

        if not self.copy_non_txt:
            return ("skipped", "非 txt 且已关闭 copy_non_txt")

        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            dst = self.output_dir / p.name
            shutil.copy2(p, dst)
            activity_log.log_add_ok(p.name, dst.name, size=size, duration_ms=dur(), source="watcher")
            return ("added", str(dst))
        except Exception as e:
            activity_log.log_add_fail(p.name, f"{type(e).__name__}: {e}", size=size, source="watcher")
            return ("failed", str(e))

    def scan_once(self) -> dict:
        """扫描一轮，返回本轮结果摘要。"""
        with self._lock:
            return self._scan_locked()

    def _scan_locked(self) -> dict:
        self.input_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        files = self._iter_files()
        if not self._primed:                      # 首轮：决定是否处理历史存量文件
            self._primed = True
            if not self.process_existing:
                for p in files:
                    if self._ignored(p):
                        continue
                    sig = self._sig(p)
                    if sig:
                        self.state[str(p.relative_to(self.input_dir))] = {
                            "size": sig[0], "mtime": sig[1], "failed": 0,
                        }
                self._save_state()
                self.last_scan = time.time()
                return {"scanned": 0, "converted": [], "added": [], "failed": [], "skipped": 0}

        result = {"scanned": 0, "converted": [], "added": [], "failed": [], "skipped": 0}
        dirty = False

        for p in sorted(files):
            if self._stop.is_set():
                break
            if self._ignored(p):
                continue
            try:
                key = str(p.relative_to(self.input_dir))
            except Exception:
                key = p.name

            sig = self._sig(p)
            if not sig:
                continue
            cur = {"size": sig[0], "mtime": sig[1], "failed": 0}
            old = self.state.get(key)
            if old and old.get("size") == cur["size"] and old.get("mtime") == cur["mtime"]:
                fails = int(old.get("failed", 0))
                # 成功过、或已放弃的（重试到上限）不再处理；失败未到上限的继续重试
                if fails == 0 or fails >= max(1, self.max_retries):
                    continue
                cur["failed"] = fails

            result["scanned"] += 1
            if not self._wait_stable(p):          # 还在写入，下轮再处理
                continue

            kind, detail = self.handle_file(p)
            if kind in ("converted", "added"):
                cur["failed"] = 0
                self.state[key] = cur
                self.stats[kind] += 1
                result[kind].append({"file": p.name, "output": Path(detail).name})
                dirty = True
            elif kind == "failed":
                cur["failed"] = int(cur.get("failed", 0)) + 1
                self.state[key] = cur
                self.stats["failed"] += 1
                result["failed"].append({"file": p.name, "error": str(detail)})
                dirty = True
            else:
                result["skipped"] += 1

        if dirty:
            self._save_state()
        self.stats["scans"] += 1
        self.last_scan = time.time()
        return result

    # ---------------- 线程控制 ----------------

    def _loop(self):
        while not self._stop.wait(self.interval):
            try:
                self.scan_once()
            except Exception:                     # 单轮异常不能让监听线程死掉
                time.sleep(self.interval)

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="novelforge-watcher", daemon=True
        )
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=self.interval + 5)
        self._thread = None

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def run_forever(self):
        """前台阻塞运行（CLI 用），首轮立即扫描。"""
        try:
            while not self._stop.is_set():
                self.scan_once()
                if self._stop.wait(self.interval):
                    break
        except KeyboardInterrupt:
            pass
        finally:
            self._stop.set()

    def status(self) -> dict:
        return {
            "running": self.is_running(),
            "input": str(self.input_dir),
            "output": str(self.output_dir),
            "interval": self.interval,
            "recursive": self.recursive,
            "copy_non_txt": self.copy_non_txt,
            "ignore": self.ignore,
            "last_scan": self.last_scan,
            "stats": dict(self.stats),
        }


def build_watcher(cfg: dict | None = None, **kw) -> FolderWatcher:
    """按配置构造监听器的便捷入口。"""
    return FolderWatcher(cfg=cfg, **kw)
