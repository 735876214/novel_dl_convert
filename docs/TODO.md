# TODO.md — 当前任务 / 优先级 / 开发进度

> **维护约定**：本文件只管「**还没做的**」。做完的**只留一行索引**（第 2 节），
> 细节一律进 `docs/roadmap-gaps-remaining.md`（活文档，最新期在末尾）—— **别再往这里抄实施记录**。
> 每条待办要带**证据**（数字、文件、复现方式），不写「优化一下性能」这种没有判据的条目。

**最后更新**：2026-10-05 —— 第 103 期**已交付但不发版**（`VERSION` 仍 `0.94.0`，连续九轮）：
**把系列 / 卷号 / 演播者接进元数据抓取线** —— 三个字段**早就建模**（`fileops.METADATA_FIELDS`、
`metascore.FIELDS` 计分、命名规则 `{series}` / `{series_index}`、Komga `seriesIndex`、系列视图都已在），
但**候选结构从一开始就没有这三个键** ⇒ 抓到的值连丢都算不上（压根没采集）。本期把候选结构 →
`metafetch._VALUE_KEYS` 字段映射 → 默认策略 → 前端策略表整条接通，顺手修两处**把值写错地方**的缺陷
（Audible 把系列名塞进 `tags`；RanobeDB 详情补全因响应套了 `book` 键而**从未生效**）。
按用户要求，本轮起**已做完的条目直接从本文件删除**（不再标 `[x]` 留痕），历史一律去 roadmap 查。

## 0. 当前状态

- HEAD = 第 94 期提交 + 第 95 期整改 + 第 96 期数据安全口径 + 第 97 期 `[low]` 清理 + 第 98 期仪表盘余留 + 第 99 期元数据抓取真机核验 + 第 100 期 EPUB 解析判定与 `dc:description` 修法 + 第 101 期 Goodreads 抓取改用 RSC payload + 第 102 期元数据抓取地基 + 第 103 期系列/卷号/演播者接线；`VERSION` = **0.94.0**
  （**九轮都刻意未升**：第 95 期清理与守卫、第 96 期数据安全补漏、第 97 期死参数/别名/零消费者端点清理、
  第 98 期仪表盘余留、第 99 期元数据抓取真 bug、第 100 期 EPUB 判定、第 101 期 Goodreads 整家失效修复、
  第 102 期元数据地基、第 103 期元数据字段接线，用户九次都选「先不发版」；单一真值源，`GET /health` 下发）；
  `CHANGELOG.md` 最新段仍是 `V0.94.0`。
- 测试基线（第 103 期）：后端 **2274 例（2249 passed / 0 failed / 0 errors / 25 skipped）**；
  前端 **67 spec / 686 例**（本期实跑全绿）。
  ⚠️ 第 85 期实测教训：**只跑相关文件看不见「改动波及别处」的问题** —— 一次私有函数重名覆盖
  （`_tag_text`）让 82 条**与本模块无关**的测试连锁失败，跑全量才发现（见 roadmap 第 85 期「踩坑」）。
  ⚠️ 长跑 pytest 必须**后台跑 + 轮询 junit**（前台会被 harness 的「长时间无输出」上限取消）。
  ⚠️ **本机跑 pytest 前必须清空全部代理变量**（`HTTP_PROXY`/`HTTPS_PROXY`/`http_proxy`/`https_proxy`/`NO_PROXY`/`no_proxy`）——
  否则 `httpx` 解析 `NO_PROXY` 里的 `[::1]` 会生成畸变代理 mount，**45 个用例假失败**（第 95 期实测，
  已写进 `AGENTS.md` §5）。
  ⚠️ **`pytest.ini` 已有 `addopts = -q`**：命令行再传 `-q` 会变 `-qq`，末行就不打印
  `N passed / M skipped` 汇总（表现是「exit 0 但拿不到计数」）⇒ 计数时**别传 `-q`**；pwsh 重定向的
  日志是 **UTF-16LE**，读要用 `encoding="utf-16"`。
  ⚠️ **不要在本仓跑 `pnpm run <script>`** —— pnpm 会自动 install 并**整套换掉** `frontend/node_modules`
  （脚本还没跑就以 `ERR_PNPM_IGNORED_BUILDS` exit 1）。要跑前端检查直接调 `frontend/node_modules/`
  里的工具，例如 `node node_modules/vue-tsc/bin/vue-tsc.js --build`。
