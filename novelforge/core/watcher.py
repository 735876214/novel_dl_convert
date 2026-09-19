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

from . import activity_log, audio, komga, lib_settings, pipeline
from .. import config

STATE_FILENAME = "watcher_state.json"

#: 旁路线程登记表：`*_async` 派生的那些「发了就不管」的线程。
#: 为什么要登记：它们都要**查库**（`library.find` → `publish_dir` → `db.get_library`），
#: 而测试收尾 / 进程关停会关掉 DB 连接 —— 线程晚一步动手就会在已关闭的连接上查库，
#: 本仓实测到过解释器 **segfault**（全量 pytest 跑到后半程突然崩、连汇总行都打不出来）。
#: 登记后配 :func:`wait_pending`，收尾方就能在关库**之前**等它们收干净。
_BG_THREADS: dict = {}
_BG_LOCK = threading.Lock()


def _spawn_bg(target, name: str) -> threading.Thread:
    """起一个**被登记**的旁路线程（daemon，不阻塞主流程）。"""
    th = threading.Thread(target=target, daemon=True, name=name)
    with _BG_LOCK:
        _BG_THREADS[id(th)] = th
    th.start()
    return th


def wait_pending(timeout: float = 5.0) -> int:
    """等所有旁路线程结束 → 返回**超时后仍未结束**的数量（``0`` = 全收干净了）。

    调用点：测试的 ``isolated`` 夹具在 ``db.close()`` **之前**（见 ``tests/conftest.py``）；
    将来若做优雅关停，也应在这里等一次再拆连接。
    """
    deadline = time.monotonic() + max(0.0, float(timeout))
    while True:
        with _BG_LOCK:
            for tid in [k for k, t in _BG_THREADS.items() if not t.is_alive()]:
                _BG_THREADS.pop(tid, None)
            alive = list(_BG_THREADS.values())
        if not alive:
            return 0
        left = deadline - time.monotonic()
        if left <= 0:
            return len(alive)
        for t in alive:
            t.join(timeout=min(0.25, left))


def auto_fetch_async(name: str, cfg: dict | None) -> None:
    """入库后自动抓取元数据（**仅在配置开启时**）。

    三条约束：

    1. **必须异步**：抓取要外呼公网（每本 1–3 秒）。watcher 是后台线程，同步做会拖慢
       扫描轮次；起个 daemon 线程最省心 —— 晚几秒补上元数据没有任何影响。
    2. **吞掉一切异常**：这是旁路增强，不能因为外网不通就影响入库结果。
    3. **只对 EPUB**：其它格式没有可写的 OPF（与 `metafetch.plan` 的口径保持一致）。
    """
    mf = (cfg or {}).get("metadata_fetch") or {}
    if not mf.get("enabled") or not mf.get("auto_on_import"):
        return
    if not str(name).lower().endswith(".epub"):
        return

    def _run():
        try:
            from . import metafetch
            res = metafetch.auto_fetch(name, cfg=cfg)
            if res.get("ok"):
                detail = f"入库自动补全 {len(res.get('fields') or [])} 个字段"
                if res.get("cover"):
                    detail += "，含封面"
                activity_log.log(activity_log.ACTION_METADATA, name,
                                 activity_log.STATUS_OK, source="watcher", detail=detail)
        except Exception:
            pass

    _spawn_bg(_run, "novelforge-auto-fetch")


