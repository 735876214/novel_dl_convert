# TODO.md — 当前任务 / 优先级 / 开发进度

> **维护约定**：本文件只管「**还没做的**」。做完的**只留一行索引**（第 2 节），
> 细节一律进 `docs/roadmap-gaps-remaining.md`（活文档，最新期在末尾）—— **别再往这里抄实施记录**。
> 每条待办要带**证据**（数字、文件、复现方式），不写「优化一下性能」这种没有判据的条目。

**最后更新**：2026-10-08 —— 第 116 期**修可动手待办：多值字段上限按字段分 + 前端 flaky 超时**：
用户原话「**修一下可动手待办**」—— 把 §1 A 组那三条消化掉。① 多值字段（`tags` / `narrators`）
原先在**候选侧与合并侧各写死一个 8**（同一判据的两份实现），收敛成 `metasources.MULTI_VALUE_MAX`
**一张表**并按字段取值：题材仍是刻意的 8 项策展上限，**演播者放宽到 32**（第 115 期真机
Audible《Dune》**12 位**演播者被砍成 8 位的**丢事实**就此修掉）；② 前端全量并行下
`ReadingLogTab.spec.ts` 的偶发 `Test timed out in 5000ms` 收到 `testTimeout: 15000`（根因是
happy-dom **环境创建**成本，见 roadmap 第 116 期段）；③ `fileops.py` 的 OPF 改写正则按第 95 期
审计结论**保留**，从 A 组挪进 C 组（A 组因此**清空**）。
历史：第 115 期核验演播者（摘掉 Audnexus、Audible 接按 ASIN 取详情）；`VERSION` 仍 `1.3.0`（本期**不发版**）。

## 0. 当前状态

- HEAD = 第 116 期修可动手待办（多值字段上限按字段分 + 前端 flaky 超时）（第 95–115 期逐期历史见 §2 与 `git log --oneline`）；`VERSION` = **1.3.0**
  —— 单一真值源，`GET /health` 下发；v0.x 阶段「第 N 期 = V0.N.0」的约定自 V1.0.0 起终止，改为**按里程碑发版**
  （第 112 期里程碑 = FB2 直读 + 容器自动展开，`CHANGELOG.md` 最新段 `V1.3.0 — 2026-10-07` 即取自它）。
- 测试基线（第 116 期实测）：后端 **2411 例（2385 passed / 0 failed / 0 errors / 26 skipped）**，全量 296 s；
  前端 **69 spec / 717 例**、`vue-tsc --build --force` exit 0（本期只改 `vite.config.ts` 里的
  **测试**配置（`testTimeout`），不动任何源码 ⇒ 产物**逐字节不变**（build + deploy 跑过，
  `git status` 里 `novelforge/static/v2` 零改动可证）；文件数与例数不变、无需动 `EXPECTED_SPECS`）。
- ⚠️ **本机运行陷阱不在这里重抄** —— 清空全部代理变量 / 别加 `-q` / 别跑 `pnpm` / 本机 DNS 被污染 /
  长跑 pytest 后台跑 + 轮询 junit / 新增前端 spec 要登记 `EXPECTED_SPECS` / 只跑相关文件看不见连锁失败：
  **一律看 `AGENTS.md` §5 与 §4**。
- **可用的真实数据实例**：本机 **`http://127.0.0.1:8412`**（`admin` / `changeme`，书目 4 本 —— 三体 / 沙丘 /
  银河系漫游指南 / 冒烟测试-第 91 期）；窄屏三档冒烟跑 `.codebuddy/tools/ui-smoke.ps1`（一次只传**一条**路由）。
- **数据安全语义**（第 75 / 81 期，硬约束）：「删书」回收**三份**；「移除书库」**默认只删登记、零文件触碰**，
  仅显式 `purge_files=1` 才在后台回收后两份并保留本地原件；源不可变、软删除 —— 原文见 `AGENTS.md` §1。
- ⚠️ **口径修订（第 80 期）**：「零外部请求 / 零依赖」由**硬约束降为默认取向**（默认仍自托管、不拉 CDN，
  但允许**显式、可关、失败降级**地引入）—— 别再用「零依赖」当**不做**的理由；同见 `AGENTS.md` §1。