- **可用的真实数据实例**（用户 2026-10-03 提供，随时可用来做实测）：本机 **`http://127.0.0.1:8412`**
  （`admin` / `changeme`），书目 **4 本**：三体 / 沙丘 / 银河系漫游指南 / 冒烟测试-第 91 期。
  窄屏三档冒烟一律跑它（`.codebuddy/tools/ui-smoke.ps1`，一次只传**一条**路由）。
- **删除语义（第 75 / 81 期，仍然生效）**：「删书」回收**三份**（本地原件 / 书库内成品 / 出版副本）；
  「移除书库」**默认只删登记、零文件触碰**，仅显式 `purge_files=1` 才在**后台**回收后两份并保留本地原件。
  硬约束原文见 `AGENTS.md` 第 1 节。
- ⚠️ 前端有**显式运行时依赖**：`vue-draggable-plus`（第 82 期）、
  `reka-ui` / `@vueuse/core` / `class-variance-authority` / `@lucide/vue`（第 90 期）。
  理由与例外边界见 `docs/architecture.md` 不变量第 6 条 + `docs/DESIGN.md` §9。
- ⚠️ **口径修订（第 80 期）**：「零外部请求 / 零依赖」已由**硬约束改为默认取向** —— 默认仍自托管、不拉 CDN，
  但允许**显式、可关、失败降级**地引入外部依赖与出网（见 `AGENTS.md` 第 1 节）。别再用「零依赖」当**不做**的理由。
- 上游缺口清单（`docs/roadmap-gaps-remaining.md` 第一节）已实质清空；
  新缺口来源改看 `docs/bookorbit/bookorbit-module-inventory.md`。

## 1. 待办（按优先级）

### P0 · 已立项，需独立一期

- （**空**）第 93 期交付 `online-fallback` 后，本节立项项已清空 —— 上一轮唯一挂起的那条
  （第 86 期 ⑦，在线阅读 + 「检查更新」）已实施，实施记录见 `docs/roadmap-gaps-remaining.md` 第 93 期段。
  ⚠️ 它的**形态口径**（用户 2026-10-03 拍板）落实为：**不内嵌第三方页面 / 不用 iframe**，
  只按书源规则把书**内容**取回来，用本项目自己的阅读器渲染，并**常驻来源标注**；
  ⚠️ 同批按用户要求**删除了「仅放行公版源」闸门** —— 现在只剩「下载开关」一条，
  每源的 `public` 字段降级为**标注**（不再参与过滤，后果由使用者自负）。
- （**空**）第 94 期是**用户报的 bug + 用户追加的范围**（书源导入没反应 → 多格式 + 引擎 + 安全层），
  不从本节取条目；实施记录见 roadmap 第 94 期段。本节仍为空。

### P1 · 待用户输入 / 待定判据

> 第 96 期按用户要求**删掉了三条「卡在外部样本」的待办**（书源格式四类 / 书源规则四个待样本参数 /
> `美利坚财富人生1-3059.txt` 乱码）：它们不是本项目自己能推进的事，挂在待办里只会被反复拿出来问。
> 材料与统计数字仍在 `docs/roadmap-gaps-remaining.md` 第 94 期段与第 89 期段，以及
> `docs/project-overview.md` / `docs/user-guide.md` 的「未覆盖项」—— **拿到真实样本再立项**。

