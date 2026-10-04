"""下载管理器：统一搜索、按站点抓取全文、转 EPUB，以及增量更新。

对应 denovel「自动更新（指定 txt 自动爬取小说更新内容）」「写扩展脚本即可加站点」。
- search：遍历已注册书源，返回带 _source 标记的候选。
- fetch_and_convert：取全文 → 走本地转换管线 → 成品落导出目录。
- update：读取本地 txt 的 sidecar 元数据，重爬源站只追加新增章节，再重转。
"""
import asyncio
import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


def _safe_name(s: str) -> str:
    """把书名清洗为安全的文件名（去掉路径分隔与多数特殊字符）。"""
    s = (s or "book").strip()
    s = re.sub(r"[\\/:*?\"<>|]", "_", s)
    return s[:120] or "book"

from ..core import network, detect, pipeline, reading_list
from .base import REGISTRY

#: 追更用的**按路径**互斥锁（第 87 期收尾补）。
#: ⚠️ 为什么必须有：`update_report` 是「读 sidecar → 抓章节 → 读全文 → 写 `.part` → replace」，
#: 两个并发调用各自读到同一份旧内容 ⇒ **后写覆盖前写、丢章**，而且两边都返回「已追加 N 章」——
#: 这类静默丢数据最难查（用户只会发现「少了几章」）。
#: 按**路径**而不是全局加锁：不同书的追更本就该并行，串行化全局会让批量追更慢得离谱。
#: 表按书增长（一本书一个条目、不清理）：条目数 = 追更过的书数，量级很小。
_UPDATE_LOCKS: dict = {}


def update_lock(txt_path) -> asyncio.Lock:
    """取某个留档 txt 的追更锁（同一个路径**永远返回同一个对象**）。"""
    key = str(Path(txt_path))
    lock = _UPDATE_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _UPDATE_LOCKS[key] = lock
    return lock

#: 单源搜索超时（秒，第 71 期）。用模块常量而不是新配置键：这是一次性需求，不值得再扩
#: 一套设置面板 + `config` 白名单（已记入 roadmap 未做项）。超时按**源**算，所以
#: 「一个源卡住」只会让该源记一条超时原因，不会拖垮整轮搜索。
SEARCH_TIMEOUT = 20.0


def source_of(item: dict) -> str:
    """命中条目的书源名（**唯一读法**，第 71 期）。

    历史上这里有两个键：``_source``（manager 自己打的）与 ``source``（前端读的）。
    只认 ``_source`` 会让「外部回传的 item」（如 sidecar 元数据）读不到；
    只认 ``source`` 会让第 71 期之前落盘的 sidecar 失效 —— 所以两个都认，且只在这里认。
    """
    item = item or {}
    return str(item.get("source") or item.get("_source") or "")


