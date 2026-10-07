# 格式 × 能力矩阵

本文是**能力边界的唯一成文口径**：哪些能力是**通用**（所有格式都必须支持）、哪些是**格式专有**
（只给某些格式是合法的，但必须写明理由）。配套的护栏是 `tests/test_format_matrix.py`。

> 为什么要有这份东西：第 86 期实测踩过一个坑 —— `core/features.py` 的 `FEATURES_BY_TYPE`
> 里 `sources` 能力**漏给了漫画库/有声书库**（注释还写着「书源下载产出 EPUB → 仅 ebook」，
> 那是更早的事实）。后果是**选中漫画库时「工具 → 书源管理」整个标签消失**，用户报
> 「书源找不到在哪」。能力键的判据是「**现有实现真实支持的范围**」：实现扩了而能力键没扩，
> 界面就会藏起用户真正需要的入口。

## 一、能力的两个轴

- **能力键**（`core/features.py` 的 `FEATURE_LABELS`，共 18 个）：前端据此显示/隐藏入口，
  `lib_settings.allows_setting` 据此剔除不生效的覆盖项。**判隐显的轴是「这本书/这个库」**，
  不是「侧栏当前选着哪个库」（后者只用于工具页标签与设置页导航）。
- **格式**：EPUB · TXT · PDF · MOBI/AZW3/AZW · FB2 · CBZ/CBR · 容器（ZIP/RAR/7Z，按内容分派）· 有声书 · UNITS（合集）。

## 二、矩阵

图例：**✅ 完整** · **⚠️ 部分**（括注缺什么） · **🐛 曾静默失败**（已修，见第四节） ·
**❌ 无入口** · **— 不适用**

| 能力 \ 格式 | EPUB | TXT | PDF | MOBI/AZW3/AZW | FB2 | CBZ/CBR | 容器（图片档） | 有声书 | UNITS |
|---|---|---|---|---|---|---|---|---|---|
| 阅读 | ✅ | ✅ | ✅ | ⚠️ 直读（KF8 全功能；纯 MOBI6 无插图 / 无书内样式、CFI 留空） | ✅ 直读（解析成派生 EPUB，见 §八） | ✅ | ✅ 归一成 CBZ | ✅ 播放器 | ✅ |
| 封面 | ✅ 内嵌 | ✅ 抓取 | ✅ 抓取 | ✅ 抓取 | ✅ 内嵌（`<coverpage>`） | ✅ 首页 | ✅ 首页 | ✅ 目录内 cover 文件 | ✅ 目录内 cover 文件 |
| 元数据抓取 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 元数据手动编辑 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 搜索（书名/作者/系列） | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 重命名 / 命名规则 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅（`scope=all`） | ✅（`scope=all`） |
| 重复检测 / 同名冲突 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 标签 / 评分 / 书评 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 批注 / 书签 | ✅ | ✅ | ❌ 专有 | ✅ 见 §六 | ✅ 见 §八 | ❌ 专有 | ❌ 专有 | ❌ 专有 | ❌ 专有 |
| 导出目录浏览 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| OPDS（浏览/元数据） | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| OPDS 下载链 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ 刻意不给 | ⚠️ 刻意不给 |
| Komga 布局 / 服务端 | ✅ | ⚠️ text/plain | ✅ | ⚠️ 退 DIVINA | ✅ | ✅ | ✅ | ❌ 库级排除 | ❌ 库级排除 |
| 书源下载产出 | ✅ EPUB | ✅ EPUB | ✅ EPUB | ✅ EPUB | — 不适用 | ✅ CBZ | ✅ CBZ | ✅ 目录树 | ✅ |
| 发送到设备 | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

## 三、格式专有（合法的不一致，理由是判据）

| 能力键 | 只给 | 理由 |
|---|---|---|
| `ebook` / `pdf` / `comic` / `audio` | 对应库 | 四种**阅读器形态**，各自专有 |
| `annotations` / `bookmarks` | ebook（+mixed） | 批注与书签长在**文字阅读器**里；漫画/PDF/有声书是另外三个渲染器 |
| `authors` | ebook（+mixed） | 与作者检索绑定，目前只有 ebook 走那条检索路 |
| `convert`（手动投递） | ebook（+mixed） | 门槛沿用旧口径**刻意没放宽**（放宽等于给漫画/有声书库也开一个工具入口，是独立一期的评估） |
| `komga` | ebook / comic（+mixed） | Komga 布局针对**系列化目录**；有声书库不进（协议无音频模型） |