- **前端显式运行时依赖**（`vue-draggable-plus` / `reka-ui` / `@vueuse/core` / `class-variance-authority` /
  `@lucide/vue`）：理由与例外边界见 `docs/architecture.md` 不变量第 6 条 + `docs/DESIGN.md` §9。
- 上游缺口清单已实质清空；新缺口来源改看 `docs/bookorbit/bookorbit-module-inventory.md`。

## 1. 待办（按优先级）

### P0 · 已立项，需独立一期

- （**空**）本节自第 93 期起清空 —— 那期交付了 `online-fallback`（上一轮唯一挂起的第 86 期 ⑦
  「在线阅读 + 检查更新」），**形态口径**（用户 2026-10-03 拍板）为**不内嵌第三方页面 / 不用 iframe**：
  只按书源规则取回书**内容**、用本项目自己的阅读器渲染并**常驻来源标注**；同批删掉「仅放行公版源」闸门
  （`public` 降级为**标注**，不再参与过滤，后果由使用者自负）。第 94 期是**用户报的 bug + 追加范围**
  （书源导入没反应 → 多格式 + 引擎 + 安全层），也不从本节取条目。
  两期实施记录见 `docs/roadmap-gaps-remaining.md` 第 93 / 94 期段；**第 95–115 期同样没有从本节取过条目**。

### P1 · 待办（分三组：可动手 / 挂起 / 钉住不改）

> **已办结的条目不留在这里** —— 本文件只管「还没做的」。第 96 / 98 / 112 / 113 / 114 / 115 / 116 期
> 做完的那几条，各自的「为什么删 / 结论是什么」都在 §2 与 `docs/roadmap-gaps-remaining.md`
> 的同名期号段里，别在这里再抄一遍。唯一要留住的判据：**卡在外部样本上的事，拿到真实样本再立项**
> （第 96 期口径）。

#### A · 可动手（本仓内，有判据）

- （**空**）第 116 期把最后两条做完了 —— 多值字段上限（`tags` 8 / `narrators` 32）与前端
  全量并行下的 flaky 超时；唯一没动的那条（`fileops.py` 的 OPF 改写正则，第 95 期审计判「保留」）
  已按结论挪进 C 组。**这一类目前没有条目** —— 新条目照文件头那条维护约定走：
  带**证据**（数字 / 文件 / 复现方式），别写「优化一下」。见 roadmap 第 116 期段。

#### B · 挂起（外部样本 / 本机环境 —— 是环境问题，不是技术债）

- [ ] **Open Library 的 `series` 字段未核验**——`_OL_FIELDS` 现在**不含** `series`，
  所以这家源对 `series` / `series_index` / `narrators` 三个字段的贡献为零。探针
  （`fields=key,title,series,author_name`）撞上本机 `ConnectTimeout`（见下面那条「DNS 被污染」）
  ⇒ 拿到真实响应再决定要不要加。
- [ ] **剩余三家抓取源仍无可解析样本**（挂起，不是忘了）—— Kobo（本机 403 + `Challenged | Kobo.com`，
  **站点主动拒绝**，与网络无关）/ Libro.fm（**AWS WAF 挑战页**，200 可达但搜索端点被拦）/
  Amazon（正则是活的，但本机命中 JS 校验页）。按第 95 期审计原话「在没有逐家真机核过的前提下改
  选择器语义，等于用『单测绿』换『线上未知』」⇒ **无样本不改选择器**。
  ⚠️ 第 101 期已把归因分开写清（WAF 可重试/降频/带 Cookie ≠ 站点改版 ≠ 站点主动拒绝），
  用户不会再误判成「站点挂了」。
