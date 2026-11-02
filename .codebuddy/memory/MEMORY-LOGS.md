# 旧当日日志精选（第 1–105 期的实施过程记录）

> 第 220 期整理：`.codebuddy/memory/` 里曾有 23 份当日日志（2026-09-13 ~ 2026-10-05，合计 **680 KB**），
> 但「当日日志」这个仪式**自 2026-10-06（第 106 期）起已取消**（`tests/period_close.py` 的 R4
> 会拒绝新建）。它们仍是仓库的一部分，却**不在每次会话的注入范围**里 —— 而内容几乎全是
> `docs/roadmap-gaps-remaining.md` 各期段的重复。
>
> 处置：
> · 逐期核过 —— 23 份日志提到的期号里，**只有第 74 / 78 期**是 roadmap 与 `MEMORY-PERIODS.md`
>   都没有的（那两期「无逐期段」）；其余每期都能在 roadmap 找到同名期段 ⇒ 21 份日志**零独有信息**。
> · 保留这两份里**第 74 / 78 期的独有段落**（下方），其余日志**删除**（git 历史里仍可取回）。
> · 「当日日志不许复活」的约定不变 —— 本文件是**一次性精选**，不是新仪式。

## 摘自 `2026-09-28.md`（第 74 / 78 期）

### 状态（已验证，2026-09-28 跑通）
- ✅ `type-check` 0 错；`test:unit` **29 例全过**（`LibraryWizard.spec` 25 + `libraryWizard.spec` 4）；`build` 过 + `deploy` 同步 `dist → novelforge/static/v2`。
- ⚠️ 首次验证失败是**环境问题**：`node_modules` 缺 `vitest`/`echarts`/`@vue/test-utils`（`vitest: command not found` + echarts 解析不到）；`npm install` 补 50 包后复跑全绿。与本次改动无关。此前 deploy「成功」只是误同步了旧 `dist`，build 失败未重生成，现已用真实构建纠正。
- **期号 = 第 74 期**（09-29 提交时确认：当时 origin/main 已到第 73 期）。功能提交 = `ffe3bfb`（rebase 前的本地态为 `a395618`，内容相同）+ 记忆提交 `b38d897`，**两笔均已推送**（`62b8b86..b38d897`）；rebase 过程见 `2026-09-29.md`。

## 摘自 `2026-09-29.md`（第 74 / 78 期）

## 第 74 期 · 收尾：新建向导并入编辑口径（已 push）

- 承接 09-28 的 T4（详见 `2026-09-28.md`）：`frontend/src/components/tools/LibraryWizard.vue` **5 步向导 → 3 页签**（内容/自动化/上次扫描），与 `LibrariesView.vue` 编辑弹窗字段组织统一；**移除内联阅读阈值**（改走「设置→命名规则」）；新增**每库刮削出版覆盖项**（与全局不同才 `librarySettingsUpdate`，默认跟随全局不写覆盖）；排除图案改换行文本框。
- 验证：`type-check` 0 错 / `test:unit` **29 例全过**（`LibraryWizard.spec` 25 + `libraryWizard.spec` 4）/ `build` + `deploy` 绿。
- ⚠️ **期号定为第 74 期**：动手前 `git fetch` + `git log origin/main` 发现**另一会话已把期号推到第 73 期**，本地 `main` 停在 `2a84183`（第 67 期）**落后 origin/main 25 个提交**。硬约定第 6 条再次生效。
- ⚠️ **rebase 实测**（`git rebase origin/main`）：代码文件**无冲突**（origin 未动 `frontend/src/components/tools/`）；但**记忆文件全部冲突** —— `2026-09-28.md`、`2026-09-29.md`（add/add）、`MEMORY.md` 三处，已按「**两边都留**」解决：两个日记取 origin 段 + 追加本线 T4 段；`MEMORY.md` 取 origin 版（它已是最新且更全的压缩版，含文档体系、硬约定第 8 条、第 71–73 期踩坑；本线那份是同一内容的旧压缩，**无独有内容**）。
- `frontend/package-lock.json` 的改动是我 `npm install` 补齐缺失 devDeps（`vitest`/`echarts`/`@vue/test-utils`）导致的 `"dev": true` 标记漂移，属噪音 ⇒ 已 `git checkout` 丢弃，未提交。
- 📌 **补正**：本条目的提交 `b38d897` 提交信息里写的「未推送」是**创作时刻的快照**（当时确实只在本地）；随后 `git rebase origin/main` 并正常推送（`62b8b86..b38d897`），**未改历史**。功能提交 rebase 后 = `ffe3bfb`（原 `a395618`，内容相同）。

