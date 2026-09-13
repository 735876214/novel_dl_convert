import argparse
import pathlib

from . import pipeline, config


def main():
    ap = argparse.ArgumentParser(
        prog="novelforge", description="TXT 小说转 EPUB（输入 / 导出目录分离）"
    )
    ap.add_argument(
        "input",
        nargs="?",
        default=None,
        help="txt 文件或目录；省略时使用 INPUT_DIR 环境变量（默认 /app/input）",
    )
    ap.add_argument(
        "-o",
        "--output",
        default=None,
        help="导出目录；省略时使用 OUTPUT_DIR 环境变量（默认 /app/output）",
    )
    ap.add_argument("-f", "--force", action="store_true", help="覆盖已存在的输出")
    ap.add_argument("-m", "--merge", action="store_true", help="合并过小的章节")
    ap.add_argument("--traditionalize", action="store_true", help="繁体转简体")
    ap.add_argument("-t", "--test-title", help="测试某标题是否能被正则识别（调试用）")
    args = ap.parse_args()

    if args.test_title:
        from .core import detect

        ok = any(p.search(args.test_title) for p in detect.CHAPTER_PATTERNS)
        print(f"匹配: {ok}  ->  {args.test_title}")
        return

    config.ensure_dirs()
    out = pathlib.Path(args.output) if args.output else config.OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)

    src = pathlib.Path(args.input) if args.input else config.INPUT_DIR
    if src.is_dir():
        for f in sorted(src.iterdir()):
            if f.suffix.lower() == ".txt":
                pipeline.dispatch(f, out, vars(args))
    else:
        pipeline.dispatch(src, out, vars(args))


if __name__ == "__main__":
    main()