def enqueue_scrape_async(name: str, lib: dict | None, cfg: dict | None) -> None:
    """入库后把这本书排进**刮削出版**队列（异步，不拖慢扫描轮次）。

    与 :func:`auto_fetch_async` 刻意分成两件事：
    - 抓在线元数据看 ``metadata_fetch.enabled``；
    - 出版硬链接副本看 ``scrape.enabled``（每库可覆写第 13 期机制）。

    用户完全可能关掉在线抓取、只用本地已有元数据把副本出版出去，因此不能把入队
    塞进 auto_fetch_async 的提前 return 之后。

    **这里只入队，不出版** —— 出版是「外呼 + 写盘」的混合动作，必须由
    ``core.scrape`` 的单线程 worker 串行执行（并发外呼会被站点限流甚至封禁）。
    """
    def _run():
        try:
            from . import library, scrape
            lid = str((lib or {}).get("id") or "")
            if not lid or not scrape.enabled(lid):
                return
            book = library.find(name, lid)
            if not book:
                # 刚入库的文件可能还没进扫描缓存（TTL 5s），失效一次再看
                library.invalidate(lid)
                book = library.find(name, lid)
            if not book:
                return
            if scrape.enqueue(book, reason="import").get("queued"):
                scrape.start()
                scrape.wake()
        except Exception:                             # noqa: BLE001 —— 旁路增强，绝不外抛
            pass

    _spawn_bg(_run, "novelforge-scrape-enqueue")


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
        # ignore 默认值来自 config.DEFAULTS["watcher"]["ignore"]，这里不再重复定义
        self.ignore = list(w.get("ignore") or [])

        self.state_file = Path(
            kw.get("state_file") or config.CACHE_DIR / STATE_FILENAME
        )
        self.state: dict = self._load_state()
        # 收书目录「忽略」的运行时名单（持久化在 state 的保留键下，见 add_ignore）
        self._ignore_names: set = set(self.state.get("__ignored__") or [])

        #: 每轮扫描结束后的回调（由 server 注入 core.bootdock.note_scan）。
        #: 刻意用回调而不是 import —— core 内部不互相依赖，watcher 不认识 dock。
        self.on_scan = None

        self._lock = threading.Lock()       # 仅保护 state 字典的短临界区
        self._scan_lock = threading.Lock()  # 串行化扫描轮次，避免并行重复处理
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # 已「首轮」过的扫描目标集合（逐个目标独立判定历史存量是否处理）
        self._primed: set = set()
        self.last_scan = 0.0
        # 主循环 tick 间隔（秒）：短间隔轮询，各目标按自己的 interval/cron 决定是否真扫
        self.tick_interval = float(self.interval)
        # 各扫描目标的上次实际扫描时刻（按 tkey 分桶，避免跨目标互相干扰）
        self._target_last: dict = {}
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

    def _target(self, src: Path):
        """该来源条目应落进哪个库：返回 ``(库实体 | None, 库根)``。

        归库判据在 ``core/library_rules.py``（**来源子目录名 > 格式 > 关键词**）；
        判不出（或没有对应类型的库）时返回 ``(None, 默认库根)`` —— 与改造前一致。

        第 13 期起调用方还用它拿到**库 id**，进而取该库的生效配置
        （投递布局 / 是否转换 / 非 txt 收取都可能逐库不同，见 :mod:`core.lib_settings`）。
        """
        try:
            from . import library_rules  # 延迟导入，避免 core 内部循环依赖
            lib = library_rules.decide_for_path(src, self.input_dir)
        except Exception:
            lib = None
        if lib:
            return lib, Path(lib.get("root_path") or self.output_dir)
        return None, self.output_dir

    def target_root(self, src: Path) -> Path:
        """该来源条目应落进**哪个库根**（多书库）。兼容薄壳 —— 需要库实体时用 :meth:`_target`。"""
        return self._target(src)[1]

    def _sig(self, p: Path) -> tuple:
        """条目指纹 ``(size, mtime)``。

        **目录**（有声书）递归汇总内部文件：往里加一集必须让指纹变化，
        否则会出现「已入库但列表还是旧的」。
        """
        try:
            if p.is_dir():
                total, newest = 0, 0.0
                for c in p.rglob("*"):
                    if c.is_file():
                        st = c.stat()
                        total += st.st_size
                        newest = max(newest, st.st_mtime)
                if total == 0:
                    return (0, round(float(p.stat().st_mtime), 3))
                return (int(total), round(float(newest), 3))
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
        if name in self._ignore_names:          # 收书目录「忽略」的条目
            return True
        for pat in self.ignore:
            if fnmatch.fnmatch(name, pat):
                return True
        return False

    def is_ignored(self, p) -> bool:
        """公开的忽略判定（收书目录对账用）。"""
        return self._ignored(Path(p))

    def iter_files(self) -> list:
        """公开的文件枚举（供收书目录对账，替代直接调私有 _iter_files）。"""
        return self._iter_files()

    def add_ignore(self, name: str) -> None:
        """把某个文件名加入**运行时忽略名单**并持久化（收书目录「忽略」操作）。

        与配置里的 ``watcher.ignore``（glob 通配）分开存：那是用户设定的长期规则，
        这是界面上对单个条目的临时决定，混在一起会让「忽略一个文件」变成改配置。
        """
        n = str(name or "").strip()
        if not n:
            return
        with self._lock:
            self._ignore_names.add(n)
            self.state["__ignored__"] = sorted(self._ignore_names)
            self._save_state()

    def _iter_files(self, root=None):
        root = root or self.input_dir
        if not root.is_dir():
            return []
        it = root.rglob("*") if self.recursive else root.iterdir()
        try:
            return [p for p in it if p.is_file()]
        except Exception:
            return []

    def _iter_entries(self, root=None):
        """待处理条目：文件 + **含音频的目录**（有声书，整目录算一本书）。

        与 `_iter_files`（收书目录对账仍只用文件）分开，避免让收书目录去登记目录。
        递归模式下若目录本身已是音频目录，则**不再单独处理它内部的音频文件**，
        否则同一本书会被复制两次。
        """
        root = root or self.input_dir
        try:
            entries = [p for p in self._iter_files(root)
                       if not p.name.startswith(".")]
            if root.is_dir():
                it = root.rglob("*") if self.recursive else root.iterdir()
                for p in it:
                    if p.is_dir() and not p.name.startswith(".") and audio.is_audio_dir(p):
                        entries.append(p)
        except Exception:
            return []
        # 只保留最外层的音频目录，并剔除落在其中的文件
        dirs = [d for d in entries if d.is_dir()]
        keep = [d for d in dirs if not any(o is not d and o in d.parents for o in dirs)]
        out = []
        for p in entries:
            if p.is_dir():
                if p in keep:
                    out.append(p)
            elif not any(d in p.parents for d in keep):
                out.append(p)
        return out

    def _wait_stable(self, p: Path) -> bool:
        """连续 stable_rounds 次读到相同大小才认为写入完成（目录按内部总量计）。"""
        last = -1
        for _ in range(self.stable_rounds + 1):
            sig = self._sig(p)
            if not sig:
                return False
            size = sig[0]
            if size == last:
                return True
            last = size
            if self._stop.wait(self.settle_seconds):
                return False
        return False

    # ---------------- 处理 ----------------

    def _opts(self, cfg: dict = None) -> dict:
        c = cfg if cfg is not None else self.cfg
        return {
            "traditionalize": bool((c or {}).get("traditionalize", False)),
            "force": True,      # 内容有变化就重转，保证 output 是最新
            "merge": True,
            "cfg": c,
        }

    def handle_file(self, p: Path, owner_lib=None) -> tuple:
        """处理单个文件，返回 (结果类型, 详情)。结果类型：converted / added / failed / skipped

        ``owner_lib`` 非空 = 该文件来自某库**专属来源子目录**的扫描，直接归到该库
        （跳过来源子目录名路由，避免又被按格式/关键词改派到别的库）；为 ``None``
        时走既有 ``_target`` 路由（全局 INPUT_DIR 路径）。
        """
        try:
            size = p.stat().st_size
        except OSError as e:
            return ("failed", str(e))
        if size == 0:
            return ("skipped", "空文件")

        t0 = time.time()
        dur = lambda: int((time.time() - t0) * 1000)

        # 第 13 期「每库覆盖」：先定目标库，再取**该库**的生效配置。
        # 库没覆写过时 `config_for` 就是全局值 → 行为与改造前逐字段一致。
        if owner_lib is not None:
            lib = owner_lib
            root = Path(lib.get("root_path") or self.output_dir)
        else:
            lib, root = self._target(p)
        cfg = lib_settings.config_for((lib or {}).get("id") or None)
        layout = str((cfg.get("output") or {}).get("layout") or "flat").strip().lower()
        # 非 txt 是否原样收取：按库取值，取不到时回落到构造时的全局判定
        copy_non_txt = bool((cfg.get("watcher") or {}).get("copy_non_txt", self.copy_non_txt))
        from . import library_rules  # 延迟导入：与 _target 同理，避免 core 内循环依赖

        if p.is_dir():
            # 有声书目录：整树复制为一本书目目录（名字不带扩展名）
            if not audio.is_audio_dir(p):
                return ("skipped", "非音频目录")
            try:
                root.mkdir(parents=True, exist_ok=True)
                series, index = komga.infer(p.name)
                rel = komga.relpath_for_dir(p.name, series, index, layout)
                # 跨库同名闸门（有声书目录是 watcher 自己实现的复制，不经 pipeline.dispatch）
                library_rules.guard_conflict(root, rel)
                dst = root / rel
                if dst.resolve() == p.resolve():     # 就地库：来源即存储，无需复制
                    activity_log.log_add_ok(p.name, rel, size=self._sig(p)[0],
                                            duration_ms=dur(), source="watcher")
                    return ("added", str(dst))
                pipeline._copy_tree(p, dst)
                activity_log.log_add_ok(p.name, rel, size=self._sig(p)[0],
                                        duration_ms=dur(), source="watcher")
                return ("added", str(dst))
            except Exception as e:
                activity_log.log_add_fail(p.name, f"{type(e).__name__}: {e}", size=0, source="watcher")
                return ("failed", str(e))

        if p.suffix.lower() == ".txt":
            try:
                opts = self._opts(cfg)
                # 转换产物也落**目标库根**（原来固定写默认库根，绕过了归库规则：
                # 投到 libraries/ebooks/ 的 txt 会被转进默认库，与「按子目录名归库」相矛盾）
                out = pipeline.convert_txt(p, root, opts)
                activity_log.log_convert_ok(
                    p.name, Path(out).name, size=size, duration_ms=dur(),
                    source="watcher", detail=opts.get("_notice", ""),
                )
                auto_fetch_async(Path(out).name, cfg)
                enqueue_scrape_async(Path(out).name, lib, cfg)
                return ("converted", str(out))
            except Exception as e:
                activity_log.log_convert_fail(
                    p.name, f"{type(e).__name__}: {e}", size=size, duration_ms=dur(), source="watcher"
                )
                return ("failed", str(e))

        if not copy_non_txt:
            return ("skipped", "非 txt 且已关闭 copy_non_txt")

        try:
            root.mkdir(parents=True, exist_ok=True)
            # ⚠️ 复制路径**也要遵循 output.layout**：第 4 期只改了 `pipeline.dispatch`，
            # 而 watcher 这条复制是自己实现的，于是「开了 Komga 布局却只有转换产物进系列目录」。
            # 系列只能从文件名推断 —— 复制进来的书没经过 OPF 解析。
            series, index = komga.infer(p.stem)
            rel = komga.relpath_for(p.stem, p.suffix.lstrip("."), series, index, layout)
            # 跨库同名闸门（复制分支同样是自己实现的，见上一段注释）
            library_rules.guard_conflict(root, rel)
            dst = root / rel
            if dst.resolve() == p.resolve():     # 就地库：来源即存储，无需复制
                activity_log.log_add_ok(p.name, rel, size=size, duration_ms=dur(), source="watcher")
                auto_fetch_async(rel, cfg)
                enqueue_scrape_async(rel, lib, cfg)
                return ("added", str(dst))
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)
            activity_log.log_add_ok(p.name, rel, size=size, duration_ms=dur(), source="watcher")
            auto_fetch_async(rel, cfg)
            enqueue_scrape_async(rel, lib, cfg)
            return ("added", str(dst))
        except Exception as e:
            activity_log.log_add_fail(p.name, f"{type(e).__name__}: {e}", size=size, source="watcher")
            return ("failed", str(e))

    def _emit(self, result: dict) -> dict:
        """把本轮结果交给 on_scan 回调（收书目录状态机），回调异常一律吞掉。"""
        cb = self.on_scan
        if cb is not None:
            try:
                cb(result)
            except Exception:
                pass
        return result

    def scan_once(self) -> dict:
        """立即扫描全局 INPUT_DIR 一轮（手动 /api/scan 用，向后兼容）。"""
        with self._scan_lock:
            return self._scan_locked(self.input_dir, owner_lib=None,
                                     tkey="input", library_id=None)

    def _state_key(self, p: Path, root: Path) -> str:
        """state 字典的键：相对扫描根的路径（按根分桶，避免多目标互相覆盖）。"""
        try:
            return str(p.relative_to(root))
        except Exception:
            return p.name

    def _scan_locked(self, root, owner_lib=None, tkey="input", library_id=None) -> dict:
        root.mkdir(parents=True, exist_ok=True)

        entries = self._iter_entries(root)
        if tkey not in self._primed:               # 首轮：决定是否处理历史存量文件
            self._primed.add(tkey)
            if not self.process_existing:
                with self._lock:
                    for p in entries:
                        if self._ignored(p):
                            continue
                        sig = self._sig(p)
                        if sig:
                            self.state[self._state_key(p, root)] = {
                                "size": sig[0], "mtime": sig[1], "failed": 0,
                            }
                    self._save_state()
                self._target_last[tkey] = time.time()
                return self._emit({"scanned": 0, "converted": [], "added": [],
                                   "failed": [], "skipped": 0})

        # 在短临界区内收集「待处理」文件，转换 I/O 移到锁外执行，
        # 避免 handle_file（可能耗时数十秒）长时间持有 _lock 而冻结其它调用方。
        pending = []
        with self._lock:
            for p in sorted(entries):
                if self._stop.is_set():
                    break
                if self._ignored(p):
                    continue
                key = self._state_key(p, root)
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
                pending.append((p, key, cur))

        result = {"scanned": 0, "converted": [], "added": [], "failed": [], "skipped": 0}
        dirty = False

        for p, key, cur in pending:
            if self._stop.is_set():
                break
            if not self._wait_stable(p):          # 还在写入，下轮再处理
                continue

            result["scanned"] += 1
            kind, detail = self.handle_file(p, owner_lib=owner_lib)   # 锁外执行 I/O / 转换
            with self._lock:                      # 仅短临界区更新 state
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

        with self._lock:
            if dirty:
                self._save_state()
            self.stats["scans"] += 1
            self.last_scan = time.time()
            self._target_last[tkey] = time.time()
        # LAST SCAN 回写：每库目标的来源子目录扫完后记到该库（全局 INPUT_DIR 无库，跳过）
        if library_id:
            try:
                from . import db as _db
                note = f"扫描 {result['scanned']} 项" if result["scanned"] else "无新文件"
                _db.set_library_scan(library_id, note)
            except Exception:
                pass
        return self._emit(result)

    # ---------------- 多目标调度（第 17 期 T2）----------------
    # 监听对象从一个全局 INPUT_DIR 扩展为「N 个来源目录」：
    #   · 全局 INPUT_DIR（library_id=None）行为完全不变（格式/关键词路由）；
    #   · 每个库的 LIBRARY_SOURCE_DIR/<source_subdir> 作为独立目标，带该库自己的
    #     watch / scan_interval / scan_cron；关掉的库不扫、设 cron 的库只在定时窗口扫。
    # 目标在每个 tick 轻量重读 libraries() 派生 —— 增 / 删 / 改库即时热重载。

    def _derive_targets(self) -> list:
        wcfg = (self.cfg or {}).get("watcher", {}) or {}
        global_interval = float(self.interval)
        global_enabled = bool(wcfg.get("enabled", True))
        targets = [{
            "root": self.input_dir, "library_id": None, "watch": global_enabled,
            "interval": global_interval, "cron": None, "tkey": "input", "name": "input",
            "owner_lib": None,
        }]
        try:
            from . import library as _lib
            for l in _lib.libraries():
                sub = (l.get("source_subdir") or "").strip()
                if not sub:
                    continue
                root = config.LIBRARY_SOURCE_DIR / sub
                try:
                    watch = int(l.get("watch", 1) or 0)
                except (TypeError, ValueError):
                    watch = 1
                interval = float(l.get("scan_interval") or 0) or global_interval
                cron = (l.get("scan_cron") or "").strip() or None
                targets.append({
                    "root": root, "library_id": str(l.get("id")), "watch": bool(watch),
                    "interval": interval, "cron": cron,
                    "tkey": "lib:" + str(l.get("id")), "name": l.get("name"),
                    "owner_lib": l,
                })
        except Exception:
            pass
        return targets

    def _should_scan(self, t: dict) -> bool:
        now = time.time()
        last = self._target_last.get(t["tkey"], 0)
        if t["cron"]:
            try:
                from datetime import datetime
                from croniter import croniter
                # 最近一次 cron 触发晚于上次扫描 → 该扫一轮；
                # 坏表达式走 except，退化成 interval 行为，绝不拖垮线程。
                prev = croniter(t["cron"], datetime.fromtimestamp(now)).get_prev(datetime)
                return prev.timestamp() > last
            except Exception:
                return (now - last) >= t["interval"]
        return (now - last) >= t["interval"]

    def _scan_target(self, t: dict) -> None:
        with self._scan_lock:
            self._scan_locked(t["root"], owner_lib=t.get("owner_lib"),
                              tkey=t["tkey"], library_id=t.get("library_id"))

    def scan_library_now(self, lid) -> bool:
        """立即扫描某库的来源子目录（忽略间隔/cron），供 /api/libraries/{lid}/scan。"""
        for t in self._derive_targets():
            if t.get("library_id") == str(lid):
                self._scan_target(t)
                return True
        return False

    # ---------------- 线程控制 ----------------

    def _loop(self):
        while not self._stop.wait(self.tick_interval):
            try:
                for t in self._derive_targets():
                    if self._stop.is_set():
                        break
                    if not t["watch"]:
                        continue
                    if self._should_scan(t):
                        self._scan_target(t)
            except Exception:                     # 单轮异常不能让监听线程死掉
                time.sleep(self.tick_interval)

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
            # 转换是同步 I/O，无法被中断；给足时间让其自然结束。
            # 超时后线程仍可能短暂存活（daemon），但 WATCHER 已置空、不会再被复用，
            # 且 state 锁已缩小范围，不会再阻塞 Web 服务的 mark 操作。
            t.join(timeout=max(self.interval + 5, 30))
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
        targets = []
        for t in self._derive_targets():
            targets.append({
                "root": str(t["root"]), "library_id": t["library_id"],
                "watch": t["watch"], "interval": t["interval"], "cron": t["cron"],
                "name": t.get("name"),
            })
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
            "targets": targets,
        }


def build_watcher(cfg: dict | None = None, **kw) -> FolderWatcher:
    """按配置构造监听器的便捷入口。"""
    return FolderWatcher(cfg=cfg, **kw)
