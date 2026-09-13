import argparse
import asyncio
import json
import pathlib

from .core import pipeline
from . import config
from .sources import DownloadManager


def _load_cfg():
    config.ensure_dirs()
    return config.load_config()


def cmd_convert(args):
    cfg = _load_cfg()
    out = pathlib.Path(args.output) if args.output else config.OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)

    if args.test_title:
        from .core import detect

        ok = any(p.search(args.test_title) for p in detect.CHAPTER_PATTERNS)
        print(f"匹配: {ok}  ->  {args.test_title}")
        return

    opts = {"traditionalize": args.traditionalize, "force": args.force,
            "merge": args.merge, "cfg": cfg}
    src = pathlib.Path(args.input) if args.input else config.INPUT_DIR
    if src.is_dir():
        for f in sorted(src.iterdir()):
            if f.suffix.lower() == ".txt":
                pipeline.dispatch(f, out, opts)
    else:
        pipeline.dispatch(src, out, opts)


async def cmd_search(args):
    cfg = _load_cfg()
    mgr = DownloadManager(cfg)
    results = await mgr.search(args.title)
    print(f"共 {len(results)} 条结果：")
    for i, it in enumerate(results):
        print(f"[{i}] ({it.get('_source')}) {it.get('title')} — {it.get('author')}")


async def cmd_download(args):
    cfg = _load_cfg()
    if not cfg.get("download", {}).get("enabled"):
        print("download 未开启（见 config.yaml 的 download.enabled）")
        return
    mgr = DownloadManager(cfg)
    if args.item:
        item = json.loads(args.item)
    else:
        item = {"_source": args.source, "url": args.url,
                "title": args.title or "book", "author": args.author or "未知",
                "formats": {}}
    result = await mgr.fetch_and_convert(item, config.OUTPUT_DIR,
                                        {"force": True, "merge": True, "cfg": cfg})
    print(f"已生成：{result}")


async def cmd_update(args):
    cfg = _load_cfg()
    mgr = DownloadManager(cfg)
    result = await mgr.update(pathlib.Path(args.txt), {"force": True, "merge": True, "cfg": cfg})
    print(f"已更新：{result}")


def main():
    ap = argparse.ArgumentParser(
        prog="novelforge", description="TXT 小说转 EPUB（输入 / 导出目录分离）"
    )
    sub = ap.add_subparsers(dest="cmd")

    # convert（默认）
    pc = sub.add_parser("convert", help="转换本地 txt（默认动作）")
    pc.add_argument("input", nargs="?", default=None,
                    help="txt 文件或目录；省略时用 INPUT_DIR")
    pc.add_argument("-o", "--output", default=None, help="导出目录；省略时用 OUTPUT_DIR")
    pc.add_argument("-f", "--force", action="store_true", help="覆盖已存在的输出")
    pc.add_argument("-m", "--merge", action="store_true", help="合并过小的章节")
    pc.add_argument("--traditionalize", action="store_true", help="繁体转简体")
    pc.add_argument("-t", "--test-title", help="测试某标题是否能被正则识别（调试用）")

    # search
    ps = sub.add_parser("search", help="跨书源搜索（需开启 download）")
    ps.add_argument("title", help="书名关键词")

    # download
    pd = sub.add_parser("download", help="下载书源条目并转 EPUB")
    pd.add_argument("--source", help="书源名（如 gutenberg）")
    pd.add_argument("--url", help="书籍/目录页 URL")
    pd.add_argument("--title", help="书名（用于命名）")
    pd.add_argument("--author", help="作者")
    pd.add_argument("--item", help="直接传入搜索结果 JSON（含 _source）")

    # update
    pu = sub.add_parser("update", help="增量更新本地 txt（需先经 download 生成 sidecar）")
    pu.add_argument("txt", help="本地 txt 路径")

    args = ap.parse_args()
    cmd = args.cmd or "convert"
    if cmd in ("search", "download", "update"):
        asyncio.run(globals()[f"cmd_{cmd}"](args))
    else:
        cmd_convert(args)


if __name__ == "__main__":
    main()