`_COMMON` 的 7 项（`rename` / `duplicates` / `entity` / `missing` / `logs` / `output` / `opds`）
是**与格式无关**的通用能力，四类库都必须有 —— 契约测试逐个钉。

## 四、本轮（第 87 期）修掉的不一致

| # | 现象（用户看到什么） | 根因 | 修法 |
|---|---|---|---|
| 1 | 封面**抓取成功但永远不显示**（PDF/TXT/MOBI/AZW3 卡片显示「有封面」，图位却是渐变占位） | 封面接口把 `db.get_cover` 的读取**只写在 EPUB 分支里**（`:fmt != "EPUB" ⇒ 404`），而 `_apply_overlay` 对**任何格式**只要库里存了抓取封面就置 `has_cover=True` | 把服务端封面的读取**提到格式分支之前**（漫画/有声书仍优先用文件内封面，行为逐字不变） |
| 2 | OPDS 客户端点下载报「文件不存在」 | `opds.book_entry` 无条件给每本书加 acquisition 链，而 `/opds/download/{bid}` 要求 `path.is_file()` ⇒ **目录型条目**（有声书/合集）必然 404 | 目录型条目**不给**下载链（与前端早已「刻意隐藏下载按钮」同口径：少给，而不是错给） |
| 3 | 「无封面」筛选与卡片显示**各说各话** | 前端分面判据是 `format === 'EPUB' && !has_cover`，只算 EPUB | 改成「没有封面」即命中（与后端 `has_cover` 的口径一致） |
| 4 | `.zip` 扫不到，或扫到也打不开 / 无封面 | `.zip` 不在任何白名单；`is_comic` 只看后缀 | 新增 `core/zipkind.py`：**容器看内容**。图片档归一成 `CBZ` ⇒ 封面/逐页接口/阅读器**上层零分支**；判不出的（内含 EPUB/PDF、嵌套、混装、坏包）照样入库但记「无法解析」，在「待修复」里看得见 |
| 5 | 选中漫画库时「工具 → 书源管理」标签消失 | `FEATURES_BY_TYPE` 里 `sources` 漏给 comic/audiobook | 补上（`features.py`），并在契约测试里写明原因 |

## 五、加新能力 / 新格式时要动哪几处

按 `AGENTS.md:19`「加/删功能都要彻底」：

1. `core/features.py`：`FEATURE_LABELS`（中文名）+ `FEATURES_BY_TYPE`（给哪些库）。
   **只给部分库时必须写清理由**，并登记进 `tests/test_format_matrix.py` 的 `EXCLUSIVE` 表 ——
   否则测试会红（这就是防「又漏配一个库」的那道闸）。
2. `core/library.py`：格式白名单（`BOOK_EXTS` / `_COMIC_EXTS` / `_EBOOK_EXTS` / `_exts_for_type`）
   与 `_probe_entry` 的形态探测。**新格式一律先问「它是容器吗」**：是容器就走内容分派
   （`zipkind`），不要靠后缀猜。
3. 前端：`lib/bookOpen.ts` 的 `READER_FORMATS` / `THUMBNAIL_READER_FORMATS`、
   `ReaderView.vue` 的阅读器选择。**能让后端把形态归一成既有 format 就不要动前端**
   （`.zip → CBZ` 就是这么做的；MOBI/AZW3 也是 —— 第 110 期只往两个集合里加格式名，
   阅读器本身零分支）。
4. **`core/readsource` 级的一件事：新格式的正文到底在哪个文件里**（第 110 期新增，见 §六）。
   只要「读的文件 ≠ 书架上那个文件」，就必须把这个问题收敛到**一处**（四个读点：目录表 /
   单章正文 / 书内资源与样式 / 进度的 CFI）。第 87 期那四条不一致（抓取封面永远 404、
   OPDS 给出必然 404 的下载链…）都是同一个判据在四处各写一遍造成的。
5. 本文件 + `tests/` 的契约测试 + 记忆。

## 六、第 110 期：MOBI / AZW3 / AZW **直读**（能力变化）

**口径**：`mobi直接阅读，不进行转化`（用户原话）。做法是**解包（unpack）**，不是转换 ——
把书自身的 KF8 内容抽出来直接读：**不进书库、不新增书目条目、不写回源文件**（源全程只读）。

