# TODO.md — 当前任务 / 优先级 / 开发进度

> **维护约定**：本文件只管「**还没做的**」。做完的**只留一行索引**（第 2 节），
> 细节一律进 `docs/roadmap-gaps-remaining.md`（活文档，最新期在末尾）—— **别再往这里抄实施记录**。
> 每条待办要带**证据**（数字、文件、复现方式），不写「优化一下性能」这种没有判据的条目。

**最后更新**：2026-11-03 —— 第 256 期**持续审计第十五轮：「删不掉的必须如实回报」这条纪律，另外两条路没遵守**：回收站那条第 141 期专门修过「**说清空了却没清干净**」比「没清干净」更坏（回收站是「删除即回收」承诺的**最后一道防线**）—— 但**同一条纪律**在这条路上没遵守：① `POST /api/cache/clear`（清缓存）此前是「逐个 `except Exception: continue` + 外层 `except: pass`」⇒ 删不掉的文件（容器里 root 建的只读文件、NFS 上的 busy 文件）**留在盘上**，而回执照旧说「已清理缓存 N 项」⇒ **用户永远不知道缓存里还剩东西** ⇒ 缓存目录**越攒越多**（而用户以为每次都清干净了）。实测：造一个删不掉的缓存文件（`monkeypatch` 挡 `pathlib.Path.unlink` —— ⚠️ Windows 上「只读属性」**不影响删除**，只能靠挡方法）⇒ 回执 `removed=1`、**残留不可见**。② **同一个洞的第二层**：后端第 141 期就给回收站那条加了 `failed`，但**前端从头到尾没读它** ⇒ 回收站里还剩东西，界面照样只说「已清空、释放 N B」—— **后端给了不说，等于没给**。修法：清缓存的回执带 `failed`（删不掉的条目 + 原因）、有残留时 `ok=False`、失败写进活动日志；前端两条都读 `failed`，有残留时明说「**N 项没删掉**（仍在盘上）」，全删得掉时照旧说「已清理缓存 N 项」（**不吓唬用户**）；顺带把**回收站那条的成功分支**也补上 `failed: []` —— 此前**只有失败分支**才带这个键 ⇒ 响应**形状随结果变** ⇒ 现在**形状恒定**，前端只读一处判据。下一轮候选见 roadmap 第 256 期段（**`_health_checks()` 整体该包 try**排第一 —— 本轮已实测：任何一项探针抛异常都会让 `/health` 500 ⇒ Docker HEALTHCHECK 失败 ⇒ 容器被反复重启）。
历史：第 255 期持续审计第十四轮：自定义字段的值也没有长度上限（1 MB 的值能存进库里）；`VERSION` 仍 `1.4.7`（无版本变更时保留这句）。

## 0. 当前状态