> 第 98 期按用户要求**做完了「仪表盘余留」三条**（页级三态 / 快速预览补两个动作 / 上游截图比对）：
> 判据与落法见 `frontend/src/lib/dashboardPageState.ts` 与
> `docs/bookorbit/bookorbit-dashboard-styles.md` §7.8。**三条全部收口** —— 像素级比对已在收尾时
> 换成能读图的模型做完：两侧截图都看过，**结论是没有发现需要修的视觉偏差**（外壳与书架行 class
> 逐字一致、结构同序；差异只在语言 / 默认启用集合 / 分区粒度三处，均属既定范围）。
> ⚠️ 工具链变动记在 §7.8 ④：`agent-browser` 在本机**已不可用**（会挂住不返回），
> 改用本机 Edge 的 CDP 无头截图；PNG 仍**不入库**。

- [ ] **演播者（`narrators`）：Audnexus 未接线**（第 103 期真机探活后挂起，不是忘了）——
  本期只接了**真机核过**的 Audible（`narrators` 是顶层键，每项 `{"name": …}`，Dune 12 位实测）。
  `novelforge/core/metasources.py` 的 `_audnexus_entry` docstring 自称「`authors`/`narrators` 都是对象数组」
  但**从未映射** narrators / series —— 而 `api.audnexus.com` 从本机连打 3 次全是
  `[SSL: UNEXPECTED_EOF_WHILE_READING]`（与第 102 期同一条阻塞）⇒ **没核过就不声明**（第 95 期口径）。
- [ ] **Open Library 的 `series` 字段未核验**——`_OL_FIELDS` 现在**不含** `series`，
  所以这家源对本期的三个字段贡献为零。探针（`fields=key,title,series,author_name`）撞上
  本机 `ConnectTimeout`（见下面那条「间歇性不可达」）⇒ 拿到真实响应再决定要不要加。
- [ ] **Audible 的 `subtitle` 顶层键存在但未接线**——第 103 期同一份响应用真机核过
  `subtitle` **是**顶层键（`novelforge/core/metasources.py` 的 `_search_audible` 没取）。
  接它要重走本期那套四处同步（候选结构 → `_VALUE_KEYS` → 默认策略 → 前端策略表），
  且要先定策略口径：不少书库把副标题当标题的一部分，默认 `overwrite` 会改书名 ⇒ 倾向 `fill_only`。
- [ ] **`frontend/src/components/book/detail/ReadingLogTab.spec.ts:242` 全量并行偶发**
  （第 103 期实测一次 `1 failed | 685 passed`，红的是 `it('重试按钮真的会再拉一次')`）——
  **单跑该文件 + 紧接着全量复跑都是 686 passed** ⇒ 是并行下的偶发，不是本次改动破坏的。
  记在这里是防止下次误判成「刚改的东西坏了」；真要根治得查该用例的等待/重试竞态。
- [ ] **`vue-tsc` 3.3.12 前端类型检查实红**（第 103 期复核：`frontend/node_modules` 里**现装的就是
  3.3.12**，不再只是「重装后才会红」）——`frontend/src/components/book/MetadataEditor.vue:614`
  模板里的 `FIELD_LABELS[c as keyof BookMetadataFields]` 报 `TS2339: Property 'value' does not exist
  on type 'Record<keyof BookMetadataFields, string>'`（`--build --force` 恰好 1 条，`EXIT=2`）。
  `frontend/package.json` 的 range 是 `"vue-tsc": "^3.3.11"`，**3.3.11 跑 `--build --force` 是 exit 0**。
  ⇒ 两条路：把该行类型写对（模板里 `changed` 是 `ref<string[]>`），或收紧版本范围；
  本期一行未动该文件，只记录不改。

- [ ] **剩余三家抓取源仍无可解析样本**（挂起，不是忘了）—— Kobo（本机 403 + `Challenged | Kobo.com`，
  **站点主动拒绝**，与网络无关）/ Libro.fm（**AWS WAF 挑战页**，200 可达但搜索端点被拦）/
  Amazon（正则是活的，但本机命中 JS 校验页）。按第 95 期审计原话「在没有逐家真机核过的前提下改
  选择器语义，等于用『单测绿』换『线上未知』」⇒ **无样本不改选择器**。
  ⚠️ 第 101 期已把归因分开写清（WAF 可重试/降频/带 Cookie ≠ 站点改版 ≠ 站点主动拒绝），
  用户不会再误判成「站点挂了」。
  同理 `novelforge/core/fileops.py` 的 OPF 改写正则（出版副本 XML，字节等价不可证）继续保留。

