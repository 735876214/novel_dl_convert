"""配置与路径解析：环境变量优先，YAML 配置文件兜底。

目录约定（NAS / 容器部署）：
- INPUT_DIR  输入目录：存放待转换的 txt 等源文件
- OUTPUT_DIR 导出目录：生成的 epub 等成品落盘位置
- CONFIG_DIR 配置目录：存放 config.yaml
- COOKIE_DIR Cookie 持久化目录：各书源登录态落盘（download 功能）
- CACHE_DIR  缓存目录：AI 分章结果缓存（按文本哈希）+ 监听状态文件
- LOG_DIR    日志目录：转换 / 添加的活动日志（activity.log、activity.jsonl）
"""
import os
import pathlib

import yaml

# ---- 目录（环境变量可覆盖，便于容器 / NAS 挂载）----
CONFIG_DIR = pathlib.Path(os.getenv("CONFIG_DIR", "/app/config"))
INPUT_DIR = pathlib.Path(os.getenv("INPUT_DIR", "/app/input"))
OUTPUT_DIR = pathlib.Path(os.getenv("OUTPUT_DIR", "/app/output"))
COOKIE_DIR = pathlib.Path(os.getenv("COOKIE_DIR", str(CONFIG_DIR / "cookies")))
CACHE_DIR = pathlib.Path(os.getenv("CACHE_DIR", str(CONFIG_DIR / "cache")))
SOURCES_DIR = pathlib.Path(os.getenv("SOURCES_DIR", str(CONFIG_DIR / "sources")))
LOG_DIR = pathlib.Path(os.getenv("LOG_DIR", str(CONFIG_DIR / "logs")))
CONFIG_FILE = CONFIG_DIR / "config.yaml"

# 把解析后的目录回写环境变量，供其它模块（如 ai_detect）在 import 时读取
os.environ.setdefault("COOKIE_DIR", str(COOKIE_DIR))
os.environ.setdefault("CACHE_DIR", str(CACHE_DIR))
os.environ.setdefault("LOG_DIR", str(LOG_DIR))

# ---- 配置默认值（config.yaml 可覆盖）----
DEFAULTS = {
    "chapter_detection": {"mode": "hybrid", "context_lines": 3, "fallback": "regex"},
    "traditionalize": False,
    "output": {"format": "epub"},  # epub；mobi/azw3 需本机 Calibre ebook-convert
    "download": {
        "enabled": False,           # 默认关闭，仅公版源可用
        "public_only": True,
    },
    "network": {
        "cookie_dir": str(COOKIE_DIR),
        "host_replace": {},         # 应对 CDN 漂移：{"old-host": "new-host"}
        "max_retries": 3,
    },
    # 可选：hybrid/ai 模式下 AI 分章兜底（不填 api_key 则仅用正则 + 缩进降级）
    "llm": {"api_key": "", "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    # 输入目录自动监听：txt 转 EPUB，其它文件直接导出
    "watcher": {
        "enabled": True,            # 服务启动时自动监听（也可用环境变量 AUTO_WATCH 覆盖）
        "interval": 5.0,            # 轮询间隔（秒）；NAS 网络挂载建议 >=3s
        "recursive": False,         # 是否递归子目录
        "settle_seconds": 1.0,      # 每次稳定判定的等待间隔
        "stable_rounds": 2,         # 连续 N 次读到相同大小才认为写入完成
        "copy_non_txt": True,       # 非 txt 文件原样导出到 output
        "process_existing": True,   # 启动时是否处理 input 里已有的存量文件
        "max_retries": 3,           # 单个文件失败重试上限，超过则记为失败并跳过
        "ignore": [
            ".*",
            "*.tmp", "*.temp", "*.part", "*.crdownload", "*.partial", "*.download",
            "*.swp", "*.swx", "~$*",
            "*.meta.json", "*.log", "*.jsonl",
        ],
    },
    # 活动日志（时间 / 文件名 / 操作 / 成败）
    "logging": {
        "dir": "",                  # 留空则用 LOG_DIR（默认 <CONFIG_DIR>/logs）
        "max_entries": 2000,        # 内存缓冲条数（API 读取用，落盘不受限）
    },
}


def ensure_dirs():
    """确保输入 / 导出 / 配置 / cookie / 缓存 / 用户书源 / 日志目录存在（容器启动时调用）。"""
    for d in (INPUT_DIR, OUTPUT_DIR, CONFIG_DIR, COOKIE_DIR, CACHE_DIR, SOURCES_DIR, LOG_DIR):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


def load_config() -> dict:
    """加载配置：先取默认值，再用 YAML 文件中的字段覆盖。"""
    data = {k: (v.copy() if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}
    if CONFIG_FILE.is_file():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or {}
            if isinstance(loaded, dict):
                for k, v in loaded.items():
                    if isinstance(v, dict) and isinstance(data.get(k), dict):
                        data[k].update(v)
                    else:
                        data[k] = v
        except Exception:
            pass

    # 环境变量覆盖监听开关 / 轮询间隔：容器部署时无需改配置文件
    auto = os.getenv("AUTO_WATCH")
    if auto is not None:
        data.setdefault("watcher", {})["enabled"] = auto.strip().lower() in ("1", "true", "yes", "on")
    if os.getenv("WATCH_INTERVAL"):
        try:
            data.setdefault("watcher", {})["interval"] = float(os.getenv("WATCH_INTERVAL"))
        except ValueError:
            pass
    return data
