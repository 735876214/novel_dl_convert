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
# 多书库来源根（第 10 期起）：其下的子文件夹可被「新建书库」就地引用。
# 第 41 期增强为**不定数量的来源根**：compose 用多个独立环境变量声明，
#   LIBRARY_SOURCE_DIRS1=/电子书1、LIBRARY_SOURCE_DIRS2=/电子书2 …（序号从 1 连续，首个缺号即停）
#   可选 LIBRARY_SOURCE_DIRS1_NAME=主库 覆盖显示名（默认取路径最后一级）。
# 未配置任何编号变量时回退到单根 LIBRARY_SOURCE_DIR（默认 /app/libraries），保持老部署兼容。
# OUTPUT_DIR 不废弃：没有库归属的条目（老部署遗留在 OUTPUT_DIR 的书、或某个库被
# 移除登记之后）路径解析仍以它为根。第 37 期起它**不再是**「默认书库」的根 ——
# 本项目不再有默认库，也不会自动在 OUTPUT_DIR 上建库。
_LIBRARY_SOURCE_ROOTS: "list[dict]" = []
_i = 1
while True:
    _raw = os.getenv(f"LIBRARY_SOURCE_DIRS{_i}")
    if _raw is None:
        break
    _i += 1
    _raw = _raw.strip()
    if not _raw:
        continue
    _p = pathlib.Path(_raw)
    _nm = os.getenv(f"LIBRARY_SOURCE_DIRS{_i - 1}_NAME", "").strip()
    if not _nm:
        _nm = _p.name or _raw
    _LIBRARY_SOURCE_ROOTS.append({"name": _nm, "path": _p})

if not _LIBRARY_SOURCE_ROOTS:
    _fb = pathlib.Path(os.getenv("LIBRARY_SOURCE_DIR", "/app/libraries"))
    _fb_name = os.getenv("LIBRARY_SOURCE_DIR_NAME", "").strip() or _fb.name or "libraries"
    _LIBRARY_SOURCE_ROOTS.append({"name": _fb_name, "path": _fb})

# 来源根集合：每个元素 {"name": 显示名, "path": Path}。
LIBRARY_SOURCE_ROOTS = _LIBRARY_SOURCE_ROOTS
# 兼容别名：指向第一个来源根（老代码 / 测试可能仍引用 LIBRARY_SOURCE_DIR，后续清理）。
LIBRARY_SOURCE_DIR = LIBRARY_SOURCE_ROOTS[0]["path"]


def _is_under_source_root(p: "pathlib.Path") -> bool:
    """p 是否落在某个来源根之内（含根本身）。仅用于一次性的就地引用边界校验。"""
    for r in LIBRARY_SOURCE_ROOTS:
        if p == r["path"] or p.is_relative_to(r["path"]):
            return True
    return False


