# Windows 开发机专属陷阱（仅当前开发机）

> ⚠️ **整份文件只对当前这台 Windows 开发机成立**（路径含 `C:\Users\qingr\…`）。**Linux / 容器 / 其他机器忽略本文件** ——
> 下面每条都是这台机器的 IDE 注入、控制台代码页或上游 DNS 造成的，与项目代码无关，**不要当成项目规则**。
> 通用陷阱见 `AGENTS.md` §5；命令与回归清单见 `docs/development.md`；一键脚本见 `scripts/`。

## 1. 工具链与解释器

- **Node 由 nvm 管**：nvm v2.0.0 位于 `C:\Users\qingr\AppData\Local\Author Software\nvm`，已 `nvm install 24.19.0` + `nvm use 24.19.0`（设为默认）。
  winget 直装的 node 落在 WinGet 包目录、PATH 检索会跳过且被 nvm 抢注（无害残留）；
  ⚠️ `install_binary`（node）在本机会因 EPERM（rename 失败）装不上，**别在它上面反复试**。
- **解释器就是仓库根 `.venv`**（**3.12.10**）⇒ Windows 用 `.venv\Scripts\python.exe`（`scripts/test.sh` 自动探测，不必手写）。
  ✅ 2026-10-11 订正：`.codebuddy/memory/MEMORY-REF.md` 曾记「仓库里**没有** `.venv`、要用 `…\.workbuddy\binaries\python\…`」——
  那条**已过期**（第 81 期的实测，此后 `.venv` 已建好）。
  ⚠️ **别把 `.venv` 升到 3.13+**（也用 `.workbuddy\binaries\python\versions\3.14.3` 直跑全量）：`quickjs` 只有 cp38–cp312
  预编译包 ⇒ 3.13+ 上 import 失败、`jssandbox.available()` 为假，`tests/test_js_sandbox.py` 的 **13 例会静默跳过**
  （第 117 期实测：`.venv` 下 2412 例 / 13 skipped，3.14 下同一份代码 2411 例 / 26 skipped —— 差的就是这 13 例，**全绿会骗人**）。
- ⚠️ **本机 `/usr/bin/env` 是个会吞输出的 shim**：`env A=1 cmd` **不执行 `cmd`、什么都不打印、退出码还是 0**
  （实测连 `env FOO=bar echo hi` 都无输出）⇒ 给命令加环境变量一律用**前缀赋值**（`FOO=bar cmd`），别用 `env`；
  历史上它曾让「跑 pytest」得到空日志 + 假成功。`scripts/*.sh` 已按此写。
- **跑 `build` / `deploy` / `pytest` 前先 `$env:NODE_OPTIONS=''`**：IDE 注入的 safe-delete shim 会拦 Vite 清 `outDir` 与
  `deploy.mjs` 的删除（报 `checkBulkDeleteGuard` / 「No active Node.js version」）⇒ 不生效时会误判成「改动没生效」。
  `scripts/*.sh` 已内置，直跑命令时要自己带。
- 同一个 safe-delete shim 也拦 **PowerShell `Remove-Item`**（**静默不删**）与不带 `-Encoding` 的 `Out-File`
  ⇒ 清临时产物用删除工具、写文件显式给编码（别以为命令报错才算失败）。

## 2. 文件读写（编码坑）

- **`write` 工具落的临时文件在 `C:\Users\qingr\Temp\`**，而 pwsh 的 `$env:TEMP` 是 `…\AppData\Local\Temp`：
  `git commit -F "$env:TEMP\nf_msg.txt"` 会报 `fatal: could not read log file '…': No such file or directory`（提交未发生、`git add` 的暂存还在）。
  ⚠️ **后果比看上去严重**：提交失败后**暂存区不会清空**，那一笔的内容会被**下一笔提交悄悄带走**（第 103 期：给 RanobeDB 缺陷修复准备的那一笔并进了系列那一笔）
  ⇒ ① `git commit -F` 一律给**完整显式路径**（`C:\Users\qingr\Temp\nf_msg.txt`）；
  ② 每笔提交后核 `git log --oneline` 的笔数，收尾用 `git show --stat <hash>` 核内容。
- **读中文 / JSON 文件一律用 `read` 工具**：pwsh 控制台是 GBK，`Get-Content package.json -Raw | ConvertFrom-Json` 报
  「传入的对象无效」、`Get-Content docs\*.md` 满屏乱码 —— **都不是文件坏了**，是 pwsh 读错了。
- **临时 `.ps1` 只用 ASCII**（或写成带 BOM 的 UTF-8）：`write` 落的是**无 BOM 的 UTF-8**，而 Windows PowerShell 对无 BOM 文件按 ANSI（GBK）解码
  ⇒ 全角字符（`：`、`（`）被当成多字节乱码，解析报 `字符串缺少终止符: "`（**脚本一行都没跑**）。同理，`.ps1` 里不要用中文做正则 / 路径字面量。
- **pwsh 的 `> $out 2>&1` 写的是 UTF-16LE**：用 `encoding="utf-8"` 读会得到夹 `\x00` 的乱码、**搜不到任何关键词**
  （曾据此白读一轮「exit 0 但没有汇总行」）⇒ 读这类日志要 `encoding="utf-16"`。

## 3. 网络