class DownloadManager:
    def __init__(self, cfg: dict):
        self.cfg = cfg or {}
        net = self.cfg.get("network", {}) or {}
        self.cookie_dir = net.get("cookie_dir") or str(Path(__import__("os").environ.get("COOKIE_DIR", "/app/config/cookies")))
        self.max_retries = net.get("max_retries", 3)
        host_replace = net.get("host_replace", {}) or {}
        self.host_replace = host_replace
        dl = self.cfg.get("download", {}) or {}
        self.enabled = dl.get("enabled", False)

    def _client(self, source):
        return network.BrowserClient(
            source.name,
            cookie_dir=self.cookie_dir,
            headers=getattr(source, "headers", None),
            host_replace=self.host_replace,
            max_retries=self.max_retries,
        )

    def gate_reason(self, source: str | None = None, feature: str = "download") -> str:
        """下载闸门判定（**唯一一处**，第 71 期）：空串 = 放行，非空 = 可直接展示的原因。

        一条规则（`config.py` 的默认值就是它）：``download.enabled`` 默认 **False** ——
        关掉时书源仅做规则管理，不搜也不下。

        第 71 期之前这段判定散在三处（`store.sources_status` 自算一份、`_visible_sources`
        一份且无人调用、CLI 一份），而 `/api/search` / `/api/download` / `/api/preview`
        谁都不检查 —— 于是设置页写着「关闭时不可搜索下载」，实际照搜照下，真开关成了假开关。
        现在三个端点都问这里，界面显示的原因也是它的原文（措辞只有一份）。

        ``feature`` 是**用途**维度（第 85 期新增；默认 ``"download"`` ⇒ 既有调用方行为一字不变）：
        ``"toc"`` 判的是「从官方书城取目录」那个开关。两个用途**各判各的、不叠加** ——
        关掉下载不影响显式打开了取目录的用户（反之亦然），因为「取一份章节目录」与
        「下载整本正文」是两个动作，理由见 `sources/toc_sources.py` 的模块注释。

        ⚠️ **第 93 期删掉了「仅放行公版源」（`download.public_only`）那一层**（用户拍板）：
        现在**不再按来源的公版 / 非公版过滤**，全部已注册源一视同仁，判定只剩上面那一条。
        ``source`` 形参**保留**（调用方仍按源逐条问原因，签名稳定），但自本期起不参与判定；
        适配器上的 ``public`` 字段降级为**纯标注**（书源列表里的「公版 / 私有」徽章）。
        """
        if feature == "toc":
            # 「取目录」是独立开关：它只读一份章节标题，与「下载整本正文」是两个动作。
            if not bool((self.cfg.get("download") or {}).get("toc_enabled", False)):
                return "取目录未开启：到「设置 → 网络与下载」打开「从官方书城取目录」"
            return ""
        if not self.enabled:
            return "下载功能未开启：到「设置 → 网络与下载」打开「开放搜索 / 下载」"
        return ""

    async def test_source(self, cls, title: str) -> list[dict]:
        """用**给定的书源类**试搜一次（不注册、不落盘）：给「手动添加书源」的自检按钮用。

        与 :meth:`search` 同一条链路（同一个 `BrowserClient` 口径：Cookie 目录 / host_replace /
        重试），差别只有三点：只跑这一类；**失败直接抛出** —— 试搜的目的是把原因如实显示给
        写规则的人看，不能像批量搜索那样静默跳过；**不受 `download.enabled` 闸门限制** ——
        闸门管的是「真的去搜去下」，试搜是「验证规则写得对不对」，一起拦掉的话用户就再也
        没法确认自己写的规则还能不能用（第 71 期取舍，`tests/test_sources_gate.py` 钉住）。
        """
        src = cls()
        async with self._client(src) as c:
            return await src.search(c, title) or []

    async def search(self, title: str, page: int = 1) -> dict:
        """**并发**跨全部已注册书源搜索，返回命中与逐源状态（第 71 期）。

        - ``items``：各源命中的并集，每条经 :meth:`_mark` 打上 ``source`` /
          ``source_name`` / ``_source``。**顺序不表示排名** —— 合并与匹配度排序是展示层的
          事（`frontend/src/lib/searchResults.ts`），后端只负责「列全、别丢、别骗」；
        - ``sources``：逐源状态 ``{name, display_name, ok, count, error, skipped,
          reason, has_more}``。

        第 71 期在这里修掉三件事：
        1. **真并发**：以前是 ``for`` 里逐个 ``await``，而界面写着「正在并发检索各书源」；
        2. **每源超时**：``asyncio.wait_for(..., SEARCH_TIMEOUT)`` —— 规则源的
           ``client.get_text`` 原先连 timeout 都没传，一个慢站能拖住整轮搜索；
        3. **失败原因如实回报**：以前异常只进日志，界面那条「部分书源检索失败」横幅
           永远不显示（后端压根不返回它）。
        """
        page = max(1, int(page or 1))
        entries = list(REGISTRY.items())
        blocked = {name: self.gate_reason(name) for name, _ in entries}
        live = [(n, c) for n, c in entries if not blocked[n]]
        results = await asyncio.gather(
            *(self._search_one(n, c, title, page) for n, c in live)
        )
        found = {row["name"]: (row, items) for row, items in results}

        out_items: list[dict] = []
        out_sources: list[dict] = []
        for name, cls in entries:
            display = getattr(cls, "display_name", name)
            if blocked[name]:
                # 被闸门拦下的源**如实列出原因**，而不是悄悄不搜：否则用户只看到
                # 「结果变少了」，分不清是自己关掉了下载、还是这个源挂了。
                out_sources.append({
                    "name": name, "display_name": display, "ok": False, "count": 0,
                    "error": "", "skipped": True, "reason": blocked[name],
                    "has_more": False,
                })
                continue
            row, items = found[name]
            out_items.extend(items)
            out_sources.append(row)
        return {"items": out_items, "sources": out_sources}

    async def _search_one(self, name: str, cls, title: str, page: int) -> tuple[dict, list[dict]]:
        """跑单个源的一页搜索，返回 ``(状态行, 命中)``。

        任何失败都变成状态行里的**原文原因**（不编造分类、不吞掉）—— 界面要如实显示
        「这个源为什么没结果」，这是它唯一的信息来源。
        """
        display = getattr(cls, "display_name", name)
        base = {"name": name, "display_name": display, "ok": False, "count": 0,
                "skipped": False, "reason": "", "has_more": False}
        try:
            src = cls()
            async with self._client(src) as c:
                res = await asyncio.wait_for(src.search_page(c, title, page), SEARCH_TIMEOUT)
            items = [self._mark(dict(it), name, display) for it in (res.get("items") or [])]
            return ({**base, "ok": True, "count": len(items), "error": "",
                     "has_more": bool(res.get("has_more"))}, items)
        except asyncio.TimeoutError:
            logger.warning("书源 %s 搜索超时（> %ss）", name, SEARCH_TIMEOUT)
            return ({**base, "error": f"搜索超时（单源超过 {SEARCH_TIMEOUT:.0f} 秒）"}, [])
        except Exception as e:  # 单源失败不影响其它源
            logger.warning("书源 %s 搜索失败: %s", name, e)
            return ({**base, "error": f"{e}"}, [])

    @staticmethod
    def _mark(item: dict, name: str, display: str) -> dict:
        """给命中打上来路（**唯一写入处**，第 71 期）。

        - ``source``：前端读的字段。第 71 期之前只写 ``_source`` 而前端读 ``source``，
          后果是结果行的来源徽章空白、点「预览」必然 502「未知书源: undefined」；
        - ``source_name``：展示名；
        - ``_source``：历史键，下载路径与 sidecar 仍在读它（见 :func:`source_of`），保留。
        """
        item["source"] = name
        item.setdefault("source_name", display)
        item["_source"] = name
        return item

    async def fetch_and_convert(self, item: dict, out_dir: Path, opts: dict) -> Path:
        name = source_of(item)
        cls = REGISTRY.get(name)
        if not cls:
            raise ValueError(f"未知书源: {name}")
        src = cls()
        async with self._client(src) as c:
            text = await src.fetch_book(c, item)
        caller_opts = opts
        opts = dict(opts)
        opts.setdefault("cfg", self.cfg)
        opts.setdefault("filename", item.get("title", "book"))
        meta = {"title": item.get("title", "未命名"), "author": item.get("author", "未知")}
        result = pipeline.convert_text(text, Path(out_dir), opts, meta=meta)
        # 回传派生格式的降级提示（供上层写活动日志 / 任务结果）
        caller_opts["_notice"] = opts.get("_notice", "")
        return result

    async def download_to(self, item: dict, out_dir: Path, input_dir: Path, opts: dict,
                          *, txt_stem: str = "") -> Path:
        """下载整本书 → 落 txt 到输入目录（留档/可重转）→ 按书源分章方案转 EPUB 到导出目录。

        - 书源提供结构化章节（目录式）时直接分章，最干净；否则抓全文后走全局检测/正则。
        - 自动写 sidecar 元数据，便于日后增量更新。

        ``txt_stem`` 是**留档 txt / sidecar 的文件名**，默认按书名清洗（``_safe_name``）。
        什么时候必须显式传：**把源站内容落到「已有的那本书」上**时（第 93 期自动落地）——
        那时留档必须叫**那本书**的名字，否则 `autoupdate.sidecar_of`（唯一一处拼法）
        在收书目录里找不到它，追更从此对这本书失效。书名的清洗可能改名（非法字符 / 超长），
        所以不能靠「书名本来就安全」这个假设。
        """
        out_dir, input_dir = Path(out_dir), Path(input_dir)
        name = source_of(item)
        cls = REGISTRY.get(name)
        if not cls:
            raise ValueError(f"未知书源: {name}")
        src = cls()
        meta = {"title": item.get("title", "未命名"), "author": item.get("author", "未知")}

        async with self._client(src) as c:
            chapters = None
            if hasattr(src, "fetch_book_chapters"):
                try:
                    chapters = await src.fetch_book_chapters(c, item)
                except NotImplementedError:
                    chapters = None
            if not chapters:
                text = await src.fetch_book(c, item)

        safe = _safe_name(item.get("title", "book"))
        stem = str(txt_stem or safe)
        caller_opts = opts
        opts = dict(opts)
        opts.setdefault("cfg", self.cfg)
        opts.setdefault("filename", safe)

        # ⚠️ 留档 txt **先写 .part 再 replace**（第 93 期）：重复下载 / 自动覆盖时这个文件
        # 是**已存在**的（它就是追更的起点依据），半截文件会被当成「本地已有这么多章」——
        # 于是下次追更从错误的位置开始，静默丢章。与 `_update_report_locked` 同一手法。
        if chapters:
            body = "\n\n".join(f"{c['title']}\n{c['body']}" for c in chapters)
        else:
            body = str(text)
        txt_path = input_dir / f"{stem}.txt"
        t_tmp = txt_path.with_suffix(txt_path.suffix + ".part")
        t_tmp.write_text(body, encoding="utf-8")
        t_tmp.replace(txt_path)

        if chapters:
            self.write_sidecar(txt_path, item, out_dir,
                               last_title=(chapters[-1].get("title") or ""),
                               chapter_count=len(chapters))
            result = pipeline.convert_chapters(chapters, out_dir, opts, meta=meta)
        else:
            # 整页全文这条路上没有现成章节表，用与 pipeline 同一套判据现切一次拿末章标题
            # （一次下载只多跑一遍正则，换来「下载完就知道最新章节」这件事不缺席）
            from ..core import detect
            chaps = detect.detect_chapters(text) or []
            self.write_sidecar(txt_path, item, out_dir,
                               last_title=(chaps[-1].get("title") if chaps else ""),
                               chapter_count=len(chaps))
            result = pipeline.convert_text(text, out_dir, opts, meta=meta)
        # 回传派生格式的降级提示
        caller_opts["_notice"] = opts.get("_notice", "")
        return result

    async def preview(self, item: dict) -> dict:
        """廉价预览：返回目录标题列表 + 首段样本，供下载前确认。"""
        name = source_of(item)
        cls = REGISTRY.get(name)
        if not cls:
            raise ValueError(f"未知书源: {name}")
        src = cls()
        if not hasattr(src, "preview"):
            async with self._client(src) as c:
                text = await src.fetch_book(c, item)
            from ..core import detect
            chaps = detect.detect_chapters(text)
            return {"toc": [c["title"] for c in chaps[:50]], "sample": text[:1500]}
        async with self._client(src) as c:
            return await src.preview(c, item)

    # ---- 增量更新（追更）----
    async def update_report(self, txt_path: Path, opts: dict) -> dict:
        """追更的**串行化入口**：同一个留档文件同时只允许一次追更。

        实现与全部口径见 :meth:`_update_report_locked`；这里只负责加锁 ——
        没有它，两次并发追更会各自「读旧内容 → 写 `.part` → replace」，
        后写覆盖前写（**静默丢章**，而且两边都报成功）。
        """
        async with update_lock(txt_path):
            return await self._update_report_locked(txt_path, opts)

    async def _update_report_locked(self, txt_path: Path, opts: dict) -> dict:
        """追更：**只追加**，既有条目一字不动（第 86 期第 6 步重写）。

        与旧实现的四处根本差别（前三条都是典型的**静默出错**）：

        1. **起点按「本地已有几章」算**，不再按 `last_title` 找 —— 站点给章名加个「（上）」
           就找不到、`start` 落回 0，于是**把整本再追加一遍**（重复内容，且不报任何错）；
        2. **EPUB 写回走 `epub_update.append_chapters`**（既有条目字节不变），不再「整本重转」——
           重转会让既有章节的 index 漂移，**进度与批注全部错位**；
        3. **txt 留档带标题**（旧实现只写 `body`，留档从此回溯不了章名）；
        4. 写 txt / 写 sidecar 改成**读全文 + 原子替换**（旧实现裸 `open(..., "a")` append，
           中途失败会留下半行）。

        返回一份**如实报告**（调用方据此显示「新增 N 章 / 源上少了 N 章」）：
        ``{"path", "added", "skipped", "missing", "epub", "note"}``。

        ⚠️ **只追加**：源上少了章（`missing`）只报告、绝不删本地已有的章；站点改了老章内容本期
        也不覆盖（要覆盖得先存「老章内容基线」，属后续项）。
        """
        def _to_html(ch: dict) -> str:
            """章节正文档 → XHTML 片段：源给了 HTML 就用，否则按纯文本转义分段。

            ⚠️ 纯文本那半**不在本地实现**：与在线阅读共用
            :func:`core.reading_list.text_to_xhtml`（第 93 期收敛 —— 两处各写一份
            「逐行 escape 包 `<p>`」时，改了一处忘了另一处就会一条路安全、另一条路漏标记）。
            """
            html = str(ch.get("body_html") or "").strip()
            if html:
                return html
            return reading_list.text_to_xhtml(ch.get("body"))

        txt_path = Path(txt_path)
        sidecar = txt_path.with_suffix(".meta.json")
        if not sidecar.exists():
            raise ValueError(f"未找到 sidecar 元数据 {sidecar.name}，无法增量更新")
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
        cls = REGISTRY.get(meta.get("source"))
        if not cls:
            raise ValueError(f"sidecar 记录的源 {meta.get('source')} 已不存在")
        src = cls()
        item = {"url": meta.get("url"), "formats": meta.get("formats", {}),
                "title": meta.get("title")}
        async with self._client(src) as c:
            chapters = None
            if hasattr(src, "fetch_book_chapters"):
                try:
                    chapters = await src.fetch_book_chapters(c, item)
                except NotImplementedError:
                    chapters = None
            if not chapters:
                text = await src.fetch_book(c, item)
                from ..core import detect
                chapters = detect.detect_chapters(text) or []

        known = int(meta.get("chapters") or 0)
        report = {"path": txt_path, "added": 0, "skipped": 0, "missing": 0, "epub": "",
                  "note": ""}
        if len(chapters) < known:
            report["missing"] = known - len(chapters)
            report["note"] = (f"源上比本地少 {report['missing']} 章：追更**只追加**，"
                              "绝不删本地已有的章（请自行确认是不是站点改版）")
        fresh = chapters[known:]
        if not fresh:
            report["note"] = report["note"] or "没有新章节"
            return report

        # ① txt 留档：读全文 + 追加带标题的新章 + **原子替换**（不再裸 append）
        try:
            old = txt_path.read_text(encoding="utf-8") if txt_path.exists() else ""
        except Exception:                                    # noqa: BLE001 —— 读不到当空
            old = ""
        add_txt = "\n\n".join(f"{ch.get('title', '')}\n{ch.get('body', '')}" for ch in fresh)
        t_tmp = txt_path.with_suffix(txt_path.suffix + ".part")
        t_tmp.write_text((old.rstrip() + "\n\n" + add_txt).strip() + "\n", encoding="utf-8")
        t_tmp.replace(txt_path)

        # ② EPUB：**只追加**（既有条目字节不变 ⇒ 阅读数据 index 不漂移）
        out_dir = Path(meta.get("output_dir") or txt_path.parent)
        epub_path = out_dir / f"{txt_path.stem}.epub"
        if epub_path.is_file():
            from ..core import epub_update
            res = epub_update.append_chapters(
                epub_path, [{"title": ch.get("title", ""), "body_html": _to_html(ch)}
                            for ch in fresh])
            report["epub"] = str(res["path"])
        else:
            report["note"] = report["note"] or f"没找到同名 EPUB（{epub_path.name}），本次只留档 txt"

        # ③ sidecar：更新到「本地现在有多少章」（原子写）
        meta["chapters"] = len(chapters)
        if chapters:
            meta["last_title"] = chapters[-1].get("title") or ""
        s_tmp = sidecar.with_suffix(sidecar.suffix + ".part")
        s_tmp.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        s_tmp.replace(sidecar)
        report["added"] = len(fresh)
        return report

    async def update(self, txt_path: Path, opts: dict) -> Path:
        """兼容壳：旧调用方拿的是 ``Path``；要报告请用 :meth:`update_report`。"""
        return (await self.update_report(txt_path, opts))["path"]
        # ⚠️ 第 86 期重写时，这里曾留着一整段**永不执行**的旧实现（`return` 之后）：
        #    裸 `open(txt_path, "a")` 追加 + `pipeline.convert_txt` 整本重转。
        #    死代码本身无害，但它**看起来像是可以「恢复」的备选路径** —— 而它正好是
        #    「重复内容 + index 漂移」那两条静默错误的正身（见 `update_report` 的说明），
        #    所以第 87 期收尾时**删掉**，不留这个念想。

    async def download_audio(self, item: dict, out_dir, opts: dict = None) -> Path:
        """有声书：逐轨取字节 → 落成**目录型有声书**（一本 = 一个目录，第 86 期）。

        三条口径（与 `download_comic` 同理，差别在产物形态）：

        · **轨名必须用 `units` 认得的序号词**（`第N话`）—— 判据在 `units.UNIT_WORDS`，
          换个名字（如 `track_1.mp3`）书架看到的就不是「一本书」而是**一堆散装音频**；
          `N` 上限取 `units._MAX_UNIT`（999）：超过这个数的编号 `units` 不认，编了也白编；
        · **轨序 = 站点给的顺序**（音频没有页序那种可读顺序，站点顺序就是唯一依据）；
        · **轨清单为空就报错**，且**失败不留半个目录**（空目录在书架上是一条点开什么都没有的书）。
        """
        from ..core import audio as audio_mod      # 延迟导入：core 不在模块级反向依赖 sources
        from ..core import units
        name = source_of(item)
        cls = REGISTRY.get(name)
        if not cls:
            raise ValueError(f"未知书源: {name}")
        src = cls()
        dest = Path(out_dir) / _safe_name(item.get("title", "audio"))
        created = not dest.exists()
        try:
            async with self._client(src) as c:
                urls = await src.fetch_media_urls(c, item, "audio") \
                    if hasattr(src, "fetch_media_urls") else []
                if not urls:
                    raise ValueError("这条书源的规则没有给出任何音频地址"
                                     "（缺 book.audio，或站点结构变了 / 需要两层跳转）")
                dest.mkdir(parents=True, exist_ok=True)
                for i, u in enumerate(urls[:units._MAX_UNIT], start=1):
                    data = await c.get_bytes(u)
                    ext = Path(str(u).split("?")[0]).suffix.lower()
                    if ext not in audio_mod.AUDIO_EXTS:
                        ext = ".mp3"              # 站点常给 `/audio?id=1` 这种没有扩展名的地址
                    (dest / f"第{i}话{ext}").write_bytes(data)
        except Exception:
            if created:                           # 只清理**本次新建**的目录，不动已有产物
                import shutil
                shutil.rmtree(dest, ignore_errors=True)
            raise
        return dest

    async def append_audio(self, client, dest_dir, urls) -> dict:
        """把新轨**追加**到目录型有声书末尾（第 86 期追更；既有文件一字不动）。

        调用方**传已有的 client**（跟取轨用同一个：Cookie / host_replace / 重试口径一致）。

        · 轨名续着**既有最大话号**：`第N话<ext>`（必须是 `units` 认得的写法 —— 否则书架
          看到的就不是一本书，而是一堆散装音频）；撞名一律跳号，**绝不覆盖既有轨**；
        · 每轨**先写 `.part` 再 `Path.replace`**：写一半的音频会被当成「这一话是坏的」，
          而重下要重跑整轮 —— 这类半成品比没有更糟；
        · 返回 ``{"dir", "added", "start"}``（`added` 只列**本次新增**的名字）。
        """
        from ..core import audio as audio_mod
        from ..core import units
        dest = Path(dest_dir)
        urls = list(urls or [])
        if not urls:
            return {"dir": dest, "added": [], "start": None}
        names = {p.name for p in dest.iterdir()} if dest.is_dir() else set()
        nums = [x for x in (units.parse_unit(Path(n).stem) for n in names) if x]
        n = (max(nums) + 1) if nums else 1
        start, added = n, []
        dest.mkdir(parents=True, exist_ok=True)
        for u in urls:
            ext = Path(str(u).split("?")[0]).suffix.lower()
            if ext not in audio_mod.AUDIO_EXTS:
                ext = ".mp3"                     # 站点常给没有扩展名的地址
            while f"第{n}话{ext}" in names:
                n += 1                            # 撞名跳号：绝不覆盖既有轨
            name = f"第{n}话{ext}"
            tmp = dest / (name + ".part")
            tmp.write_bytes(await client.get_bytes(u))
            tmp.replace(dest / name)
            names.add(name)
            added.append(name)
            n += 1
        return {"dir": dest, "added": added, "start": start}

    async def download_comic(self, item: dict, out_dir, opts: dict = None) -> Path:
        """漫画：从书源取页清单 → 逐页取**字节** → 打成 CBZ 落本地（第 86 期）。

        ⚠️ 三条不许破的口径：
        · 逐页必须走 `get_bytes`（走 `get_text` 会把图片按文本编码解一遍，字节就变了）；
        · 页序**按站点给的顺序**写进归档（阅读顺序），只在扩展名不可信时兜底成 `.jpg`；
        · **页清单为空就报错**，不产出一个「0 页的 CBZ」—— 那在书架上是一本打不开的假漫画。
        """
        from ..core import comics                     # 延迟导入：core 不在模块级反向依赖 sources
        name = source_of(item)
        cls = REGISTRY.get(name)
        if not cls:
            raise ValueError(f"未知书源: {name}")
        src = cls()
        async with self._client(src) as c:
            urls = await src.fetch_media_urls(c, item, "comic") if hasattr(src, "fetch_media_urls") else []
            if not urls:
                raise ValueError("这条书源的规则没有给出任何图片地址"
                                 "（缺 book.comic，或站点结构变了 / 需要两层跳转）")
            pages = []
            for i, u in enumerate(urls):
                data = await c.get_bytes(u)
                ext = Path(str(u).split("?")[0]).suffix.lower()
                if ext not in comics.IMAGE_EXTS:
                    ext = ".jpg"                      # 站点常给 `/img?id=1` 这种没有扩展名的地址
                pages.append((f"{i + 1:04d}{ext}", data))
        dest = Path(out_dir) / f"{_safe_name(item.get('title', 'comic'))}.cbz"
        return comics.write_cbz(dest, pages)

    def write_sidecar(self, txt_path: Path, item: dict, output_dir: Path,
                      last_title: str = "", chapter_count: int = 0):
        """下载完成后为本地 txt 写入 sidecar，供日后 update 使用。

        ⚠️ **`last_title`（最新章节）必须在这里就写下来**：产品承诺是「下载后就能看出这本书
        来自哪个源、最新章节是哪一章」，而 `update()` 是**下一次抓取**时才回写的 ——
        中间这段时间 sidecar 里没有它，界面与用户看到的就只有一句「不知道」。
        """
        sidecar = Path(txt_path).with_suffix(".meta.json")
        meta = {
            "source": source_of(item),
            "url": item.get("url"),
            "formats": item.get("formats", {}),
            "title": item.get("title"),
            "output_dir": str(output_dir),
        }
        if last_title:
            meta["last_title"] = str(last_title)
        # ⚠️ 记下**本地已有几章**：追更要靠它决定「源上第几章之后是新的」（第 86 期）。
        # 旧实现是按 `last_title` 找起点 —— 站点一改章名（加个「（上）」）就会静默错位，
        # 把已经读过的章当新章再追加一遍，而**不报任何错**。
        if chapter_count:
            meta["chapters"] = int(chapter_count)
        sidecar.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