- HEAD = 第 219 期（审计遗留三条：目录客户端封面 / pip 缓存锁 / App.vue 结构）
  + 第 218 期智能书架：服务端求值 + 规则表达力 + 第 217 期成就 ETA + 第 216 期自定义图标库
  + 第 215 期成就展示柜 + 第 214 期元数据批量抓取 + 第 213 期镜像瘦身开关与构建缓存
  + 第 212 期书架多级排序 + 第 211 期书目导出粒度 + 第 210 期收藏夹分页 + 第 209 期仪表盘偏好服务端
  + 第 208 期封面缩略图判据改字节 + 第 205 期审计归档按天保留 + 第 200–204 期封面变更审计 /
  阅读状态 8 档 / 作者抓取配置 / 跨库移动指纹 / 元数据权重可配 + 第 194–199 期 ⌘K 命令面板 /
  PDF 搜索 / KOReader / 成就提示语 / 审计导出 + 第 189–193 期 EPUB 搜索 / 通知中心 / 扫描历史 /
  登录审计 / 元数据缓存统计 + 第 185–188 期播客合集 / 智能播放列表 / 目录搜索 / read-along
  + 第 179 期体积与加载速度（按需化 / 静态预压缩 / 镜像与仓库瘦身）+ 第 173–178 期播客订阅 /
  管理 / 下载 / 进度 / 书签 / 连播 + 第 164–172 期读路径审计 / 文件名提取 / 有声书书签与倍速 /
  批量事务 / Phase 2A 收口 + 第 153–163 期 BookOrbit 对齐与 brief 模式 / Komga 凭据 / 条件请求
  + 第 148–152 期 TXT 派生件 / 部署面收口 / 发版 1.4.1 / 漫画库 Vol.04 最后一环
  ⚠️ **逐期一句话在 §2，完整叙事在 `docs/roadmap-gaps-remaining.md`**（最新期在文件末尾）；
  + 第 221 期服务端筛选 + 规则筛选器
  + 第 222 期注释与非代码文件梳理（界面文本分流 / 生成物清理 / 对照文档压缩）
  + 第 223–227 期 PDF 文字层与批注 / 收书目录入库前预览 / Hardcover 进度 / 审计缓冲修复 / 背景纹理
  + 第 229 期外部书库只读登记导入（Calibre → 覆盖层）
  + 第 228 期读路径四处重复劳动收口（/api/stats 配置读盘 2309 → 1 次）
  + 第 230 期Hardcover 端点收敛到一处真值源
  + 第 232 期404 断言补齐 + 四处行号敏感的源码断言改写
  + 第 233 期书目列表热路径收口（一页 96 ms → 9.6 ms）
  + 第 234 期测试里的本机绝对路径（CI 红的根因）
  + 第 235–237 期 TTS 朗读 / KOReader 批注导出 / KEPUB 导出（三条评估项的最小闭环）
  + 第 240 期 KOReader 重置同步凭据 + 设备列表
  + 第 238 期配置分区断言不再「恰好等于」+ 清理误建目录 .codebudy
  + 第 239 期清单型断言指向真值源 + 判据清单补三条
  + 第 241 期持续审计第六轮（零问题 —— 任务收尾总结）
  + 第 242 期持续审计第二轮（正确性 / 安全 / 信任：解压炸弹 / 任意目录写入 / 残留状态自愈）
  + 第 243 期持续审计第三轮：数据可信度 / 边界值 / 数值上限（零发现轮）
  + 第 244 期持续审计第四轮：缓存失效点 / 配置生效路径（13 项修复）
  + 第 245 期持续审计第五轮：特殊字符与编码（OPDS feed 的 XML 合法性）
  + 第 246 期持续审计第六轮：配置写入口的热应用（五个入口只挂了一个）
  + 第 247 期持续审计第七轮：CI 的覆盖缺口 + 本机绿 ≠ CI 绿
  + 第 248 期 Pillow 链路的缺口补齐（缺依赖不许说成「内容坏了」）
  + 第 249 期持续审计第八轮：缓存失效点补漏 / 往返对称 / 事务边界（补两个测试盲区）
  + 第 250 期持续审计第九轮：元数据字段的长度上限（一个书名就能把书架打爆）
  + 第 251 期持续审计第十轮：状态与实情不符（回收站清空漏目录 / /health 误报监听）
  + 第 252 期持续审计第十一轮：一个段写坏，服务就起不来（config.yaml 的段类型没人管）
  + 第 253 期持续审计第十二轮：环境变量的兜底被自己的界面废掉（「人写过」判据不认来源）
  + 第 254 期持续审计第十三轮：扫描派生值也没有长度上限（一个 11.6 KB 的 EPUB 能造出 1.2 MB 的简介）
  + 第 255 期持续审计第十四轮：自定义字段的值也没有长度上限（1 MB 的值能存进库里）
  + 第 256 期持续审计第十五轮：「删不掉的必须如实回报」这条纪律，另外两条路没遵守
  这条链只留**里程碑分组**，别再逐期追加 —— 它是每次会话必读的。
  `VERSION` = `1.4.7`（第 152 期发版，含系列页/详情页读路径与 CLS）—— 单一真值源，`GET /health` 下发；
  v0.x 阶段「第 N 期 = V0.N.0」的约定自 V1.0.0 起终止，改为**按里程碑发版**
  （第 147 期里程碑 = 格式识别与导入的判据收敛 —— 同一份字节只许一种结论；最新段 `CHANGELOG.md` 的 `V1.4.7 — 2026-10-27` 覆盖系列页/详情页读路径与 CLS，`V1.4.6` 覆盖首屏与显示优化，`V1.4.5` 覆盖合集跨册续接 / 漫画·PDF 系列目录 / 书详情回系列，`V1.4.4` 覆盖多选补修，`V1.4.3` 覆盖审计与 CI 噪音，`V1.4.2` 覆盖第 152 期主体）。
- 测试基线（第 256 期实测）：后端 **3255 例（3228 passed / 0 failed / 0 errors / 27 skipped）**，全量 813 s；
  ⚠️ 比基线要**连着 skipped 与「总数」一起读** —— skipped 变化可能来自环境（本机环境项、`quickjs` 缺失等），不是新写的用例。