- [ ] **按 ID 取详情：两家源仍未核验**（第 102 期真机探活后挂起，不是忘了；第 115 期更新）——
  `novelforge/core/metasources.py` 的 `_DETAIL_FETCHERS` 已接了**真机核过**的三家
  （iTunes `/lookup?id=`、Open Library `/works/OL…W.json`、**第 115 期新接的 Audible
  `/1.0/catalog/products/{asin}`**）。剩下两家的具体阻塞原因：
  **Google Books** 三个查询全部 `429`（匿名额度耗尽，`volumes/{id}` 端点没核过）/
  **Goodreads** `GET /book/show/{id}` 返回 `302`（反爬验证页）。
  （原先列在这里的第三家 **Audnexus 已在第 115 期整家删除** —— 声明域名 NXDOMAIN、真接口
  `api.audnex.us` 又**没有检索路由**，见 roadmap 第 115 期段。）
  按第 95 期口径「没有逐家真机核过就改选择器语义 = 用单测绿换线上未知」
  ⇒ `detail()` 对这两家如实回**明确中文回绝**（「这家来源没有按 ID 取详情的通道，请改用按书名检索」）。
  证据见 roadmap 第 102 期 §四、第 115 期段。
- [ ] **Open Library 本机解析被污染（不是本站的链路问题）**（第 104 期定因，**改自第 102 期的「链路问题」**）——
  重试探针 12/12 次全部 `ConnectTimeout [WinError 10060]`，裸 `httpx.get(url, timeout=30)` 也连不上
  （各耗 42 s）；第 104 期查了 DNS：本机 `openlibrary.org` → **`31.13.112.4`**（Facebook 段），
  而 `8.8.8.8` → `199.59.149.201`（正确）；`hosts` 无自定义行、`1.1.1.1` 无应答 ⇒ **上游 DNS 污染**。
  ⇒ 该家的真机核验（含 `series` 字段、`/works/OL…W.json` 详情）要等能解析对之后再谈；
  体检现在会把它报成 `dns_polluted` 而不是「超时」。**详情绑定因此保留不回撤**。
- [ ] **`ubuntu-latest` 将于 2026-10-19 起迁移到 Ubuntu 26**（第 105 期的 notice，**仍未发生**）——
  那天之后再看一次 `Build and Push Image` 是否仍绿。它与 action 的 node24 运行时**无关**
  （那是 runner 镜像的迁移）⇒ 第 114 期那次升级不解决它。

#### C · 钉住不改（语义已定 / 已知边界，写在这里免得反复讨论）

- [ ] **`frontend/src/components/book/detail/ReadingLogTab.spec.ts` 全量并行偶发超时**（第 116 期
  **已缓解**，不是修好）—— 第 103 期实测 `1 failed | 685 passed`、第 104 期又复现一次（红的是同文件
  :233 `it('接口失败 → 给重试…')`），**都是 `Test timed out in 5000ms`**；单跑该文件 12 例 **453 ms 全绿**、
  紧接着全量复跑 **686 passed** ⇒ 不是用例坏了。根因是 vitest 给**每个 spec** 各建一次 happy-dom
  （`isolate` 默认开；第 104 期记 `67 次 / 256.61 s / 占 55%`，第 116 期复测 `69 次 / 72.75 s / 48%`），
  这几秒记在**恰好排在它后面**的那条用例头上 ⇒ **命中的用例会换，别按行号认领**。
  第 116 期把 `vite.config.ts` 的 `test.testTimeout` 收到 **15 s** 覆盖这个抖动；
  ⚠️ **再红先怀疑环境创建成本与机器负载，别当「刚改的东西坏了」**。要再压这块成本得动
  `pool: 'vmThreads'` / `isolate: false`（会改 717 例的隔离语义，属另一件事）。
- [ ] **`novelforge/core/fileops.py` 的 OPF 改写正则**（出版副本 XML，**字节等价不可证**）——
  第 95 期审计**判定保留**（`docs/agents-audit-95.md:183`、roadmap 第 95 期段「六、未做及原因」）：
  「出版产物不得变化」是硬约束，换成 `ElementTree` 拿不出字节等价证明 ⇒ **不动**。
  它与 B 组那几条抓取源无关，是**另一件事**；想重试的人先读上面两处。