def normalize_source_dirs(paths) -> "list[pathlib.Path]":
    """就地引用边界：每个路径必须是绝对路径且落在某来源根内（跨根合法）。
    返回规整后的 Path 列表；非法抛 ValueError（由 server 转 400）。
    注意：本函数**不反查所属根名、也不计算相对子目录**——那部分信息由前端
    在下钻选择时持有，绝对路径即唯一真值。"""
    out: "list[pathlib.Path]" = []
    for p in (paths or []):
        pp = pathlib.Path(str(p).strip())
        if not pp.is_absolute():
            raise ValueError(f"库文件夹必须是绝对路径：{p}")
        if not _is_under_source_root(pp):
            raise ValueError(f"库文件夹不在任何来源根内：{p}")
        out.append(pp)
    return out
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
    # 阅读状态口径（第 40 期）：新建书库向导第 4 步可配，全局 + 每库覆写。
    # ⚠️ 两个默认值都**刻意等于改造前的硬编码值** —— 读起来像多此一举，但这是必须的：
    # 全仓原有 11 处硬编码 `99.5` 与 4 处 `pct > 0`，改默认值等于**静默改变既有判定**，
    # 会让用户的书一夜之间从「已读完」变回「在读」。有「逐字节等价」用例钉住这两个数。
    "reading": {
        # 「在读」下界：进度 **> 该值** 即在读（默认 0.0 ≡ 改造前的 `pct > 0`）
        "started_threshold": 0.0,
        # 「已读完」阈值：进度 **>= 该值** 即读完。
        # ⚠️ 默认 99.5 是本仓既有口径，**不是上游 BookOrbit 的 99** —— 别顺手对齐上游。
        "finished_threshold": 99.5,
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
        # 留存策略（第 52 期）。**默认关闭** —— 关着就是原来的「单文件一直追加」，
        # 不改变任何既有行为；打开后当前文件超过 max_bytes 就轮转成带时间戳的归档，
        # 只保留最近 keep 份（可选 gzip），读取会自动跨归档，审计页仍连续。
        "retention": {
            "enabled": False,
            "max_bytes": 5 * 1024 * 1024,
            "keep": 5,
            "compress": True,
        },
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
        # auto_push（第 52 期）：新增批注 / 改状态 / 改评分书评时**自动**推给该服务。
        # 默认一律 False —— 这是「写向第三方」的动作，必须由用户显式打开。
        "hardcover": {"token": "", "auto_push": False},
        "readwise": {"token": "", "auto_push": False},
        "storygraph": {"session": "", "remember_token": "", "auto_push": False},
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
        # 跨源字段级合并（第 58 期）：够格的候选来自 ≥2 家时**逐字段择优**
        # （简介信 Google Books、年份/语言信 Open Library…，题材多源合并去重）。
        # 关掉即回到「只用匹配分最高的那一条候选」的旧行为。
        "merge_sources": True,
        # 按书籍语种自动重排来源顺序（第 60 期）：专精本语种的（韩→Aladin、波→Lubimyczytac、
        # 日→RanobeDB）排最前，多语种通吃的（Google Books / Open Library / Kobo）居中，
        # 专精别的语种的排最后；**每档内保持你在「元数据来源」里设的顺序**。
        # 语种取自书的 language 字段，未知就不重排（不猜）。关掉即严格按你设的顺序依次检索。
        "auto_order_by_language": True,
        # 题材黑名单：抓到的 tags 里命中这些词的**不写入**（过滤「小说」这类无信息量的值）
        "genre_blocklist": ["小说", "文学", "General", "Fiction"],
        # 自定义元数据（第 35 期起**已下线**这个配置项）：改由 core/customfields.py 管理 ——
        # 定义与按书的值都在 DB（custom_field_defs / book_custom_values），
        # 老配置里的这串 {name, value} 会在启动时被 migrate_from_config 迁成字段定义。
        # 原来那句注释「写入 EPUB 的 <meta>」是**从未兑现**的：全仓没有任何一处把它应用出去，
        # 而「元数据只存服务端、不写文件」是硬约定 —— 所以这是一项死配置，删掉无损。
        # Google Books 匿名额度很低（实测常撞 429），填 Key 可提高
        "googlebooks_api_key": "",
        # 第 57 期：另外三家的密钥（键名与 `core/metasources.SOURCES[*].key_field` 一一对应，
        # 「元数据来源」页按注册表渲染输入框）。填了才能用那一家，留空即该家返回明确错误。
        "hardcover_api_token": "",       # Hardcover（GraphQL Bearer Token）
        "comicvine_api_key": "",         # Comic Vine（免费申请，限流 200 次/小时）
        "aladin_ttbkey": "",             # Aladin（韩国书店 TTB API）
        # 行内抓取参数（第 57 期 E 段，值域与注册表 config_fields 的 options 对齐）
        "amazon_cookie": "",             # Amazon：登录后的 Cookie（可选，降低反爬拦截率）
        "itunes_cover_resolution": "high",   # iTunes 封面：high(1000) / standard(100)
        "kobo_region": "us",             # Kobo：URL 的区域段
        "kobo_language": "en",           # Kobo：URL 的语言段（要与区域匹配才不被拦）
        "audible_region": "us",          # Audible：分站域名 us/uk/de/jp
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
    for d in (INPUT_DIR, OUTPUT_DIR, CONFIG_DIR, COOKIE_DIR, CACHE_DIR, SOURCES_DIR, LOG_DIR, DATA_DIR, BACKUP_DIR, FONTS_DIR):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
    # 每个来源根也要确保存在（就地引用直接读这些目录）
    for r in LIBRARY_SOURCE_ROOTS:
        try:
            r["path"].mkdir(parents=True, exist_ok=True)
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
