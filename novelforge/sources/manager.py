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

    def _visible_sources(self):
        for name, cls in REGISTRY.items():
            if self.public_only and not getattr(cls, "public", True):
                continue
            yield name, cls

    async def search(self, title: str) -> list[dict]:
        """跨全部已注册书源搜索（含用户添加的非公版源；搜索是只读操作，不做 public 过滤）。"""
        out = []
        for name, cls in REGISTRY.items():
            src = cls()
            try:
                async with self._client(src) as c:
                    items = await src.search(c, title) or []
                for it in items:
                    it["_source"] = name
                    it.setdefault("source_name", getattr(cls, "display_name", name))
                out.extend(items)
            except Exception as e:  # 单源失败不影响其它源
                logger.warning("书源 %s 搜索失败: %s", name, e)
        return out

    async def fetch_and_convert(self, item: dict, out_dir: Path, opts: dict) -> Path:
        name = item.get("_source")
        cls = REGISTRY.get(name)
        if not cls:
            raise ValueError(f"未知书源: {name}")
        src = cls()
        async with self._client(src) as c:
            text = await src.fetch_book(c, item)
        opts = dict(opts)
        opts.setdefault("cfg", self.cfg)
        opts.setdefault("filename", item.get("title", "book"))
        meta = {"title": item.get("title", "未命名"), "author": item.get("author", "未知")}
        return pipeline.convert_text(text, Path(out_dir), opts, meta=meta)

    async def download_to(self, item: dict, out_dir: Path, input_dir: Path, opts: dict) -> Path:
        """下载整本书 → 落 txt 到输入目录（留档/可重转）→ 按书源分章方案转 EPUB 到导出目录。

        - 书源提供结构化章节（目录式）时直接分章，最干净；否则抓全文后走全局检测/正则。
        - 自动写 sidecar 元数据，便于日后增量更新。
        """
        out_dir, input_dir = Path(out_dir), Path(input_dir)
        name = item.get("_source")
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
        opts = dict(opts)
        opts.setdefault("cfg", self.cfg)
        opts.setdefault("filename", safe)

        if chapters:
            txt_path = input_dir / f"{safe}.txt"
            txt_path.write_text(
                "\n\n".join(f"{c['title']}\n{c['body']}" for c in chapters),
                encoding="utf-8",
            )
            self.write_sidecar(txt_path, item, out_dir)
            return pipeline.convert_chapters(chapters, out_dir, opts, meta=meta)
        else:
            txt_path = input_dir / f"{safe}.txt"
            txt_path.write_text(text, encoding="utf-8")
            self.write_sidecar(txt_path, item, out_dir)
            return pipeline.convert_text(text, out_dir, opts, meta=meta)

    async def preview(self, item: dict) -> dict:
        """廉价预览：返回目录标题列表 + 首段样本，供下载前确认。"""
        name = item.get("_source")
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

    def write_sidecar(self, txt_path: Path, item: dict, output_dir: Path):
        """下载完成后为本地 txt 写入 sidecar，供日后 update 使用。"""
        sidecar = Path(txt_path).with_suffix(".meta.json")
        meta = {
            "source": item.get("_source"),
            "url": item.get("url"),
            "formats": item.get("formats", {}),
            "title": item.get("title"),
            "output_dir": str(output_dir),
        }
        sidecar.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
