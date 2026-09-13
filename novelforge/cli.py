import argparse
import asyncio
import json
import logging
import pathlib

from .core import pipeline, activity_log, watcher as watcher_mod
from . import config
from .sources import DownloadManager


def _load_cfg():
    config.ensure_dirs()
    cfg = config.load_config()
    d = (cfg.get("logging") or {}).get("dir")
    if d:
        activity_log.set_dir(d)
    return cfg


def _setup_logging(verbose: bool = True):
    """让活动日志同步打到终端（watch / scan 时有用）。"""
    if not verbose:
        return
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
    lg = logging.getLogger("novelforge.activity")
    lg.setLevel(logging.INFO)
    lg.handlers = [h]
    lg.propagate = False


def _print_summary(res: dict):
    for it in res.get("converted", []):
        print(f"  转换成功：{it['file']} → {it['output']}")
    for it in res.get("added", []):
        print(f"  添加成功：{it['file']} → {it['output']}")
    for it in res.get("failed", []):
        print(f"  失败：{it['file']}（{it['error']}）")
    print(f"本轮：转换 {len(res.get('converted', []))} / 添加 {len(res.get('added', []))} / "
          f"失败 {len(res.get('failed', []))}")


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


def cmd_watch(args):
    """持续监听输入目录，也可 --once 只跑一轮。"""
    cfg = _load_cfg()
    _setup_logging(True)
    kw = {}
    if args.interval:
        kw["interval"] = args.interval
    if args.recursive:
        kw["recursive"] = True
    w = watcher_mod.FolderWatcher(cfg=cfg, **kw)
    if args.once:
        print(f"扫描一次：{w.input_dir} → {w.output_dir}")
        _print_summary(w.scan_once())
        return
    print(f"监听中：{w.input_dir} → {w.output_dir}（间隔 {w.interval}s，Ctrl+C 停止）")
    w.run_forever()


def cmd_logs(args):
    """查看活动日志。"""
    cfg = _load_cfg()
    d = (cfg.get("logging") or {}).get("dir")
    if d:
        activity_log.set_dir(d)
    items = activity_log.recent(limit=args.limit, action=args.action or "",
                                status=args.status or "", q=args.q or "")
    if not items:
        print(f"（暂无日志，目录：{activity_log.log_dir()}）")
        return
    for e in reversed(items):      # 旧 → 新，符合 tail 习惯
        out = f" → {e['output']}" if e.get("output") else ""
        extra = f"（{e['detail']}）" if e.get("detail") else ""
        print(f"{e['ts']} | {e['action']} | {e['status']} | {e['file']}{out}{extra}")
    print(f"共 {len(items)} 条，日志目录：{activity_log.log_dir()}")


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

    # watch（监听输入目录）
    pw = sub.add_parser("watch", help="监听输入目录：txt 自动转 EPUB，非 txt 直接导出")
    pw.add_argument("-i", "--interval", type=float, help="轮询间隔秒数（默认取 config.yaml）")
    pw.add_argument("-r", "--recursive", action="store_true", help="递归监听子目录")
    pw.add_argument("--once", action="store_true", help="只扫描一轮就退出（等同 scan）")

    # scan（单次扫描）
    pk = sub.add_parser("scan", help="立即扫描输入目录一轮（不常驻）")
    pk.add_argument("-i", "--interval", type=float, help="（保留参数，单次扫描无需间隔）")
    pk.add_argument("-r", "--recursive", action="store_true", help="递归扫描子目录")

    # logs（查看活动日志）
    pl = sub.add_parser("logs", help="查看转换 / 添加的活动日志")
    pl.add_argument("-n", "--limit", type=int, default=50, help="显示条数（默认 50）")
    pl.add_argument("--action", help="按操作过滤：转换 / 添加 / 跳过")
    pl.add_argument("--status", help="按结果过滤：成功 / 失败")
    pl.add_argument("-q", help="按文件名关键字过滤")

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
    elif cmd == "scan":
        args.once = True
        cmd_watch(args)
    elif cmd in ("watch", "logs"):
        globals()[f"cmd_{cmd}"](args)
    else:
        cmd_convert(args)


if __name__ == "__main__":
    main()