- **历史基线（第 148–150 期）**：后端 2752 / 2770 / 2770 例（2752 / 2756 / 2756 passed，14 skipped），
  全量 497.6 / 493.1 / 400.3 s；第 147 期那次在 Linux 容器里六分片并行（墙钟约 21 min）。
  ⚠️ **比基线要连着 skipped 与「总数」一起读** —— skipped 变化可能来自环境（`quickjs` 装没装、
  `py7zr` 缺失时模块级 `importorskip` 整组吃掉），**不是**新写的用例 ⇒ 判据是**拿两台机器的
  junit 做用例名差集**，不是看 skipped 计数。别拿耗时互比（随环境波动，无单点热点）。
  逐期数字见 `docs/roadmap-gaps-remaining.md` 各期段与 `git log`。
  ⚠️ **仍在生效的操作约束**（不是历史，别跟着上面一起压掉）：
  · **别把 `.venv` 升到 3.13+** —— `quickjs` 只有 cp38–cp312 包（见 `AGENTS.md` §5）。
  · 夹具若「写文件 → `invalidate()` → 立刻读」，读路径对「索引非空 + 标脏」只做**有上限**的等待
    （`catalog.SETTLE_WAIT` = 0.25 s）⇒ 满载时读到旧列表（单跑必绿）。要同步重扫就显式调
    `library.books(force=True)`（第 129 期 `test_annotation_export.py::_bid` 的教训）。
- 前端（第 135 期实测）：**70 spec / 722 例**全绿、`vue-tsc --build` exit 0、`build + deploy` 跑过（`scripts/frontend-verify.sh` 等价四连）；
  本期前端改 17 个文件（`lib/format.ts` 新增 `localDate` / `localMonth` 作本地日的**唯一实现**，7 处 `toISOString().slice(0, 10)` 全部收敛；设置页四个页面改「判返回值才提示成功」；`auth.ts` 不再把 5xx 当未登录；`library.ts` 给 `loadFeatures` 加序号；`DuplicateBooksView` 改 `allSettled`；`LoginGate` 用 `apiErrorMessage`），新增 `src/lib/format.spec.ts`（`EXPECTED_SPECS` 已登记），`package-lock.json` 零改动；
  `novelforge/static/v2` 是**构建产物且不入库**（`.gitignore` 忽略）⇒ 它变与不变都不在 `git status` 里。
- ⚠️ **运行陷阱不在这里重抄** —— 别加 `-q` / 长跑 pytest 后台跑 + 轮询 junit / 新增前端 spec 要登记
  `EXPECTED_SPECS` / 只跑相关文件看不见连锁失败：**一律看 `AGENTS.md` §4 与 §5**；
  **本机（Windows）专属项**（清代理变量、别跑 `pnpm`、DNS 污染、编码坑）：见 `docs/development-windows.md`。
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

### P0 · BookOrbit 全量对齐（第 153 期起，五期）

> 对照与取证：`docs/bookorbit/bookorbit-live-diff-2026-10.md`（196 条上游独有 / 108 条同名不同义 /
> 76 条本项目独有，附全表）与 `docs/bookorbit/bookorbit-live-inventory-2026-10.md`（320 API / 472 chunk /
> 42 设置页）。范围按用户 2026-10-26 的决定：§3.1 与 §3.5 全做（写回书文件跳过）；read-along 做；
> PWA / 实时 / 安全头 / history 路由照上游做。**每期按 AGENTS §1/§2 的同步点同批收口。**

- [x] **Phase 0 · 工程地基**（第 153 期）：对照文档 + 取证清单；history 路由 + SPA 兜底 + 旧 hash 迁移；
  全局安全响应头 + theme-init 外置；PWA manifest/图标/SW；WebSocket `/ws` + 事件总线 + 前端重连/轮询回退；
  修 Book Dock 统计恒 0。
