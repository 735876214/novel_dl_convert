"""下载管理器：统一搜索、按站点抓取全文、转 EPUB，以及增量更新。

对应 denovel「自动更新（指定 txt 自动爬取小说更新内容）」「写扩展脚本即可加站点」。
- search：遍历已注册书源，返回带 _source 标记的候选。
- fetch_and_convert：取全文 → 走本地转换管线 → 成品落导出目录。
- update：读取本地 txt 的 sidecar 元数据，重爬源站只追加新增章节，再重转。
"""
import asyncio
import json
from pathlib import Path

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
        out = []
        for name, cls in self._visible_sources():
            src = cls()
            try:
                async with self._client(src) as c:
                    items = await src.search(c, title) or []
                for it in items:
                    it["_source"] = name
                out.extend(items)
            except Exception as e:  # 单源失败不影响其它源
                print(f"[warn] 书源 {name} 搜索失败: {e}")
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