- [ ] **`online_candidate(book)` 不传 `cfg` 时静默返回 `None`**（既有语义，第 102 期已钉住不改）——
  `novelforge/core/metafetch.py` 的 `_cfg(cfg: dict)` 只从**传入的** dict 取 `metadata_fetch`，
  而 `online_candidate(book, cfg=None)` 默认 `None` ⇒ 看着像「这家源没结果」，实际是「压根没去查」。
  仓内真实调用方都传了（`novelforge/server.py` 的详情页路径传 `cfg=config.load_config()`），
  已由 `tests/test_config_readback_contract.py::test_不传配置时它什么都查不到是既有语义` 钉住。
  **不要**改成自动 `load_config()`（会让它从「什么都不做」变成「真的出网抓」，属有副作用的静默行为变更）。

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
| 116 | 修可动手待办：多值字段上限按字段分 + 前端 flaky 超时 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 116 期段 |
| 115 | 核验演播者：摘掉 Audnexus、Audible 接按 ASIN 取详情 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 115 期段 |
| 114 | CI 的 5 个 action 升到 Node 24 运行时 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 114 期段 |
| 113 | Audible `subtitle` 接线；TODO §0 精简 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 113 期段 |
| 112 | FB2 直读 + 容器自动展开 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 112 期段 |
| 111 | `.rar`/`.7z` 容器按内容分派：与 `.zip` 同一套判据（图片档归一 CBZ、其余进待展开），`.7z` 用纯 Python 的 `py7zr`；「缺解压能力」收敛成 `comics.backend_problem` 一处、503 说清缺什么；三类库白名单 + `SCAN_RULE_VERSION` 3→4。⚠️ 教训：`analyze` 把未分派形态的 format 写死 `"ZIP"` 会让待展开清单**静默漏掉**新容器 —— 判据要派生不要手写 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 111 期段 |
| 110 | MOBI/AZW3/AZW 直读（解包，不转换）：把书自身的 KF8 内容解包到缓存目录直读（不进书库、源只读），KF8 出真 EPUB 全复用、纯 MOBI6 出 HTML 如实降级；`.azw` 进白名单（`SCAN_RULE_VERSION` 2→3）。⚠️ 延迟导入必须放分支第一行，否则 `UnboundLocalError` 全线 500 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 110 期段 |
| 109 | 发版 V1.0.0：把第 95–108 期的积累一次性发布 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 109 期段 |
| 108 | 仪表盘直读 + 侧栏抽屉判据按设备 + 阅读沉浸 + 设置面板点外关（用户 m09721 追问响应式后补横扫 17 视口 × 5 路由 = `FAILS=0`，并修掉窄屏设置面板跑出视口的既有缺陷）—— 细节见 `docs/roadmap-gaps-remaining.md` 第 108 期段 |
| 107 | 自动化收尾：落位器 + 三方对账 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 107 期段 |
| 106 | **记忆体系精简（收尾只写两处）**（用户 2026-10-06 直接提出 m08584：做完一期要把同一段「根因 / 证据 / 修法 / 核验」抄 **5 处**（`docs/roadmap-gaps-remaining.md` 本期段 / `MEMORY.md` / `MEMORY-REF.md` / `memory/YYYY-MM-DD.md` 当日日志 / `docs/TODO.md` 头部+§0+§1+§2+§3）+ `AGENTS.md` 基线；经 `ask_user_question` 选定**方案 B「先把记忆三件合并，再谈自动化」**）：① `.codebuddy/memory/MEMORY.md`（48903 B / 86 行 → **8588 字符 / 92 行**）只留**铁律小节 + 一期一行索引**，逐期索引正文（24857 字符）移入存档；② `.codebuddy/memory/MEMORY-REF.md`（207485 B / 1777 行 → **14635 字符 / 122 行**）保留行 1–116 主题部分，改成**按主题的域手册**（逐期原文 106673 字符移入存档，**不再按期号追加**，只有新领域知识才补小节）；③ **取消当日日志**（2026-10-06 起不再新建 `memory/YYYY-MM-DD.md`，既有日期文件保留为历史）；④ 逐期铁律全文 → 新存档 `.codebuddy/memory/MEMORY-PERIODS.md`（**132070 字符 / 1696 行**，A=原 `MEMORY.md` 索引 75–105 期、B=原 `MEMORY-REF.md` 逐期原文 53–105 期，**两份原样合入**、已在文件头标注 81–105 期重叠属历史、未合并以免丢信息；缺 62–65 / 74–78 / 80 期只在 A 里有）。⚠️ **文件名一律不动** —— 它们被 `AGENTS.md:15`、`AGENTS.md:165`、`docs/development.md:79`、`novelforge/core/sqlcompat.py:7`（引 `MEMORY.md`「自动化测试」小节，该小节**保留**）、`tests/test_engine_urlspec.py:205`、`tests/test_library_count_contract.py:19` 引用。规则落点：`AGENTS.md` §0 第 3 条（读哪三份）+ §6「**每期收尾只写两处（第 106 期起，用户 m08584 要求精简）**」（① roadmap 本期段 = **唯一叙事** ② `MEMORY.md` 索引加一行 ③ 不再建当日日志 ④ 不再按期号追加 `MEMORY-REF.md` ⑤ 存档只读、按 `### 第 N 期` 搜 ⑥ `docs/TODO.md` 与 `AGENTS.md` 基线数字仍同批更新）、`docs/development.md` 回归清单同条。**守恒核验**：脚本 `nf_p106_restructure.py` 写前断言索引标记/逐期标记各唯一、写后断言旧索引与逐期原文**逐字**仍在存档且**不在**两个新文件里（输出 `moved_index=24857 moved_periods=106673`、两条 `check → True`）；`python tests/check_doc_anchors.py` **exit 0**（纯文档改动，未动代码与用例 ⇒ 基线仍 2311 例）。**没做**：自动化（脚本生成索引 / 漂移校验）按用户选择**留到下一轮**（**不发版**，`VERSION` 仍 0.94.0） |
| 105 | **CI「Build and Push Image」全失败修好**（用户 2026-10-06 直接立项）：先查历史 —— 该工作流 **run 288–317 全 failure**（2026-10-03 起），最后一次 success 是 run 217（2026-10-01，sha `99ee3494`）⇒ **既存故障**，与第 104 期那几笔提交无关。失败步骤 = job `build` 第 7 步 `Build and push`（`docker/build-push-action@v6`）；annotation **只给最后一行**，真正的 vite 报错要用本机 `git credential fill` 的 token 下 `GET /actions/jobs/<id>/logs`（⚠️ 返回**纯文本日志**、不是 zip）才拿到：`[UNLOADABLE_DEPENDENCY] Could not load src/components/ui/input`（`SidebarInput.vue:4`）。**根因**：`.gitignore` 的 `input/` **不带前导斜杠** ⇒ 匹配**任意层级**同名目录 ⇒ 第 90 期新增的 `frontend/src/components/ui/input/`（`Input.vue` + `index.ts`）**从未入库**；本机文件一直在 ⇒ 本地 `npm run build` / `vue-tsc` / 单测**永远绿**，CI 从 clone 构建才断链。**修法**：运行时目录全部锚定仓库根（`/input/` `/output/` `/cookies/` `/cache/` `/config/cookies/` `/config/cache/`）+ 补回那两个文件，**刻意不加任何兜底**（不在 workflow 里 `git add -f`、不给 vite 加 alias）。**防回归**：`tests/test_source_tracking_contract.py` 两例（源码树不许有被 `.gitignore` 忽略的文件；`@/` 别名导入必须落在**已入库**路径上），**「改动前会红」已实测**。**核验口径**：在本工作区构建成功**不算证明**（工作区本来就有那两个文件）—— 必须 `git clone` 到临时目录（只有已入库内容）再跑 `docker build --target frontend`（实测 `#10 RUN npm run build` **真执行**、`✓ built in 2.44s`、EXIT=0）。后端全量 **2311 例全绿**（+2）。**CI 已转绿**：推送后 `Build and Push Image` run **318**（id `37394372273`，head_sha `ea2ad51`，约 11 分钟）conclusion **success** —— job `build` 第 7 步 `Build and push` 与第 8 步 `Ensure package is public` **全 success**（失败时是第 7 步 failure / 第 8 步 skipped）⇒ **自 run 217（2026-10-01）起连续 30 次失败终止**（**不发版**，`VERSION` 仍 0.94.0） |
| 104 | 出网**失败归因**（用户 2026-10-06 在 ask_user_question 里选 A）+ 前端类型红收口：先查出**本机 DNS 被上游污染**（`openlibrary.org`→`31.13.112.4` / `www.goodreads.com`→`128.242.240.253`，而 `8.8.8.8`→`199.59.149.201` / `199.59.148.6`，`hosts` 无自定义行、`1.1.1.1` 无应答）—— 此前一律报「超时」，用户会去修一个**根本没坏**的源（仓规：误报比不测更糟）。新增叶子模块 `novelforge/core/netdiag.py`：① **数据路径只做纯函数分类**（`classify_exc` / `describe_exc`，零 I/O，`search()` 失败多回一个 `fail` 键）② **诊断路径才交叉核对**（手写 UDP DNS 查询本机 vs `8.8.8.8`/`1.1.1.1`，按 host 缓存 60 s；两个 I/O 缝可注入）③ 污染 ⇒ 结论升级 `dns_polluted` 并**把两边地址写进原因**；公共解析器答不上来 ⇒ 如实说「无法交叉核对」，**未知 ≠ 污染**。`HEALTH_KINDS` 12→17 类（`dns` / `dns_polluted` / `tls` / `proxy` / `connect_timeout`，中文文案由后端下发，前端零新文案；`healthClass` 把这四类归**琥珀**＝本机环境问题，别再指着站点）。顺带**收口 `vue-tsc` 3.3.12 的 `TS2339`**：`MetadataEditor.vue` 五处重复的字段中文名（其中 :614 在模板内联箭头里）收敛成一个 `labelOf(k: string)` ⇒ `--build --force` **exit 0**（此前 `.vue(614,40)` 恰 1 条、EXIT=2）。测试 **+35 例**（`tests/test_netdiag.py` 23 / 健康归因 12，含把 `[Errno -2] Name or service not known` 从 `network` **故意改判** `dns`）、新增 `tests/conftest.py` 的 `_no_live_dns_in_tests`（全测试进程**零真实 DNS**）；后端全量 **2309 例全绿**、前端 686 例（**不发版**，`VERSION` 仍 0.94.0） |
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