- [ ] **Phase 1 · 书目与治理**（进行中；第 154–165 期已完成：手动排序 / 全库汇总 / 入库时间 / 建库预扫 /
  按库只读凭据 / 分面 / 分桶 / 正则导入向导 / 封面编辑器 / 重复书四类依据 / 实体 6 类 / 批量元数据编辑 /
  表视图列面板；第 201/203/204 期补：阅读状态 8 档 / 移动 preflight 指纹 / 评分权重可配 + 版本；
  第 209/210 期补：仪表盘偏好服务端 / 收藏夹分页；第 211 期补：导出粒度；第 218 期补：智能范围表达力
  （29 字段 / 8+6+4+4 操作）+ 服务端求值）：
  第 233 期补：书目列表热路径收口（一页 96 ms → 9.6 ms：路径拼装不逐行解析根路径、
  分页只取这一页的行、总数用一次 COUNT）。
  **剩余**：把**规则筛选**下推到 SQL（现在的筛选是 Python 层求值；实测一条规则在
  2309 本上只要 3–4 ms，而一条 SQL 预筛要 11 ms —— 下推**更慢**，且要把
  「override > online > opf」的优先级搬进 SQL，不划算）。
  **已覆盖（不另做）**：规则筛选器 UI（第 221 期已做：书架筛选面板里可直接写规则）。
  **已覆盖（不另建入口）**：受管副本批量改名 —— 刮削「命名规则 → 重出版」已有预览 / 冲突拒绝 /
  `remap_book_id`（`scrape.plan_naming` / `republish`），再做一个入口就是第二份命名实现。
  **不做**：写回书文件；kobo-sync 标志（Kobo 仍评估）。
  第 234 期补：维护页孤儿扫描一次请求读两遍库表（`_orphans` 的两处都要它，而第二遍来自
  `catalog.books` 内部）—— 改 `catalog.books` 的签名动的是**核心读路径**，省几十毫秒不值 ⇒ 不做。
- [x] **Phase 2 · 有声书 + 播客**（第 167–186 期）：2A 有声书增强（书签 / 单轨已听 / 倍速 / M4B / ZIP / 续听）；
  2B 播客内核/订阅（RSS / OPML / 健康 / 批量刷新）；2C 单集/队列/下载/转录/自动下载/进度/书签/连播/继续收听；
  2D 合集 / 单集轴智能播放列表 / 目录搜索。删除与清理一律回收站。
- [x] **Phase 3 · read-along**（第 188 期）：SMIL 解析与识别；`book_media_overlays` + `read_aloud_sync`
  （含 `book_id`，已进 remap 清单）；句子级同步；位置回写；去音频导出。
- [x] **Phase 4 · 阅读器/收书/统计/运维收口**（第 189–238 期已收口）：第 189–200 期已完成 EPUB/PDF 搜索、
  PDF 大纲、快捷键/全屏/跳转、每库扫描历史、登录/登出审计、通知分页/隐藏、成就提示、
  ⌘K 命令面板、KOReader 未匹配、逐源搜索健康、下载文件名模式、封面变更审计；
  第 209–217 期补：仪表盘偏好服务端 / 收藏夹分页 / 导出粒度 / 多级排序 / 元数据批处理暂停继续取消 / 成就展示柜 / 自定义图标 / 成就 ETA；
  第 221 期补：服务端筛选 + 规则筛选器（筛选口径下沉，五项下拉与规则共用 `core/bookrules.py`）；
  第 223 期补：PDF 文字层 / 选区 / 批注（PDF 的「章」= 页，锚点用页内字符偏移）；
  第 224 期补：Dock 入库前预览（落点名 / 封面 / 查重，**只读**、重复只提示不拦）；
  第 225 期补：Hardcover 阅读进度（**只在换章推**，0 与「没读过」分开）；
  第 227 期补：背景纹理（10 档纯 CSS，不引图片 / 不出网）；
  第 229 期补：外部书库的只读登记导入（Calibre `metadata.db` → 覆盖层，零拷贝）；
  第 231 期补：PDF 拖拽平移 + 站外链确认（外链先弹确认框，只放行 http/https）；
  第 235–238 期补：TTS 朗读（自托管 OpenAI-compatible）/ 批注导出成 KOReader 文件 /
  KEPUB 导出（Kobo）/ KOReader 重置凭据 + 设备列表；
  **剩余**：无（Phase 4 的能力项已全部落地）。
  另修「作者抓取开关是死配置」（`metadata_fetch.authors.fetch_bio/fetch_photo/sources` 无后端读点）—— 第 202 期已修。