| 事项 | 落点 / 口径 |
|---|---|
| 解包产物 | `CACHE_DIR/mobi-unpack/<book_id>/`（`core/mobicache.py` 的 `CACHE_SUBDIR`）：可随时重建、可随时整个删掉 |
| **唯一的「读目标」判据** | `mobicache.read_target(book)` → `"epub"` / `"html"` / `"pdf"` / `""`。四个读点（详情页目录表 `library.book_detail`、单章 `api_book_chapter`、书内资源与样式 `api_book_asset` + `api_epub_css`、进度的 CFI `_progress_file`）**全部问它一处** —— 见 §五 第 4 条 |
| KF8 / AZW3 | 解包出的是**真 EPUB** ⇒ 目录 / 正文 / 插图 / 书内样式 / **CFI 精确位置** / 批注**零新代码**复用 EPUB 链路（`library._reading_list` / `chapter_html` / `chapter_assets` / `epub_cfi`） |
| 纯 MOBI6 | 解包只出 `mobi7/book.html` ⇒ 复用既有分章真值源（`detect`）渲染成章节流。**如实降级**：没有插图、没有书内样式、`cfi` 留空（恢复回落「章 + 全书百分比」，与 TXT 原生路线同款） |
| Print Replica 型 | 解包出 `<base>.001.pdf` ⇒ 交回既有 PDF 阅读路线（本期不为它新增处理） |
| 缓存失效三分量 | 源指纹 + `mobicache.RULE_VERSION` + **`mobi` 包版本**（后者是本期特有的：读到什么由抽取器决定，换了版本目录可能变） |
| 缺解包器 | 章节接口 **503**「服务器缺少 MOBI 解包能力（需 mobi）」（与缺 bsdtar 时 `.cbr` 的 503 同款）；详情页目录**如实为空**；进度照常能存。**绝不假装能读、绝不 500** |
| 解不开 / 坏书 | 章节接口 **422** + 原因（把抽取器的话转述出来）；源没变就**锁定形态**不再重试；产物原子换入，不留半个目录 |
| 批注 / 书签 | ✅ 可用。判据不在 CFI 上：`db.add_annotation` 用的是 `chapter` + `start_off` / `end_off`（**章内字符偏移，真能定位**），`anchor` 只用于去重与溯源 |
| 封面点击 | `MOBI` / `AZW3` / `AZW` 已进 `READER_FORMATS` 与 `THUMBNAIL_READER_FORMATS`（有了内容就该直读）；仍读不了的（如**未归一成书**的 `ZIP` 容器）继续进详情页 |
| `.azw` | 本期才进白名单（`BOOK_EXTS` / `_EBOOK_EXTS`）：它此前**不是书**，扫描时被忽略；`SCAN_RULE_VERSION` 2 → 3 ⇒ 存量库下次刷新走一次全量重探 |
| 契约测试 | `tests/test_mobi_reader.py`（12 例）：把 `unpackBook` 换成造**真 EPUB / 真 HTML** 的假解包器 ⇒ **不依赖第三方样本**；真样本那条 `skipif`，把任意 `.mobi` 放到 `tests/fixtures/mobi/demo.mobi` 即自动启用 |
| 许可证 | `mobi` 是 **GPL-3.0-only** 且为**进程内** import ⇒ 本项目整体按 **AGPL-3.0** 分发（见根目录 `LICENSE` 与 `THIRD-PARTY-NOTICES.md`） |

## 七、第 111 期：`.rar` / `.7z` 容器（与 `.zip` 同一套判据）

**口径**：容器看内容、不看后缀（第 87 期立的口径，本期把另外两个壳补齐）。用户原话（m00001）
要的是「mobi、zip、rar 等格式直接阅读」—— 第 110 期交付 MOBI，本期补齐容器。

