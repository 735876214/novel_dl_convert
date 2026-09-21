"""配置与路径解析：环境变量优先，YAML 配置文件兜底。

目录约定（NAS / 容器部署）：
- INPUT_DIR  输入目录：存放待转换的 txt 等源文件
- OUTPUT_DIR 导出目录：生成的 epub 等成品落盘位置
- CONFIG_DIR 配置目录：存放 config.yaml
- COOKIE_DIR Cookie 持久化目录：各书源登录态落盘（download 功能）
- CACHE_DIR  缓存目录：AI 分章结果缓存（按文本哈希）+ 监听状态文件
- LOG_DIR    日志目录：转换 / 添加的活动日志（activity.log、activity.jsonl）
"""
import json
import os
import pathlib

import yaml

# ---- 目录（环境变量可覆盖，便于容器 / NAS 挂载）----
CONFIG_DIR = pathlib.Path(os.getenv("CONFIG_DIR", "/app/config"))
INPUT_DIR = pathlib.Path(os.getenv("INPUT_DIR", "/app/input"))
OUTPUT_DIR = pathlib.Path(os.getenv("OUTPUT_DIR", "/app/output"))
# 多书库（第 10 期）：书库来源根目录 —— 其下的子文件夹可被「新建书库」就地引用，
# 或作为导入源（扫描后复制/移入该库自己的存储目录）。
# OUTPUT_DIR 不废弃：当书库表为空时它是**默认书库**的根（兼容既有部署）。
LIBRARY_SOURCE_DIR = pathlib.Path(os.getenv("LIBRARY_SOURCE_DIR", "/app/libraries"))
COOKIE_DIR = pathlib.Path(os.getenv("COOKIE_DIR", str(CONFIG_DIR / "cookies")))
CACHE_DIR = pathlib.Path(os.getenv("CACHE_DIR", str(CONFIG_DIR / "cache")))
SOURCES_DIR = pathlib.Path(os.getenv("SOURCES_DIR", str(CONFIG_DIR / "sources")))
LOG_DIR = pathlib.Path(os.getenv("LOG_DIR", str(CONFIG_DIR / "logs")))
# 持久化数据（SQLite + 其它用户数据），与配置目录同卷挂载，便于 NAS 多端一致
DATA_DIR = pathlib.Path(os.getenv("DATA_DIR", str(CONFIG_DIR / "data")))
CONFIG_FILE = CONFIG_DIR / "config.yaml"
# 应用内「设置」页写回的文件：只存被改过的字段，叠加在 config.yaml 之上。
# 单独放一个文件是为了**不改写 config.yaml 的注释与排版**。
SETTINGS_FILE = CONFIG_DIR / "settings.json"
# 「高级」里直接编辑 config.yaml 时的自动备份目录
BACKUP_DIR = pathlib.Path(os.getenv("BACKUP_DIR", str(CONFIG_DIR / "backups")))
# 阅读字体（用户上传的 TTF/OTF/WOFF/WOFF2，见 core/fonts.py）——
# 与配置同卷，随 CONFIG_DIR 一起备份，NAS 多端一致
FONTS_DIR = pathlib.Path(os.getenv("FONTS_DIR", str(CONFIG_DIR / "fonts")))

# 把解析后的目录回写环境变量，供其它模块（如 ai_detect）在 import 时读取
os.environ.setdefault("COOKIE_DIR", str(COOKIE_DIR))
os.environ.setdefault("CACHE_DIR", str(CACHE_DIR))
os.environ.setdefault("LOG_DIR", str(LOG_DIR))