---

## 第 78 期 · V0.78.0：版本号单一真值源 + 侧栏/新功能页 + 一键更新 + Release 自动化

## 第 80 期 · `update` 段配置「每个键都真有读点」+ 解除「零外部请求 / 零依赖」硬约束（V0.80.0）

**动机**：用户指令「继续 A+B」→ A = 让 `update.auto_apply` / `update.image` 真正生效（否则从 UI/白名单移除，**绝不留假开关**）；
B = 给 `core/updater.py` 补完全离线的契约测试；补充输入「取消零外部请求和零依赖的要求」。

**缺陷形态（本期最值得记住的一条）**：第 78 期引入的 `update` 段四个键**三个是假配置** ——
`check_enabled` / `interval_hours` **只在 lifespan 读一次**（改完必须重启进程，关掉后侧栏 `new` 徽标还会重新冒出来）；
`image` 只在白名单 + 回显里、`apply_update()` 直读环境变量（**界面根本没这个控件**）；
`auto_apply` **连读点都没有**（打开什么都不会发生）。危害是**静默**的：用户看到「已保存」，只在下次发版时才觉得「这开关时灵时不灵」。

**修法（后端）**：
- `updater.configured_image(explicit="")` = **镜像唯一读法**（显式入参 > `update.image` > `NOVELFORGE_UPDATE_IMAGE` > `_DEFAULT_IMAGE`）；
  新增 `_split_image()` **只把最后一个 `/` 之后的冒号当 tag**（`localhost:5000/ns/img` 不被误拆）。
- `updater.maybe_auto_apply()`：`auto_apply ∧ has_update ∧ updater_available() ∧ latest ≠ auto_applied`；
  ⚠️ **先记后做** —— 先把 latest 写进**新增持久化键 `auto_applied`** 落盘再做，于是 pull 失败也不会每轮重试；
  「未挂 socket」**不记**尝试（否则以后挂上也永远不自动更）；失败只记日志不冒泡。
- ⚠️ `_persist()` / `_load_persisted()` 的**写死键元组必须同批扩容**（加 `auto_applied`）—— 漏一处会静默丢键，
  表现正是「每次重启后对同一版本重新自动拉一遍」。
- `server._apply_update_config()`（与 `_apply_watcher_config()` 并排）在 **5 处**配置写接口 + lifespan 复用 ⇒ 判据只有一份；
  关检查 = `stop_background()` + `clear_has_update()`；开/改间隔 = 先 stop 再 `start_background(新间隔)`。
- ⚠️ **`start_background` 原有竞态**：旧实现**共享同一个模块级 `_stop` Event** ⇒「先 stop 再 start」会让新线程一启动就被旧的置位信号劝退。
  改为**每次新建 Event 并把 stop 作为参数传给 `_loop`**，幂等判据 = `_thread is not None and is_alive() and not _stop.is_set()`。
- `apply_update` 的返回结构与 `stage` 枚举（`unavailable`/`pull_failed`/`restarting`）**逐字不变**，前端类型不受影响。

**修法（前端）**：`UPDATE_FIELDS` 3 → **4 项**（新增 `update.image`，`type:'text'`）；三条 hint 改为「保存即生效」口径；
`UpdateStatus` 加可选 `check_enabled`/`auto_apply`；`WhatsNewView` 横幅按 `auto_apply && updater_available` 如实加一句「已开启自动更新」。

**⚠️ 实现比计划多修的一处**：写入口第一版镜像名正则 `^[A-Za-z0-9][A-Za-z0-9._/-]*(?::[A-Za-z0-9._-]+)?$` 会**把 `localhost:5000/ns/app` 拒掉**
（主机后的 `:端口` 过不了字符集）—— 而 `_split_image` 明明已按最后一个冒号正确处理了它；改为**第一段单独放行 `:端口`**：
`^[A-Za-z0-9][A-Za-z0-9._-]*(?::[0-9]{1,5})?(?:/[A-Za-z0-9._-]+)*(?::[A-Za-z0-9._-]+)?$`。