| 事项 | 落点 / 口径 |
|---|---|
| 认哪些后缀 | `zipkind.CONTAINER_EXTS = (".zip", ".rar", ".7z")`；「没分派出形态」时的书目标签 = `zipkind.CONTAINER_FORMATS = ("ZIP", "RAR", "7Z")`（**由前者派生，只有一处**；`library.container_books` 与前端注释都认它） |
| 三个解压后端 | `core/comics.py` 的 `_Archive` 按**魔数**选：zip → `zipfile`；rar → `rarfile` + 外部解压器（`bsdtar` / `unrar`）；7z → `py7zr`（**纯 Python，不需要外部解压器**） |
| 能读的一档 | 里面是**图片序列** ⇒ 归一成 `CBZ`，页序 / 封面 / 逐页接口 / 阅读器**上层零分支**（与 `.cbz` 完全同等待遇）。**`.rar` 漫画因此第一次能直接读** |
| 需展开的一档 | 里面是别的书（EPUB / PDF / TXT / MOBI / AZW3 / FB2）或嵌套压缩包 ⇒ 照旧入库、记「无法解析」，进「工具 → 书库管理 → 副本与容器」的**待展开**清单（第 87 期的能力，第 111 期自动覆盖三兄弟）。⚠️ **第 112 期起这一档默认由后台自动展开**（可关，源容器原样保留），手动按钮仍在、对自动失败的容器兜底 —— 见 §八 |
| 缺解压能力 | **唯一判据** `comics.backend_problem(path)`：`.rar` 缺 bsdtar/unrar 或 `.7z` 缺 `py7zr` ⇒ 页接口 **503** 并**说清缺什么**；「缺能力」**不算**「这本书坏了」（两者文案分开）。魔数认不出时**退回后缀**再判一次 —— 半截下载 / 占位文件也该先报能力 |
| 白名单 | `.rar` / `.7z` 进 `library.BOOK_EXTS` + `_COMIC_EXTS` + `_EBOOK_EXTS`（**三类库都收**：里面可能是漫画，也可能是一份 EPUB）；`SCAN_RULE_VERSION` **3 → 4** ⇒ 存量库下一轮刷新全量重探一次 |
| 上传 / 转交 | `pipeline.EBOOK_EXT` 与 `server._ANY_MEDIA_EXTS` 同步补 `.rar` / `.7z`（否则「能入库的格式上传却 400」）；同批补上第 110 期漏掉的 `.azw` |
| 前端 | 只改两处**文案 / 注释**（`lib/api.ts` 的容器清单注释、`components/tools/LibraryCopiesPanel.vue`）；容器**没有**前端格式白名单，列表由 `/api/library-containers` 驱动 |
| 契约测试 | `tests/test_archive_kinds.py`（11 例）：`.7z` **现场造真归档**（`py7zr` 可写）跑完整链路；`.rar` **造不出来**（`rarfile` 只读，本机实测 `tool_setup()` 抛 `RarCannotExec`）⇒ 只测缺能力的诚实路径与判定档位，**绝不伪造「读过 RAR」的结论** |

## 八、第 112 期：FB2 直读 + 容器自动展开

### 8.1 FB2（`.fb2`）—— 解析成**派生 EPUB**

**口径**：与 MOBI 直读同一形态（§六）—— **不进书库、不新增书目条目、不写回源文件**，产物可随时重建或整个删掉。
区别只在「怎么得到那份 EPUB」：MOBI 是**解包**书自身已有的 KF8 内容，FB2 是**解析**单文件 XML 后**组装**一份。