- [ ] **按 ID 取详情：三家源仍未核验**（第 102 期真机探活后挂起，不是忘了）——
  `novelforge/core/metasources.py` 的 `_DETAIL_FETCHERS` 只接了**真机核过**的两家
  （iTunes `/lookup?id=`、Open Library `/works/OL…W.json`）。三家具体阻塞原因：
  **Google Books** 三个查询全部 `429`（匿名额度耗尽，`volumes/{id}` 端点没核过）/
  **Audnexus** 本机 `[SSL: UNEXPECTED_EOF_WHILE_READING]` 不可达 / **Goodreads** `GET /book/show/{id}`
  返回 `302`（反爬验证页）。按第 95 期口径「没有逐家真机核过就改选择器语义 = 用单测绿换线上未知」
  ⇒ `detail()` 对这三家如实回**明确中文回绝**（「这家来源没有按 ID 取详情的通道，请改用按书名检索」）。
  证据见 roadmap 第 102 期 §四。
- [ ] **Open Library 本机间歇性不可达**（第 102 期收尾实测，**链路问题不是代码问题**）——
  重试探针 **12/12 次全部 `ConnectTimeout [WinError 10060]`**（同日早些时候同一个 works URL
  曾返回 200），裸 `httpx.get(url, timeout=30)` 同样连不上（各耗 42 s）⇒ 不是超时太短，是这台机器
  到 `openlibrary.org` 的 TCP 连不上。**详情绑定因此保留不回撤**。日后再遇到「体检报这一家 timeout」，
  **先查链路再查代码**，别当成本期改坏了。
- [ ] **`online_candidate(book)` 不传 `cfg` 时静默返回 `None`**（既有语义，第 102 期已钉住不改）——
  `novelforge/core/metafetch.py` 的 `_cfg(cfg: dict)` 只从**传入的** dict 取 `metadata_fetch`，
  而 `online_candidate(book, cfg=None)` 默认 `None` ⇒ 看着像「这家源没结果」，实际是「压根没去查」。
  仓内真实调用方都传了（`novelforge/server.py` 的详情页路径传 `cfg=config.load_config()`），
  已由 `tests/test_config_readback_contract.py::test_不传配置时它什么都查不到是既有语义` 钉住。
  **不要**改成自动 `load_config()`（会让它从「什么都不做」变成「真的出网抓」，属有副作用的静默行为变更）。
- [ ] **`vue-tsc` 3.3.12 起前端类型检查会红**（与本期能力无关，未动）——
  `frontend/src/components/book/MetadataEditor.vue:614` 模板里的
  `FIELD_LABELS[c as keyof BookMetadataFields]` 报 `TS2339: Property 'value' does not exist on type
  'Record<keyof BookMetadataFields, string>'`；用**仓库原有的 3.3.11** 跑 `--build --force` 是 exit 0。
  ⇒ 触发条件是「重装前端依赖」，不是这行代码变了。修它要动数据编辑器模板（属另一件事），
  本轮只记录不改；`frontend/package.json` 的 `vue-tsc` 版本范围**迟早要收紧或把这行类型写对**。

### 明确「不做」（避免反复立项）

- **跨语言检索词（翻译检索词）** —— 第 91 期定级。理由：① 翻译质量不可控，会把「同名不同书」的误配率推高；
  ② 各源的语言内检索语义不同，翻译后的词未必是站内可检的形态；③ 已有「按语种重排来源顺序 + 手动指定来源」两条退路。
  设置页「元数据来源」如实标注「未支持」并写明这三条。