- **本机 DNS 被上游污染**（与代码无关）：`openlibrary.org` / `www.goodreads.com` / `www.googleapis.com` 在本机解析到的是**别人的网段**
  （Facebook 的 `31.13.x` / `128.242.x`），而 `8.8.8.8` 给的是正确地址；`hosts` 里**没有**自定义行、`1.1.1.1` 的 UDP/53 无应答。
  ⇒ 这三家的**真机探活 / 详情核验在本机做不了**；探针连不上时**先按 DNS 归因**（应用内体检会报 `dns_polluted` 并把两边地址写进原因），
  **别去改选择器或超时**。
- **出网走本机代理 `127.0.0.1:7897`**；而本机根证书链含**自建 CA** ⇒ 已设 **User 级 `NODE_OPTIONS=--use-system-ca`**
  （须**完全重启 IDE** 才生效，否则 Node 侧 HTTPS 会因证书链断而失败）。
- **跑 pytest 前清空全部 proxy 变量**（`HTTP_PROXY` / `HTTPS_PROXY` / `http_proxy` / `https_proxy` / `NO_PROXY` / `no_proxy`）：
  `httpx` 0.28.1 解析 `NO_PROXY` 里的方括号 IPv6（`[::1]`）会生成畸变 mount `all://*[::1]`，于是**任何真实 `BrowserClient` 用例**炸
  `httpx.InvalidURL: Invalid port: ':1]'`（曾据此误判出 45 个「回归」）。**只去掉方括号不够，必须整组清空**（`scripts/test.sh` 已内置）。
- **GHCR 的 `tags/list` 有缓存**：镜像构建 success 之后十几分钟，tag 列表里仍可能没有刚推上去的那个 tag
  ⇒ 判「tag 推没推上去」要**按 tag 取 manifest**（`GET https://ghcr.io/v2/<owner>/<repo>/manifests/<tag>`，带 `Bearer` pull token），
  并用随便编的 tag 回 404 做对照，否则分不清「真存在」与「这个端点不校验」。
- **计时类测量用 `curl`**（`-w "%{time_total} %{size_download}"`），**别用 PowerShell `Invoke-RestMethod`**
  （解析大 JSON 会严重虚高耗时，曾把 65 ms 测成 613 ms）。

## 4. 浏览器冒烟

- 本机**无 Chrome** ⇒ `playwright-cli open --browser=msedge`（走系统 Edge 通道，免下载）；直接 `open` 会失败。
- 注入 `nf_token` 不稳（首屏会 401 并把刚注入的 token 清掉）⇒ **直接走登录表单**（`admin/changeme` 点「进入」）。
- 该外壳下 `getByRole` 常匹配不到 ⇒ 用 DOM 文本 / DOM 遍历点按钮；`run-code` 传 JS **只用单引号**（别用 `\"` 转义）；
  该沙箱里 `setTimeout` 可能缺失 ⇒ 竞态类验证改由 Vitest 钉。
- `snapshot` 直接打到 stdout（`--filename` 可能不落盘）⇒ 重定向到 `/tmp` 再读，别落仓库根；
  换了产物要**带 `?nc=N` goto**（普通 `reload` 用旧 bundle，会误判成「改动没生效」）。
- **`ui-smoke.ps1`**（`.codebuddy/tools/ui-smoke.ps1`，机器级三档冒烟：`open →（可选）登录 → 每档 set viewport → 量布局 → 截图`；
  `-CleanOnly` 清残留）—— 三个会让它**静默挂死**的坑（2026-10-03 已全部修进脚本）：
  ① `~/.agent-browser/default.pid|default.port` 残留指向**已死进程** ⇒ CLI 永久等待、不启新守护进程（`open` 零输出挂死）；
  ② **PowerShell 管道 + 冷启动死锁**：首个 `open` spawn 的守护进程会**继承 PS 管道句柄** ⇒ `& agent-browser … 2>&1 | …` 永远等不到流结束
  （cmd / `.bat` 不受影响）⇒ 首个 open 走临时 `.bat`，且**别用 `Start-Process -Wait`**（它等整棵进程树）；
  ③ `eval` 传的 JS **只能用单引号**并放进 **here-string**。
  `-Widths` 用**空格**分隔（逗号会被 `.cmd` 转发吃掉）；默认 `-Profile ~/.agent-browser-profile/novelforge`（**存着登录态，别删那个目录**）。
  ⚠️ 360 档判据要**看 `off` 不能只看 `ovf`** —— 溢出常被内部 `overflow-x:auto` 容器吸收，`ovf` 仍是 false。

## 5. 端口与实例

- **不认识的 python 进程一律不 kill**（本机常有并行会话的实例）：`8791` 常被旧代码实例占、`8993` 是测试 compose、`8992` 是生产容器；
  自建实例用新端口（`scripts/dev-instance.sh`，默认 8412）。
- 多实例共用同一 `CONFIG_DIR` 会共享日志目录 ⇒ 验证日志 / 合并类行为要换全新目录（`scripts/dev-instance.sh` 每次建独立目录）。

---

> 本文件由**第 117 期**从 `AGENTS.md` §4/§5 与 `.codebuddy/memory/MEMORY-REF.md`「运行 / UI 验证」节**搬家**而来（不是新增知识，是收敛到唯一落点）；
> `MEMORY-REF.md` 原地只留指针。改这里的判据时，同批检查 `AGENTS.md` §5 的指针是否需要跟着改。