## 3. 排期候选（含逐期立项来源）

- 第 1 节 P0 目前**已清空**（第 93 期交付 `online-fallback`）；第 96 期取自**第 95 期审计批次 8**、
  第 97 期取审计的四条 `[low]`、第 98 期取 P1「仪表盘余留」、第 99 期取 P1「书源网页抓取」、
  第 100 期取 P1「EPUB 解析重试」（**实测后删除该立项**）、第 101 期取 P1「书源网页抓取」的剩余三家
  （Goodreads 已收口，另两家缺样本）、第 102 期由**用户直接立项**（元数据抓取地基，不从 TODO 取）、
  第 103 期取 P1「书源网页抓取：系列信息没有接进候选」（**该条已交付并删除**）、
  第 104 期由**用户直接立项**（出网失败归因 + 前端类型红收口，我给的推荐项，不从 TODO 取）、
  第 105 期同样由**用户直接立项**（修 GitHub Actions「Build and Push Image」全失败 ——
  根因不在构建本身，而是 `.gitignore` 把 `frontend/src/components/ui/input/` 静默忽略、从未入库，
  详见 roadmap 第 105 期段）、第 106 期仍由**用户直接立项**（记忆体系精简 / 收尾只写两处 ——
  痛点来自第 104、105 期收尾的重复劳动，方案经 `ask_user_question` 由用户选定 B；
  **其中的「自动化」半场按用户选择留到下一轮**，可直接作为候选）、第 107 期同样由**用户直接立项**
  （用户 m08782「再谈自动化」，切到 plan mode 写计划并获批）：收尾的**落位器 + 三方对账**
  （`tests/period_close.py` 的 `new` / `check`），见 roadmap 第 107 期段 ——
  ⚠️ 这条正是第 106 期收尾时明确留给用户的那**两件事（索引行生成 + 三方漂移校验）**，属**已知候选**而非新需求，
  立项时它还没写进本节。
  第 108 期仍由**用户直接立项**（用户 m09151 报的四条阅读动线问题：仪表盘点封面还弹浮层 / 手机横屏与平板
  侧栏常驻 / 阅读页仍顶着侧栏与顶栏 / 设置面板点旁边收不掉；五处歧义经 m09230 全部选推荐项）——
  属**用户体感反馈**，不从 TODO 取，见 roadmap 第 108 期段。
  第 109 期仍由**用户直接立项**（用户 m09886 一句「发版v1.0.0」）：把第 95–108 期连续十四轮
  「只提交、不发版」的积累一次性发布为 **V1.0.0**（`CHANGELOG.md` 只写一段话里程碑说明、镜像多推
  `:1.0.0` 版本 tag —— 两个决策经 `ask_user_question` 均由用户选推荐项），见 roadmap 第 109 期段。
  第 110 期由**用户直接立项**（原话「mobi直接阅读，不进行转化」，m00255；同一轮还立下工程口径
  「有成熟功能和模块的，不要自研」，m00226）；第 111 期接着做**同一需求的「阶段②」**
  （用户 m00875「接着做阶段②」，把 `.rar` / `.7z` 归到与 `.zip` 同一套容器判据）；第 112 期取
  **第 110 期计划里剩下的阶段③④**（FB2 直读 + 容器自动展开，三项口径由用户拍板）；
  第 113 期由**用户直接立项**（原话「todo的当前状态太长了，精简一下。精简完成做一下剩下的任务」——
  Audible `subtitle` 接线）；第 114 期仍由**用户直接立项**（原话「修一下 CI 的 5 个 action
  仍跑在 Node 20 运行时」）；第 115 期取 §1 挂了四期的那条（用户原话「核验 演播者（narrators）」，
  落地为「摘掉 Audnexus、Audible 接按 ASIN 取详情」）；第 116 期由**用户直接立项**
  （原话「修一下可动手待办」—— **直接取 §1 A 组**那三条，其中两条当轮做完、OPF 正则按审计结论
  挪进 C 组）。各期细节见 roadmap 同名期号段。
  ⚠️ 第 102 期按拍板口径**只做了地基、零新源**：**分期做**（用户原话），
  微信读书一家中文源与其余能力留待后续期次；`docs/roadmap-gaps-remaining.md` 第 102 期段
  已写清「本期刻意不做」的边界（不新建 providers 包 / 不搬 1833 行解析实现 / 不改 `metascore` 计分 /
  不接 series / 不装 Calibre 运行时）。
  ⚠️ **§1 的 A 组（可动手）现已清空**（第 116 期把多值字段上限与前端 flaky 超时两条做完，
  唯一没动的 `fileops.py` OPF 改写正则按第 95 期审计结论挪进 C 组「钉住不改」）。
  所以下一期**没有现成的可动手条目** —— 要么从下面**挂起**那几条里挑（条件已具备才立项），
  要么按用户新需求立项。挂起项的最新状态：Kobo / Libro.fm / Amazon 缺样本；**两家**源的按 ID
  详情通道未核验（第 115 期已接 Audible、摘掉 Audnexus，故由三家降为两家）；`openlibrary.org`
  等三家本机 **DNS 被上游污染** —— 这是**环境问题不是代码问题**，别当技术债还；
  `ubuntu-latest` **2026-10-19 起迁 Ubuntu 26** 仍在**等日期**（第 105 期只登记，见 §1 B 组）。
  历史口径补充：「把 CI 的 5 个 action 升到最新大版本」**已于第 114 期完成**（5 个一起升 +
  新增离线契约测试钉住）。
- 若要做重投入项（例如再次跑大库基准、或做 PG / Redis 相关专项），**先量化再动手**
  —— 本项目已在第 61 期明确：没有指标不许凭感觉优化。