- Kobo 同步、邮件投递；国际化（25 语言）；多用户 / 角色 / OIDC；在线元数据的「插件市场 / 第三方源市场」（**已取消**）；
  批注跨端同步与导入（无数据源）、按设备重建批注位置、Kobo 阅读状态投影、通知清理 job、通知 SSE 网关、孤儿封面清扫；
  非 EPUB 的元数据解析（刻意不解析）；实体**删除**策略（源文件名无写入口）；`file-write`（元数据写回文件，永久不做）。
- 判据与出处：`docs/roadmap-gaps-remaining.md` 第二节 + `docs/bookorbit/bookorbit-module-inventory.md` §4.2 / §6.2 / §9。

## 2. 交付索引

> 一行一期的索引；**细节全部在 `docs/roadmap-gaps-remaining.md` 的同名期号段**（该文件的最新期在末尾）。
> 本表只回答「最近交付了什么」，不做实施记录。

| 期 | 交付（版本） |
|---|---|
| 103 | 元数据字段**接线**（用户 2026-10-05 在 ask_user_question 里选 A：`series` / `series_index` / `narrators` 三项**早就建模、消费者全在**（`fileops.METADATA_FIELDS` / `metascore.FIELDS` 的 series 4.0 + series_index 3.0 / 命名规则 `{series}` `{series_index}` / Komga `seriesIndex` / 系列视图 / `db._CLEARABLE` `_META_FIELDS` / `patch_opf_meta`），**唯独这条抓取线从未接上** —— `_entry` 是固定键白名单、`metafetch` 无映射 ⇒ 抓到了也被静默丢掉）：① 顺手修 **RanobeDB 详情补全从未生效**（真机响应套在 `book` 键里，`{**b, **fetched}` 只并进一个键 ⇒ 作者/出版社/简介**全空且不报错**、`score_candidate` 只剩书名 0.7 < 阈值 0.75 ⇒ 这家源在默认配置下**永远进不了合并**，白挂两期）② **五个同步点**（`_entry` / `_CURRENT`·`_VALUE_KEYS`·`_FINALIZE_FIELDS` / `DEFAULTS['metadata_fetch']['fields']` / 前端 `POLICY_FIELDS` / 前端**写死的 spec 断言**「不含 series」）③ 卷号**只认 `^\d+(?:\.\d+)?$`**（错值比空值严重：它喂命名规则与 Komga `seriesIndex`）、`_best_series` **取卷号最小那支**（Audible 数组顺序三次实测倒置、Goodreads item 内层 `$4d:…:series` 是引用**要二次解析**、RanobeDB 卷号 = `series.books` 位置 + 1 且 29 册核过 28/29）④ **演播者四处口径**（`_LIST_FIELDS` + `_as_list`；`merge_values` 里 **不跨源合并** —— 两个源常是两次不同录音，拼起来会造出**从未存在**的阵容；`metastore.effective`/`state` 的在线分支此前给 `"['Scott Brick']"` 这串 repr，改 `_online_value` 走 `db._parse_tags`）⑤ 三项默认 **`fill_only`**（系列参与命名规则与系列视图、抓取收益在没值的书上；演播者本地值来自音频标签=权威源；老配置整表 overwrite 的用户仍按 overwrite 走，已在 `config.py` 写明）；Audnexus（SSL EOF）/ Open Library `series`（超时）/ Audible `subtitle` 三条**未核验不接线**挂 TODO；测试 **+11 例**、后端全量 **2274 例全绿**（**不发版**，`VERSION` 仍 0.94.0） |
| 102 | 元数据抓取**地基**（用户 2026-10-05 直接提出，非从 TODO 取条目）：① 14 家源声明**收口**到 `novelforge/core/sources/`（`Provider` 数据类 + `DECLARED`，`SOURCES`/`GROUPS`/`IMPLEMENTED`/`LANG_AFFINITY`/`LANG_BROAD`/`SOURCE_ID_FIELD`/`HEALTH_SAMPLES` **7 张手工表改派生**，逐字段验算 14 家旧键全等，只多 `kind`/`rate_limit`/`cache_ttl`）② 进程内**缓存 + 按源限流**（`time.monotonic` 计时、只缓存「成功且非空」、命中浅拷贝防分数污染；`force=True` = 诊断模式**缓存与限流都旁路**，否则体检 4 路并发会被自己的 sleep 拖成**假 timeout**）③ **按记录标识取详情**（只接真机核验过的 iTunes / Open Library；Google Books 匿名 429 / Audnexus 本机不可达 / Goodreads 302 ⇒ **不声明**，如实中文回绝）④ 配置两键 `cache_ttl`（默认 `None` = 按各来源声明，不写死 600）/ `detail_fetch`（默认**关**，不改既有书的抓取结果）+ 环境变量**只兜底不覆盖** + 前端两个开关；顺带修掉一个**假配置**（`metasources.py` 从未 import `config` ⇒ `cache_ttl` 写完两期无人读，被裸 `except` 吞掉）＋ 新增 `test_metasource_registry_contract` 15 / `test_metasources_cache` 21 / `test_metasources_detail` 24 / `test_config_readback_contract` 19（**不发版**，`VERSION` 仍 0.94.0） |
| 101 | 书源网页抓取收口：**Goodreads 旧结构（`<tr itemscope>`/`bookTitle`/`authorName`）已被站点下线 ⇒ 整家恒返 0 条**，改用 React Server Components 的 **RSC flight payload** 解析（同一真样本 604317 B：0 条 → **19 条**，多作者/年份/封面/provider_id 全对，未解析引用残留 0）+ **AWS WAF 挑战页归因**与「站点改版 / 站点主动拒绝」分开（Goodreads / Libro.fm 同套防护，取决于 IP 信誉）＋ 夹具 2 个、`tests/test_metasources_scrape.py` 12→24 例（**不发版**，`VERSION` 仍 0.94.0） |
| 100 | EPUB 解析换成熟解析器**实测后删除该立项**：37 本真实第三方 EPUB（Standard Ebooks，30 本含 OPF）逐字段对比「现有正则」vs「`xml.etree.ElementTree`」——`title`/`creator`/`publisher`/`language` **0/30 不一致**、真解析器**零失败**（CDATA/DOCTYPE/非标准实体/单引号属性/疑未声明前缀 **全为 0**）⇒ 标题承诺的收益是 0，风险（`unbound prefix`/`undefined entity` 整份作废）恰是第三方 OPF 会遇到的那类；`tests/test_epub_xml_parse.py`（5 例）**保留**为将来换解析器的验收条件。另立并修掉**唯一站得住的差异**：`dc:description` 不解 HTML 实体（30/30 本实测 `html.unescape(旧) == 真解析器` 逐字成立）⇒ 新增 `_dc_description()`（解一次实体、**保留标签**），前后端可见性已证实（前端 `{{ }}` 文本插值不做二次解码）；新增 `tests/test_epub_description.py`（7 例，改动前 4 例实测会红）（**不发版**，`VERSION` 仍 0.94.0） |
| 99 | 元数据抓取**真机核验** + 三处线上真 bug：① Audible `response_groups` 带非法组名 `publisher` ⇒ 400、**整家永远 0 结果**（`publisher_name` 是**字段**，随 `product_desc` 照旧返回）② Lubimyczytac **多作者截断**（卡内多作者多个 `<a>`，旧实现三次独立 `findall` 按下标配对）③ Amazon 的 JS 校验页（`200` + `bm-verify` 跳转、**不含验证码关键词**）**静默 0 条**；Lubimyczytac 改逐卡 `bs4` + `_soup` 缺库如实回落；新增 `tests/test_metasources_scrape.py`（12 例，此前六家脆弱源解析逻辑零覆盖）+ 真机夹具；Goodreads/Kobo/Libro.fm 三家**取不到样本 ⇒ 挂起**（**不发版**，`VERSION` 仍 0.94.0） |
| 98 | 仪表盘余留三条：**页级三态**（判据 = 聚合首屏真请求：`stores/stats` 的 `loaded`/`error` + `stores/library` 的 `loading`/`booksError`；唯一实现 `frontend/src/lib/dashboardPageState.ts` + 页级骨架 / 页级错误与「一起重试」）+ **快速预览补两个动作**（「编辑元数据」深链 `?tab=metadata`，**不挂第二个 `MetadataEditor`**；「移动到书库…」复用 `BookMoveDialog`）+ **上游首页截图像素级对照完成**（收尾换能读图的模型做完；结论：无需要修的视觉偏差；`docs/bookorbit/bookorbit-dashboard-styles.md` §7.8）（**不发版**，`VERSION` 仍 0.94.0） |
| 97 | 第 95 期审计四条 `[low]` 全清：`gate_reason` 的不参与判定 `source` 形参**删除**（17 处调用点 / 11 处传参 + 2 个测试桩）/ `manager._mark` **不再写**冗余历史键 `_source`（读侧 `source_of` 保留）/ `config.LIBRARY_SOURCE_DIR` Python 别名**删除**（环境变量回退照旧，18 个测试文件改读 `LIBRARY_SOURCE_ROOTS[0]["path"]`）/ 零消费者旧式端点 `GET /content` **删除**并补 404 断言（**不发版**，`VERSION` 仍 0.94.0） |
| 96 | 数据安全两处口径落地：展开容器的「删源」改为**移入回收站**（`publish.recycle` + 台账，可还原）+ 自动落地/显式覆盖**先把被替换的文件移入回收站**（回收失败即中止、盘上零改动）；报告写实（不再对显式覆盖说「本地读不了」）（**不发版**，`VERSION` 仍 0.94.0） |
| 95 | `AGENTS.md` 新增 §7「工程原则」+ 按 `AGENTS.md` 做合规审计与整改（九处旧路径、三处死代码、文件名判据收口、视觉 token 守卫、404 断言）（**不发版**，`VERSION` 仍 0.94.0） |
| 94 | 书源导入静默失败修复 + 格式适配器轴（native / 导出 / Legado 3.x / 阅读 2.x / JSONL）+ 转换诚实闸 + 引擎能力（XPath / `##` 替换 / 索引语法 / 选择器后缀 / URL 选项字典 / 续页 / 多编码）+ 安全层（JS 沙箱 / 正则超时 / URL 导入 SSRF 闸）+ 字段去向全量报告（V0.94.0） |
| 93 | 在线阅读（接用户自己的书源）+ 章节缓存与断网降级 + 跨客户端进度 + 读满 5 章自动落地 + 单本「检查更新」；删「仅放行公版源」（V0.93.0） |
| 92 | 工具页窄屏重排：外壳去掉 `min-w-[32rem]` / 标签条改换行 + 窄屏下拉（V0.92.0） |
| 91 | TODO 台账化 + 未登录 401 探测归零 + 元数据来源权重 + 窄屏「更多」菜单 + 浮层键盘可达 + 本地导入改投递（V0.91.0） |
| 90 | 窄屏外壳侧栏：抽屉 / 图标条 / 拖宽 / ⌘B（V0.90.0） |
| 89 | TXT 上传假报错 + 正文不乱码（V0.89.0） |
| 88 | 书库加载提速（请求路径 + 前端感知）+ 分页与无限滚动（V0.88.0） |
| 87 | `.zip` 内容分派 + 重名与重复判定重构 + 格式能力矩阵（V0.87.0） |
| 86 | 书源体系对齐 legado / Mihon + 书籍追更（V0.86.0） |
| 85 | 目录体系：本地「卷 / 段」解析 + 官方书城目录覆盖（V0.85.0） |
| 84 | 自动更新加固：失败退避 / 启动即检 / 更新前备份（V0.84.0） |
| 83 | 仪表盘余留项：库范围筛选 / 封面动画 / 第 13 件部件 / 快速预览（V0.83.0） |
| 82 | 首页（仪表盘）逐项对齐上游 BookOrbit（V0.82.0） |
| 81 | 「移除书库」改为「只删登记」+ 长文件操作后台化 + 回收站还原（V0.81.0） |
| 80 | `update` 段每个键都真有读点 + 解除「零外部请求 / 零依赖」硬约束（V0.80.0） |
| 79 | 一级子文件夹内「同前缀 + 尾部编号」合并为合集（V0.79.0） |
| 78 | 版本唯一真值源改为仓库根 `VERSION`（V0.78.0） ⚠️ 无逐期段，见 `CHANGELOG.md` |
| 77 | 移除「按格式归库」（跨库移动保留） |
| 76 | EPUB 插图不显示 + 还原书内排版 |
| 75 | 开关圆点固定白色 + 删除语义重定义（三份一起回收） |
| 74 | 新建书库向导并入编辑口径（3 页签） ⚠️ 无逐期段，见 `CHANGELOG.md` / 当日日志 |
| 73 | 漫画 / 有声书「序号单元」合并成书 + 连续阅读 |
| 72 | TXT 阅读全乱码（编码样本截断）+ 长章书分章退化 |
| 71 | 探索发现做扎实（闸门真生效 / 逐源状态 / 同名合并 / 真分页） |
| 70 | 收书目录「上传」按钮 + 全站开关胶囊收敛为唯一实现 |
| 69 | 滚动模式改成「跨章连续流」 |
| 68 | 列表不发简介（载荷 −69%）+ 迁移预览提速去重 |
| 67 | 提速验证与收尾：响应 gzip + 并发请求去重 |
| 66 | 阅读器「自动续接」三处收敛为单一真值源 |
| 65 | Book Dock 一级入口 + 顶栏图标行 + 重命名 / 匹配书库 |
| 64 | 书卡 ⋮ 菜单 + 快速预览 + 删书（只回收不真删） |
| 63 | 详情页骨架重做 + 阅读追踪数据层 + 批注位置锚 |
| 62 | 书目索引落库（42 秒 → 毫秒级）+ PostgreSQL 可选后端 + Redis 缓存 + 增量刷新 stat 收敛 |