**契约测试（两新增，全离线，共 +35 例）**：
- `tests/test_updater.py`（26 例）：版本比较数值段边界 / `status` 形状 / `updater_available`（判定**不碰 docker**）/
  `check(force)` 三条出网路径 / 1h 缓存**不重复出网** / `clear_has_update` 落盘 / `_split_image` 端口边界 /
  `configured_image` 四级优先级 / 持久化往返**含 `auto_applied`** / `start_background` 幂等 + 新 Event /
  `apply_update` 未挂载**且 `_docker` 从未被调用** / 已挂载的 `fromImage`+`tag` 与 `_recreate`（用 `threading.Event` 同步，
  **不要 monkeypatch `Thread`** —— 会波及模块内其它线程）/ `maybe_auto_apply` 四象限 + 先记后做 + 重启不重试。
- `tests/test_update_config_contract.py`（9 例）：`EDITABLE['update']` ⇄ 前端 `UPDATE_FIELDS`（正则解析 TS）**集合相等** /
  `SECTION_KEYS.update` / `DEFAULTS` 覆盖白名单 / **每键的真实读点**（`READ_POINTS` 表 + `.get("<键>"` 片段）+ **反向闸**（读点表须覆盖白名单）/
  回显 / 保存后 status 如实 / 镜像名 4 拒 4 收。
  ⇒ 把「白名单 ⇄ 控件 ⇄ 读点」三者一致钉死，**「假配置」形态下次复现会直接红**。

**口径修订（用户明确要求，但本期不新增任何依赖）**：解除「零外部请求 / 零依赖」**硬约束** → 改为
「默认自托管、默认不引；允许**显式、可关、失败降级**地引入外部依赖与出网；新增依赖须在 `requirements*.txt` / `package.json`
显式声明并说明理由」。改动落点：`AGENTS.md` 第 1 节、`MEMORY.md` 硬约定 #5、`MEMORY-REF.md`（逐期铁律上方加总注，
**历史原文不改写**）、`docs/project-overview.md` / `DESIGN.md` / `architecture.md` / `docs/bookorbit/{capability-gap,module-inventory,settings-inventory}.md`（加注）、
代码注释 `config.py` / `core/{fonts,audio_meta,metasources}.py` / `frontend/src/lib/icons.ts` / `assets/{main,fonts}.css`、
`tests/test_audio_narrators.py` docstring。
**刻意不改**：`docs/roadmap-gaps-remaining.md` 里历史各期的同类措辞；`prefsBridge.ts` 的「零依赖」（那是「无 import」的技术事实）。
**刻意不做**：不为「解除零依赖」顺手替换手写实现（`_UnixSocketConnection`、字体 name 表解析）—— 改口径 ≠ 必须引依赖。

**验证**：后端全量 **1319 例（1307 passed / 12 skipped / 0 failed，+40）**；前端四连全绿（type-check / 447 单测 / build / deploy）。
⚠️ `novelforge/static/v2/` 在 `.gitignore:28`，**构建产物不入库**（deploy 只为本地/Docker 构建服务）。

**提交与发布**（4 笔，按能力拆，提交即推送 `22a911d..91f8e02`）：
`9c962c7` feat(updater) / `6fe2899` feat(config) / `f944ff2` docs(口径) / `91f8e02` chore(release) V0.80.0。
- ✅ **自动发布端到端通过**：`ref/tags/v0.80.0` → `91f8e02…`；`Release | 91f8e02 | completed | success`，
  `author=github-actions[bot]`，**body 与 `CHANGELOG.md` 的 V0.80.0 段逐字一致**（1026 字符）；
  `Build and Push Image | 91f8e02` 亦为 success。
- ⚠️ 两个纯 Windows 环境坑（不是产品缺陷）：
  ① `python -m novelforge.core.changelog <版本>` 在 GBK 控制台会 `UnicodeEncodeError`（`⇄` 等非 GBK 字符）⇒ 比对时先
     `$env:PYTHONIOENCODING='utf-8'`；
  ② PowerShell `Out-String`/`>` 会把 `\n` 翻成 `\r\n`（1042 vs 1026 字符）⇒ 比对正文要**先归一化行尾再比**，否则误判「不一致」。
- 收尾后工作区仅剩 `.vscode/settings.json`（本机设置，非本轮改动，未提交）。

---