- [ ] **评估项**（部分已落地，剩余部分仍不排期）：
  - TTS（自托管 OpenAI-compatible）—— **第 235 期已做**（受限版：只接自托管引擎、默认关、只朗读当前一章）；
  - KEPUB 导出 —— **第 237 期已做**（只产出文件，投递由用户自己走 Calibre-Web / Kobo 桌面端）；
  - KOReader 双向批注 —— **第 63 期导入 + 第 236 期导出已做**（官方协议只同步进度，批注走文件）；
  - **仍不做**：Kobo 设备配对与自动投递（Kobo 私有协议）、KOReader 插件包级同步。

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
| 256 | 持续审计第十五轮：「删不掉的必须如实回报」这条纪律，另外两条路没遵守 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 256 期段 |
| 255 | 持续审计第十四轮：自定义字段的值也没有长度上限（1 MB 的值能存进库里） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 255 期段 |
| 254 | 持续审计第十三轮：扫描派生值也没有长度上限（一个 11.6 KB 的 EPUB 能造出 1.2 MB 的简介） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 254 期段 |
| 253 | 持续审计第十二轮：环境变量的兜底被自己的界面废掉（「人写过」判据不认来源） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 253 期段 |
| 252 | 持续审计第十一轮：一个段写坏，服务就起不来（config.yaml 的段类型没人管） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 252 期段 |
| 248 | Pillow 链路的缺口补齐 —— **「缺依赖」不许说成「内容坏了」** —— 细节见 `docs/roadmap-gaps-remaining.md` 第 248 期段 |
| 251 | 持续审计第十轮（状态与实情不符：回收站清空漏目录 ⇒ 说「已清空」实际有残留；`/health` 把用户主动关掉的监听说成故障） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 251 期段 |
| 250 | 持续审计第九轮（元数据字段的长度上限：一个书名就能把书架打爆 —— 存储层闸门 + 服务端 400 + 前端 maxlength） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 250 期段 |
| 249 | 持续审计第八轮（缓存失效点补漏 / 往返对称 / 事务边界 —— 五角度零发现 + 补 `customicons` 的安全盲区） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 249 期段 |
| 247 | 持续审计第七轮（CI 覆盖缺口：前端没有守门人 + 播客 worker 跨用例常驻 ⇒ 本机绿 CI 红） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 247 期段 |
| 246 | 持续审计第六轮（配置写入口的热应用：五个入口只挂了一个 ⇒ 还原/重置后日志配置不生效） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 246 期段 |
| 245 | 持续审计第五轮（特殊字符与编码：OPDS feed 的 XML 合法性 —— 非良构 XML ⇒ 客户端整份解析失败） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 245 期段 |
| 244 | 持续审计第四轮（缓存失效点 / 配置生效路径：分页污染全量缓存键 / 覆盖层漏失效 / 配置不热应用 / 假配置 / 死代码清理） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 244 期段 |
| 243 | 持续审计第三轮：数据可信度 / 边界值 / 数值上限（零发现轮） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 243 期段 |
| 242 | 持续审计第二轮（正确性 / 安全 / 信任：解压炸弹 / 任意目录写入 / 残留状态自愈） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 242 期段 |
| 241 | 持续审计第六轮（零问题 —— 任务收尾总结） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 241 期段 |
| 239 | 清单型断言指向真值源 + 判据清单补三条 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 239 期段 |
| 238 | 配置分区断言不再「恰好等于」+ 清理误建目录 .codebudy —— 细节见 `docs/roadmap-gaps-remaining.md` 第 238 期段 |
| 240 | KOReader 重置同步凭据 + 设备列表 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 240 期段 |
| 237 | KEPUB 导出 —— Kobo 那条评估项的最小闭环 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 237 期段 |
| 236 | 批注导出成 KOReader 的批注文件 —— 反向那一半 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 236 期段 |
| 235 | TTS 朗读 —— 自托管 / 局域网的 OpenAI-compatible 引擎 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 235 期段 |
| 234 | 测试里的本机绝对路径（CI 红的根因） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 234 期段 |
| 233 | 书目列表热路径收口（一页 96 ms → 9.6 ms） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 233 期段 |
| 232 | 404 断言补齐 + 四处行号敏感的源码断言改写 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 232 期段 |
| 230 | Hardcover 端点收敛到一处真值源 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 230 期段 |
| 228 | 读路径四处重复劳动收口（/api/stats 配置读盘 2309 → 1 次） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 228 期段 |
| 223 | PDF 文字层 + 选区 + 批注 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 223 期段 |
| 224 | 收书目录的入库前预览 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 224 期段 |
| 225 | Hardcover 阅读进度同步 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 225 期段 |
| 226 | 审计缓冲的缺陷修复 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 226 期段 |
| 227 | 背景纹理 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 227 期段 |
| 229 | 外部书库的只读登记导入 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 229 期段 |
| 222 | 注释与非代码文件梳理（界面文本分流 / 生成物清理 / 对照文档压缩） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 222 期段 |
| 221 | 服务端筛选 + 规则筛选器 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 221 期段 |
| 219 | 审计遗留三条（目录客户端封面 / pip 缓存锁 / App.vue 结构） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 219 期段 |
| 218 | 智能书架：服务端求值 + 规则表达力 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 218 期段 |
| 217 | 成就 ETA —— 细节见 `docs/roadmap-gaps-remaining.md` 第 217 期段 |
| 216 | 自定义图标库 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 216 期段 |
| 215 | 成就展示柜 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 215 期段 |
| 214 | 元数据批量抓取：暂停 / 继续 / 取消 + 预览汇总 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 214 期段 |
| 213 | 镜像瘦身开关 + 构建缓存（704 MB → 453 MB） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 213 期段 |
| 212 | 书架多级排序 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 212 期段 |
| 211 | 书目导出粒度 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 211 期段 |
| 210 | 收藏夹书目分页 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 210 期段 |
| 209 | 仪表盘偏好存服务端 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 209 期段 |
| 208 | 封面缩略图判据改字节（真机 −84%） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 208 期段 |
| 205 | 审计归档按天保留 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 205 期段 |
| 204 | 元数据完整度权重可配 + 版本标注 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 204 期段 |
| 203 | 跨库移动指纹判重 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 203 期段 |
| 202 | 作者抓取配置接通 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 202 期段 |
| 201 | 阅读状态 8 档 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 201 期段 |
| 200 | 封面变更审计 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 200 期段 |
| 199 | 审计日志服务端 CSV 导出 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 199 期段 |
| 198 | 成就提示语：还差多少 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 198 期段 |
| 197 | KOReader 未匹配文档可见 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 197 期段 |
| 196 | 下载文件名模式 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 196 期段 |
| 195 | PDF 大纲 + 文内搜索 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 195 期段 |
| 194 | ⌘K 命令面板 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 194 期段 |
| 193 | 元数据缓存统计 + 书源搜索健康 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 193 期段 |
| 192 | 登录 / 登出审计 + 审计日期筛选 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 192 期段 |
| 191 | 每库扫描历史 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 191 期段 |
| 190 | 通知中心分页 / 隐藏 / 清空 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 190 期段 |
| 189 | EPUB 书内搜索 + 阅读器快捷键 / 全屏 / 跳转 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 189 期段 |
| 188 | read-along 媒体叠加（SMIL 解析 / 句子同步 / 去音频导出） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 188 期段 |
| 187 | 播客目录搜索（iTunes Search / 默认开 / 失败降级） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 187 期段 |
| 186 | 播客智能播放列表（单集轴规则 / 内置预设 / 队列快照） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 186 期段 |
| 185 | 播客合集（只装订阅 / 软删过滤 / 重订阅恢复） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 185 期段 |
| 183 | 播客版继续收听 + 单集搜索 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 183 期段 |
| 182 | 播客单集官方转录（feed 转录 / 剥时间码 / 缓存） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 182 期段 |
| 184 | 重复书页 19.4 s 收口（两级内容哈希 / quick_ratio 上界预筛） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 184 期段 |
| 181 | 播客自动下载最新 N 集 + 听完清理本地副本 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 181 期段 |
| 180 | 播客播放队列（本机持久化 / 跨订阅 / 播完优先取队首） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 180 期段 |
| 179 | 体积与加载速度（前端按需化 / 静态预压缩 / 镜像与仓库瘦身） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 179 期段 |
| 178 | 播客单集播完自动连播 + 单实例播放 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 178 期段 |
| 177 | 播客单集书签（时间点 / 同秒幂等 / 软删除） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 177 期段 |
| 176 | 播客单集播放进度 / 已播状态 / 筛选 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 176 期段 |
| 175 | 播客单集下载（队列 / 本地播放 / 清理） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 175 期段 |
| 174 | 播客订阅管理（OPML / 健康落账 / 批量刷新） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 174 期段 |
| 173 | 播客订阅内核（RSS 订阅 / 刷新 / 单集试听） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 173 期段 |
| 172 | Phase 2A 收口（继续收听 / 按书倍速 / M4B 章节 / 整本 ZIP） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 172 期段 |
| 171 | 覆盖写入批量事务（工具 → 文件名提取的整库规则） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 171 期段 |
| 170 | 批量动作收口（单事务批量写 / 自动推送合并 / Komga 集合批量化） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 170 期段 |
| 169 | 有声书倍速 0.5–3 + 睡眠「+15 分钟 / 本轨结束」 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 169 期段 |
| 168 | 有声书单轨「已听」标记 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 168 期段 |
| 167 | 有声书书签（时间点 + 备注） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 167 期段 |
| 165 | 按正则从文件名提取元数据（工具 → 文件名提取） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 165 期段 |
| 164 | 读路径第二轮审计（重复页 bigram 预筛 / 成就走 brief / 会话查询收敛） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 164 期段 |
| 163 | Komga 兼容层支持只读客户端凭据 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 163 期段 |
| 162 | 仪表盘统计 brief 模式（/api/stats?brief=1） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 162 期段 |
| 161 | GET /api/* 条件请求（ETag/304）+ 侧栏计数与全量书目解耦 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 161 期段 |
| 160 | OPDS 只读客户端凭据（可限定书库） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 160 期段 |
| 159 | 实体管理扩到 6 类 + 修复多值覆盖值形态 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 159 期段 |
| 158 | 表格视图列面板（显隐 / 行高 / 冻结 / 命名视图） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 158 期段 |
| 157 | 书库直传上传 + 批量元数据编辑 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 157 期段 |
| 156 | 书架分面计数 + 跳转跟随排序 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 156 期段 |
| 155 | BookOrbit 对齐 Phase 1A：重复书治理 + 封面编辑器 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 155 期段 |
| 154 | BookOrbit 对齐 Phase 1A：排序 / 汇总 / 入库时间 / 预扫 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 154 期段 |
| 153 | BookOrbit 全量对齐：独立复核 + Phase 0 工程地基 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 153 期段 |
| 152 | 漫画库「Vol.04 没合并」的最后一环：折叠行标题取代表本 / 折叠默认关 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 152 期段 |
| 150 | 镜像 tag 的发布规则修正 + 发版 1.4.1（148/149/150 三期合集） —— 细节见 `docs/roadmap-gaps-remaining.md` 第 150 期段 |
| 149 | 部署面收口：镜像 tag 钉死到版本号 / 非 root 运行的配方与启动自检 / 「是不是压缩包」判据收敛 / 待展开清单不再每次重开归档 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 149 期段 |
| 148 | TXT 在线阅读：两个并发请求就能把这本书读废 —— 派生件构建没有串行化 / 成品被删永不重建 / 进度拿不到精确位置 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 148 期段 |
| 147 | 格式识别与导入：同一份字节换个名字就有两种结论 —— 改名的 EPUB 被当一页漫画 / 页数与封面两次开包 / 标题里的实体不解开 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 147 期段 |
| 146 | GitHub 反复报错的三个真因：源码目录被静默忽略 / 层缓存并发写 / 空目录不进 clone —— 细节见 `docs/roadmap-gaps-remaining.md` 第 146 期段 |
| 145 | 漫画库 series 恒空：2043 张散卡收敛成 170 个系列 —— 扫描期按目录布局推断 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 145 期段 |
| 144 | 十轮审计 10/10：部署与运维面 —— 备份永远失败 / 永远 unhealthy 的端口 / 永远不提的默认口令 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 144 期段 |
| 143 | 十轮审计 9/10：文档真值源漂移 —— 点名的主语不存在 / 界面路径成片过期 / 同一判据两份实现 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 143 期段 |
| 142 | 十轮审计 8/10：前端运行时 —— 检查失败别报成功 / 常驻标签页别偷请求 / 静默失败要说话 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 142 期段 |
| 141 | 十轮审计 7/10：错误处理与降级 —— 别把错误写进正文、别把失败记成 0 本、别把静默当成功 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 141 期段 |
| 140 | 十轮审计 6/10：数据库层 —— 一个 inf 让书架永久 500 / 搬迁失败不许记账 / 幂等标记不许提前写 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 140 期段 |
| 139 | 十轮审计 5/10：缓存一致性 —— 命中也要登记、写回前先比对、计数不再丢掉盘上已不在的成员 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 139 期段 |
| 138 | 掩码回写把真密钥覆盖成掩码 / 一个配置段挂在两个设置页 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 138 期段 |
| 137 | 审计收口：落盘原子性收敛 / 登录退避三入口 / 令牌指纹不可逆 / 书源 JS 不降级 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 137 期段 |
| 136 | 十轮审计：令牌绑密码 / OPDS 分页掉筛选 / 按书取路径收敛 / 刮削队列重启停摆 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 136 期段 |
| 135 | 第二轮审计：媒体出口收敛 / 刮削台账卡死 / 迁移缩进 / 双线程并扫 / 前端假成功 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 135 期段 |
| 134 | 五轮审查九条收口：正文丢段 / 掉线误删索引 / 设置读失败清空 / 出站闸 / 展开上限 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 134 期段 |
| 133 | 阅读器不再执行书里的脚本：正文按允许清单净化，未知标签降级 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 133 期段 |
| 132 | 导出的 CSV 里，书里的文字会变成 Excel 公式 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 132 期段 |
| 131 | 任务记录的诚实性：重启后没人推进的「进行中」如实标成失败 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 131 期段 |
| 130 | 查询串的条数：limit 超范围不再 500，LIMIT 绑定统一夹进 SQLite 整数范围 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 130 期段 |
| 129 | 名字到路径的判据：超长名与非法书源名不再 500，Cookie 路径不再越出 COOKIE_DIR —— 细节见 `docs/roadmap-gaps-remaining.md` 第 129 期段 |
| 128 | 同名冲突的降级路径：单书入口 409，批注总览与导出不再整页打不开 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 128 期段 |
| 127 | 数值入口的有限性：inf / NaN / 整数溢出不再毒化整页 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 127 期段 |
| 126 | 分章完整性：全顶格无标记退化成一章全文 / 全缩进文本不再切出零章 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 126 期段 |
| 125 | 入库审查修复：隐藏文件 / 等条件重试 / 解压上限 / 根外链接 / 覆盖标记 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 125 期段 |
| 124 | 格式识别复审修复：旁注判据收紧 + 容器媒体类型与上传白名单收敛 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 124 期段 |
| 123 | 格式识别审查：图文混装永久不可读 + 兼容层媒体表落后 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 123 期段 |
| 122 | zip 上传被判没有库：先落临时件再判形态 + 前端白名单补齐 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 122 期段 |
| 121 | 功能审查：同名守卫覆盖 KOReader / 同一文件双库登记 / 假监听 / 封面当章节 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 121 期段 |
| 120 | 第二轮逻辑审计：书源名就是文件名 + 设置写不进去还回 ok —— 细节见 `docs/roadmap-gaps-remaining.md` 第 120 期段 |
| 119 | 逻辑审查：一条未鉴权任意文件读取 + 九条逻辑缺陷 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 119 期段 |
| 118 | 跨平台审查修复：pytest 进 CI + 六条平台假设缺陷 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 118 期段 |
| 117 | AGENTS.md 索引化 + 本机陷阱外移 + 常用命令脚本化 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 117 期段 |
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
| 106 | **记忆体系精简（收尾只写两处）**+ `AGENTS.md` 基线； |
| 105 | **CI「Build and Push Image」全失败修好**：先查历史 —— 该工作流 **run 288–317 全 failure**（2026-10-03 起），最后一次 success 是 run 217（2026-10-01… |
| 104 | 出网**失败归因**+ 前端类型红收口：先查出**本机 DNS 被上游污染**（`openlibrary.org`→`31.13.112.4` / `www.goodreads.com`→`128.242.240.253`… |
| 103 | 元数据字段**接线**，**唯独这条抓取线从未接上** —— `_entry` 是固定键白名单、`metafetch` 无映射 ⇒ 抓到了也被静默丢掉）：① 顺手修 **RanobeDB 详情补全从未生效**（真机响应套在 `book` 键里… |
| 102 | 元数据抓取**地基**：① 14 家源声明**收口**到 `novelforge/core/sources/`（`Provider` 数据类 + `DECLARED`… |
| 101 | 书源网页抓取收口：**Goodreads 旧结构（`<tr itemscope>`/`bookTitle`/`authorName`）已被站点下线 ⇒ 整家恒返 0 条**… |
| 100 | EPUB 解析换成熟解析器**实测后删除该立项**：37 本真实第三方 EPUB（Standard Ebooks… |
| 99 | 元数据抓取**真机核验** + 三处线上真 bug：① Audible `response_groups` 带非法组名 `publisher` ⇒ 400、**整家永远 0 结果**（`publisher_name` 是**字段**… |
| 98 | 仪表盘余留三条：**页级三态**（判据 = 聚合首屏真请求：`stores/stats` 的 `loaded`/`error` + `stores/library` 的 `loading`/`booksError`… |
| 97 | 第 95 期审计四条 `[low]` 全清：`gate_reason` 的不参与判定 `source` 形参**删除**（17 处调用点 / 11 处传参 + 2 个测试桩）/ `manager._mark` **不再写**冗余历史键 `_source`（读侧 `source_o… |
| 96 | 数据安全两处口径落地：展开容器的「删源」改为**移入回收站**（`publish.recycle` + 台账，可还原）+ 自动落地/显式覆盖**先把被替换的文件移入回收站**（回收失败即中止、盘上零改动）； |
| 95 | `AGENTS.md` 新增 §7「工程原则」+ 按 `AGENTS.md` 做合规审计与整改（九处旧路径、三处死代码、文件名判据收口、视觉 token 守卫、404 断言）（**不发版**，`VERSION` 仍 0.94.0） |
| 94 | 书源导入静默失败修复 + 格式适配器轴（native / 导出 / Legado 3.x / 阅读 2.x / JSONL）+ 转换诚实闸 + 引擎能力（XPath / `##` 替换 / 索引语法 / 选择器后缀 / URL 选项字典 / 续页 / 多编码）+ 安全层（JS 沙… |
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