**更早的期次**：本仓无逐期记录（台账从第 60 期起）。

## 3. 排期候选（未立项）

- 第 1 节 P0 目前**已清空**（第 93 期交付 `online-fallback`）；第 96 期取自**第 95 期审计批次 8**、
  第 97 期取审计的四条 `[low]`、第 98 期取 P1「仪表盘余留」、第 99 期取 P1「书源网页抓取」、
  第 100 期取 P1「EPUB 解析重试」（**实测后删除该立项**）、第 101 期取 P1「书源网页抓取」的剩余三家
  （Goodreads 已收口，另两家缺样本）、第 102 期由**用户直接立项**（元数据抓取地基，不从 TODO 取）。
  ⚠️ 第 102 期按拍板口径**只做了地基、零新源**：**分期做**（用户原话），
  微信读书一家中文源与其余能力留待后续期次；`docs/roadmap-gaps-remaining.md` 第 102 期段
  已写清「本期刻意不做」的边界（不新建 providers 包 / 不搬 1833 行解析实现 / 不改 `metascore` 计分 /
  不接 series / 不装 Calibre 运行时）。
  ⚠️ 下一期从 P1 取时**只剩两条**：`novelforge/core/fileops.py` 的 OPF 改写正则（**字节等价不可证**，
  须先证明等价才动）、「书源网页抓取：系列信息没有接进候选」（**新立项**，要动候选结构 →
  `_VALUE_KEYS` → 收尾模式 → OPF 写入四处）；另有三条**挂起**（Kobo / Libro.fm / Amazon 缺样本；
  三家源的按 ID 详情通道未核验；Open Library 本机链路间歇不通）。或按用户新需求立项。
- 若要做重投入项（例如再次跑大库基准、或做 PG / Redis 相关专项），**先量化再动手**
  —— 本项目已在第 61 期明确：没有指标不许凭感觉优化。