| 事项 | 落点 / 口径 |
|---|---|
| 派生产物 | `CACHE_DIR/fb2-epub/<book_id>/derived.epub`（`core/fb2cache.py` 的 `CACHE_SUBDIR`）；组装复用 `core/epub_builder.build_epub`（本期给它加**可选** `images=`，默认 `None` ⇒ 既有调用方产物逐字节不变） |
| **唯一的「读目标」判据** | `fb2cache.read_target(book)` → `(派生 EPUB 路径, "epub")` / `(None, "")`。五个读点（目录表 `library.book_detail`、单章 `api_book_chapter`、书内资源 `api_book_asset`、书内样式 `api_epub_css`、进度的 CFI `_progress_file`）**全部问它一处** —— 同 §五 第 4 条 |
| 复用面 | 派生 EPUB 与真 EPUB **没有区别** ⇒ 目录（`library._reading_list`）/ 正文（`chapter_html`）/ 插图（资产接口，`<img src="images/bNNNN.png">` 被 `_rewrite_assets` 改写）/ 书内样式 / **CFI 精确位置** / 批注**零新代码**复用 |
| 解析器 | **标准库** `xml.etree.ElementTree`（与 `core/epub_cfi.py` 同口径）；零新依赖。预处理剥 `<?xml?>` / `<!DOCTYPE>` 并把 HTML5 具名实体（裸 `&nbsp;` 很常见）转数字引用 —— 复用 `epub_cfi._parse` 那套配方 |
| 可选兜底 | stdlib 解析失败且 **lxml 在**（`requirements.txt` 里本就有）⇒ 用 `XMLParser(recover=True)` 重试一次；两者都失败 ⇒ **422 + 原因**。lxml 缺失只少一层兜底，**不 503、不影响可用性** |
| 命名空间 | `local(tag)` 剥 `{ns}` 前缀 ⇒ 带不带 `gribuser` 命名空间都能过 |
| 根闸门 | 必须是 `FictionBook` 且至少一个 `<body>`，否则**算读不出**（别的 XML 不许冒充书） |
| 章节 | 带 `<title>` 的 `<section>` = 一章（标题取 `<title>` 文本），无 title 的递归并入当前章；收尾丢掉「既无可见文字又无 `<img>`」的纯容器章，再给无标题章补 `第 N 章`（**过滤之后**编号 ⇒ 0 基且连续） |
| 封面 | `<coverpage><image l:href="#id">` 那张图写进派生 EPUB ⇒ `api_book_cover` 的 FB2 分支把 path 换成派生产物，落回既有 EPUB 内嵌封面读取；扫描期只做**廉价头部扫描**（`has_embedded_cover`，读前 256 KB 找 `<coverpage`）—— 不把「丢一本书进库」变成一次 XML 解析 |
| 缓存失效三/四分量 | 源指纹 + `fb2cache.RULE_VERSION` + **`recover` 分量**（lxml 是否在）。`recover` 是**自愈钩子**：先前因无 lxml 而锁定失败的文件，装上 lxml 后即使源一个字节没动也能重建 —— 只比指纹会**永远锁死** |
| 读不出 | 章节接口 **422** + 原因（不 500、不假装能读）；源没变就**锁定形态**不再重试；进度**照常能存**（读不出只影响「读到什么」） |
| 白名单 | `.fb2` 进 `BOOK_EXTS` / `_EBOOK_EXTS`；`SCAN_RULE_VERSION` **4 → 5**；`pipeline.EBOOK_EXT` 与 `server._ANY_MEDIA_EXTS` 同步补 |
| 前端 | 只加格式名：`lib/bookOpen.ts` 的 `READER_FORMATS` 与 `THUMBNAIL_READER_FORMATS` 各加 `'FB2'`。`ReaderView.vue` **零改动** —— 后端已归一成真 EPUB |
| 契约测试 | `tests/test_fb2_reader.py`（17 例）：用例内**直接写真实 FB2 字节**（实体 / 嵌套 section / 脚注 body / 坏 base64 / 非 `FictionBook` 根 / 超大文件），**不依赖第三方样本** |
| 本期不做 | FB2 脚注 body（`<body name="notes">`）与悬空脚注锚（`<a l:href="#…">` 退成纯文本）；FB2 元数据（书名 / 作者仍按**文件名**解析，与 MOBI / TXT 同口径） |

### 8.2 容器自动展开（默认开启、可关；源容器保留）

| 事项 | 落点 / 口径 |
|---|---|
| 触发点 | `watcher.FolderWatcher._auto_unpack_tick()`，跑在**既有监听线程**里（与书目索引刷新同一条，**不新起线程** —— 否则要给 `tests/conftest.py::_quiesce_background` 的收尾清单加条目） |
| 节流 | 到 `index_interval`（默认 60 s）才跑一轮 —— 展开要开归档，绝不能每 5 s tick 都跑 |
| 幂等 | 标记落 `app_state`（键 `autounpack:{book_id}`，值是**源指纹** `mtime_ns:size`）：源没变就跳过；容器不可变 ⇒ 源一改指纹就变、自然重试；坏包也**无论成败都记**，不会每轮刷屏 |
| 做什么 | 复用既有安全原语 `zipkind.unpack(path)`（默认 `remove_source=False`）：**只新增文件、撞名跳过不覆盖、从不 `unlink`**，源容器原样保留 |
| 候选判据 | `format ∈ zipkind.CONTAINER_FORMATS`（`ZIP` / `RAR` / `7Z`，**唯一判据**，不手写第二份）；不用 `library.container_books()`（它每条都开归档） |
| 深度 | **一轮只解一层**（`zipkind` 的既有口径）。嵌套归档被提取出来后自己是新的书目条目，下一轮才轮得到它 —— 别把递归塞进 `unpack` |
| 配置 | `libraries.auto_unpack`（默认 `True`）：进 `config.DEFAULTS` + `server.EDITABLE` + `GET /api/config` 硬编码回显 + `GET /api/library-containers` 的 `auto_unpack`。保存配置走 `_apply_watcher_config` 热刷 `WATCHER.cfg` ⇒ **无需重启** |
| 前端 | `components/tools/LibraryCopiesPanel.vue` 顶部一个开关（初值取 `/api/library-containers`，切换 `PUT /api/config`，失败**回滚**）；**不新建**设置页分区（`settingsFields.ts` / `settingsNav.ts` 不动） |
| 契约测试 | `tests/test_auto_unpack.py`（15 例）：`.7z` 现场造真归档；`.rar` **只测判据**（造不出来，不伪造） |