# ---- 配置默认值（config.yaml 可覆盖）----
DEFAULTS = {
    "chapter_detection": {"mode": "hybrid", "context_lines": 3, "fallback": "regex"},
    "traditionalize": False,
    # format: epub；mobi/azw3 需本机 Calibre ebook-convert
    # layout: flat  = 全部平铺在 OUTPUT_DIR（原行为）
    #         komga = 有系列的书放 ``系列名/系列名 #N.ext``，让 Komga 扫描后正确成系列
    #                 （Komga 不递归系列目录的子目录，故最多一层；无系列的书仍平铺）
    "output": {"format": "epub", "layout": "flat"},
    # 成品命名规则：**副本名**的默认 pattern/scope（存 settings.json 覆盖层；
    # 每库可覆盖，见 core/lib_settings，刮削面板与设置页共用同一份规则）
    # 可用占位符见 core/fileops.PATTERN_FIELDS；扩展名由后端自动追加，模式里不要写 {ext} 之外的后缀
    "naming": {
        "pattern": "{author} - {title}",
        "scope": "all",             # all / epub / mobi / azw3 / pdf / txt
    },
    # 刮削出版（第 18 期）：把刮削结果写进**硬链接副本**，源文件永不改动 ——
    # 这样外部阅读器（Komga 等）能读到整理完成的书，而原作逐字节保持原样。
    # 成品目录**不在全局配置里**：它是每库的列（libraries.publish_path），
    # 由「新建 / 编辑书库」时手动选择，只对该库的内容生效。
    "scrape": {
        "enabled": True,            # 扫描入库后自动排队刮削（后台单线程串行）
        "max_attempts": 2,          # 同一本的自动重试上限，超限标失败等人工整理
        # 空闲时校验副本是否还在（每 N 秒一次；<=0 关闭）。
        # ⚠️ 校验只**标记待确认**（removed / orphan），绝不自动删源、绝不自动重建。
        "verify_interval": 120,
    },
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
    # 上传上限。⚠️ 此前**完全没有任何限制**：POST /convert 与 POST /api/sources/upload
    # 都直接 `await file.read()`，把整个请求体一次性读进内存 —— 一个几 GB 的请求
    # 就能把容器内存打满（不需要鉴权绕过，走正常接口即可）。
    # 现在改为按上限分块读取，累计超限立即中断并返回 413。
    "upload": {
        "max_bytes": 50 * 1024 * 1024,          # 单本书上限（默认 50 MB）
        "max_source_rules_bytes": 5 * 1024 * 1024,  # 书源 JSON 上限（默认 5 MB）
    },
    # 成就统计与界面开关（对应上游 Profile 页的 Enable achievements）。
    # 关闭后：不判定、不解锁，且侧栏隐藏成就入口 —— 与上游「不统计、不显示成就相关界面」一致。
    "achievements": {
        "enabled": True,
    },
    # OPDS 目录订阅源（供第三方阅读器订阅下载）。
    # 默认**关闭**：它开了一个 Basic Auth 入口（账号=应用账号），
    # 用户没打算用就不该默默对外暴露。
    "opds": {
        "enabled": False,
        # 书库是否出现在对外 OPDS 目录里（第 14 期「按库暴露」）。
        # 默认 True = 全部书库都暴露，与加这个开关之前的行为完全一致；
        # 可逐库覆盖为 False 把某个库藏起来（不进库导航、单库地址 404）。
        "expose": True,
    },
    # KOReader 进度互通（kosync 协议）。
    # `key` 是**密码的 MD5**（协议本身就这么传），服务端只存这个哈希，从不接触明文。
    # 同样是默认关闭：开了就多一个对外入口。
    "koreader": {
        "enabled": False,
        "username": "koreader",
        "key": "",
    },
    # 外部服务凭据（第 4 期）。三家都**不是 OAuth**：
    #   Hardcover   → API Token（账号设置页生成），GraphQL + Bearer
    #   Readwise    → API Token，REST + `Authorization: Token`
    #   StoryGraph  → **没有公开 API**：上游存的也是登录态 Cookie，且自己注明可能失效
    # 凭据一律掩码回显，提交掩码 = 不修改。
    "integrations": {
        "hardcover": {"token": ""},
        "readwise": {"token": ""},
        "storygraph": {"session": "", "remember_token": ""},
    },
    # 元数据自动抓取与治理（第 5 期）。
    # 会**外呼公网**（OpenLibrary / Google Books），所以默认关闭，由用户显式打开。
    "metadata_fetch": {
        "enabled": False,
        # 源顺序：依次检索并按匹配分合并（单源失败不影响其它源）
        "sources": ["openlibrary", "googlebooks"],
        "limit": 5,                      # 每个源取多少条候选
        # 置信度阈值：低于它的候选**不自动应用**，只在页面上列出来让人挑
        "threshold": 0.75,
        # 字段策略：默认 overwrite（在线优先覆盖本地）；fill_only（仅原值空时写）/ skip 仍可用。
        # 无论哪种，用户通过编辑器显式改过的字段都会记入 meta_override 并受保护（再抓取不冲掉）。
        "fields": {
            "title": "overwrite", "author": "overwrite", "publisher": "overwrite",
            "year": "overwrite", "language": "overwrite", "isbn": "overwrite",
            "description": "overwrite", "tags": "overwrite", "cover": "overwrite",
        },
        "auto_on_import": False,         # 新书入库时自动抓（仍受阈值与字段策略约束）
        # 题材黑名单：抓到的 tags 里命中这些词的**不写入**（过滤「小说」这类无信息量的值）
        "genre_blocklist": ["小说", "文学", "General", "Fiction"],
        # 自定义元数据（第 35 期起**已下线**这个配置项）：改由 core/customfields.py 管理 ——
        # 定义与按书的值都在 DB（custom_field_defs / book_custom_values），
        # 老配置里的这串 {name, value} 会在启动时被 migrate_from_config 迁成字段定义。
        # 原来那句注释「写入 EPUB 的 <meta>」是**从未兑现**的：全仓没有任何一处把它应用出去，
        # 而「元数据只存服务端、不写文件」是硬约定 —— 所以这是一项死配置，删掉无损。
        # Google Books 匿名额度很低（实测常撞 429），填 Key 可提高
        "googlebooks_api_key": "",
        # 作者级元数据（第 8 期 D1/D2/D5）：独立于书籍抓取开关，默认关
        "authors": {
            "enabled": False,      # 是否抓取作者传记 / 头像
            "fetch_bio": True,     # 抓传记
            "fetch_photo": True,   # 抓头像（下载到 CACHE_DIR/authors/ 本地缓存）
            "sources": ["openlibrary"],
        },
    },
    # Komga v1 兼容服务端（第 5 期）：让第三方 Komga 客户端（Mihon/Panels/官方 App）
    # 把本应用当成 Komga 服务器用 —— 浏览书库、读漫画/EPUB/PDF、推拉阅读进度。
    # 默认关闭：开了等于对外暴露一个「Komga 服务端」，且认证走应用账号。
    "komga": {
        "enabled": False,
        "username": "admin",   # HTTP Basic 的用户名（密码用登录 PIN）
        "api_key": "",         # 可选：客户端也可用 X-API-Key（App 端比 Basic 更省事）
        # 书库是否出现在 Komga 客户端的书库列表里（第 22 期，与 opds.expose 同口径）。
        # 默认 True = 全部符合条件的库都暴露，与加这个开关之前的行为完全一致；
        # 可逐库覆盖为 False 把某个库藏起来（不进列表、直连它的书也 404）。
        "expose": True,
    },
    # 多书库（第 10 期 D8）。
    # 库实体本身存 SQLite（libraries 表）；这里只放**跨库策略开关**。
    "libraries": {
        # 启动时检测到「现有书还没按格式归库」时，是否跳过确认直接搬。
        # 默认 **False**：迁移是真移文件（破坏性），第一次必须由用户点一次确认。
        "auto_migrate": False,
    },
}


def ensure_dirs():
    """确保输入 / 导出 / 配置 / cookie / 缓存 / 用户书源 / 日志目录存在（容器启动时调用）。"""
    for d in (INPUT_DIR, OUTPUT_DIR, CONFIG_DIR, COOKIE_DIR, CACHE_DIR, SOURCES_DIR, LOG_DIR, DATA_DIR, BACKUP_DIR, FONTS_DIR, LIBRARY_SOURCE_DIR):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


def load_overrides() -> dict:
    """读取应用内设置覆盖层（settings.json）。不存在或损坏时返回空 dict。"""
    if not SETTINGS_FILE.is_file():
        return {}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_overrides(data: dict) -> None:
    """写入设置覆盖层（整份替换）。"""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_config() -> dict:
    """加载配置：默认值 → config.yaml → settings.json 覆盖层 → 环境变量。"""
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

    # 应用内「设置」页的覆盖层（config.yaml 之上）
    for k, v in load_overrides().items():
        if isinstance(v, dict) and isinstance(data.get(k), dict):
            data[k] = {**data[k], **v}
        else:
            data[k] = v

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
