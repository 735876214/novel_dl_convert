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

from ..core import network, detect, pipeline
from .base import REGISTRY

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
        self.public_only = dl.get("public_only", True)

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

        两条规则（`config.py` 的默认值就是这两条）：
        - ``download.enabled`` 默认 **False**：关掉时书源仅做规则管理，不搜也不下；
        - ``download.public_only`` 默认 **True**：只放行 ``public`` 源。

        第 71 期之前这段判定散在三处（`store.sources_status` 自算一份、`_visible_sources`
        一份且无人调用、CLI 一份），而 `/api/search` / `/api/download` / `/api/preview`
        谁都不检查 —— 于是设置页写着「关闭时不可搜索下载」，实际照搜照下，真开关成了假开关。
        现在三个端点都问这里，界面显示的原因也是它的原文（措辞只有一份）。

        ``source`` 留空时只判「下载开关」这一层；给了源名再判「仅公版源」那一层。
        **未知源名不在这里拦**：那不是闸门的事，交由调用方按「未知书源」如实报错。

        ``feature`` 是**用途**维度（第 85 期新增；默认 ``"download"`` ⇒ 既有调用方行为一字不变）：
        ``"toc"`` 判的是「从官方书城取目录」那个开关。两个用途**各判各的、不叠加** ——
        关掉下载不影响显式打开了取目录的用户（反之亦然），因为「取一份章节目录」与
        「下载整本正文」是两个动作，理由见 `sources/toc_sources.py` 的模块注释。
        """
        if feature == "toc":
            # 「取目录」是独立开关，也**不受 public_only 约束**：那条管的是下载内容的版权，
            # 而取目录只读一份章节标题，且用户点名要的正是「官方书城」的目录。
            if not bool((self.cfg.get("download") or {}).get("toc_enabled", False)):
                return "取目录未开启：到「设置 → 网络与下载」打开「从官方书城取目录」"
            return ""
        if not self.enabled:
            return "下载功能未开启：到「设置 → 网络与下载」打开「开放搜索 / 下载」"
        if source and self.public_only:
            cls = REGISTRY.get(source)
            if cls is not None and not getattr(cls, "public", True):
                display = getattr(cls, "display_name", source)
                return f"「{display}」不是公版源：已被「仅放行公版源」拦下（设置 → 网络与下载）"
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

    async def download_to(self, item: dict, out_dir: Path, input_dir: Path, opts: dict) -> Path:
        """下载整本书 → 落 txt 到输入目录（留档/可重转）→ 按书源分章方案转 EPUB 到导出目录。

        - 书源提供结构化章节（目录式）时直接分章，最干净；否则抓全文后走全局检测/正则。
        - 自动写 sidecar 元数据，便于日后增量更新。
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
        caller_opts = opts
        opts = dict(opts)
        opts.setdefault("cfg", self.cfg)
        opts.setdefault("filename", safe)

        if chapters:
            txt_path = input_dir / f"{safe}.txt"
            txt_path.write_text(
                "\n\n".join(f"{c['title']}\n{c['body']}" for c in chapters),
                encoding="utf-8",
            )
            self.write_sidecar(txt_path, item, out_dir,
                               last_title=(chapters[-1].get("title") or ""))
            result = pipeline.convert_chapters(chapters, out_dir, opts, meta=meta)
        else:
            txt_path = input_dir / f"{safe}.txt"
            txt_path.write_text(text, encoding="utf-8")
            # 整页全文这条路上没有现成章节表，用与 pipeline 同一套判据现切一次拿末章标题
            # （一次下载只多跑一遍正则，换来「下载完就知道最新章节」这件事不缺席）
            from ..core import detect
            chaps = detect.detect_chapters(text) or []
            self.write_sidecar(txt_path, item, out_dir,
                               last_title=(chaps[-1].get("title") if chaps else ""))
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

    # ---- 增量更新 ----
    async def update(self, txt_path: Path, opts: dict) -> Path:
        txt_path = Path(txt_path)
        sidecar = txt_path.with_suffix(".meta.json")
        if not sidecar.exists():
            raise ValueError(f"未找到 sidecar 元数据 {sidecar.name}，无法增量更新")
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
        cls = REGISTRY.get(meta.get("source"))
        if not cls:
            raise ValueError(f"sidecar 记录的源 {meta.get('source')} 已不存在")
        src = cls()
        async with self._client(src) as c:
            text = await src.fetch_book(c, {"url": meta.get("url"), "formats": meta.get("formats", {})})

        chapters = detect.detect_chapters(text)
        last_title = meta.get("last_title")
        start = 0
        if last_title:
            for i, ch in enumerate(chapters):
                if ch["title"] == last_title:
                    start = i + 1
                    break
        new_body = "\n\n".join(ch["body"] for ch in chapters[start:])
        if not new_body.strip():
            print("[info] 无新增内容")
            return txt_path

        with open(txt_path, "a", encoding="utf-8") as f:
            f.write("\n\n" + new_body)
        opts = dict(opts)
        opts.setdefault("cfg", self.cfg)
        result = pipeline.convert_txt(txt_path, Path(opts.get("output") or meta.get("output_dir") or txt_path.parent), opts)
        # 更新 sidecar 末章
        if chapters:
            meta["last_title"] = chapters[-1]["title"]
            sidecar.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        return result

    def write_sidecar(self, txt_path: Path, item: dict, output_dir: Path,
                      last_title: str = ""):
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
        sidecar.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
