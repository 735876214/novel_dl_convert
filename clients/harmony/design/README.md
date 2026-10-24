# 鸿蒙端视觉稿

`harmonyos-client.html` —— 单文件、零外部依赖的**可交互**样式稿（约 110 KB），
用浏览器直接打开即可，不需要起服务：

```
start clients\harmony\design\harmonyos-client.html
```

它和 `../entry/src/main/ets/pages/` 里的 ArkTS 页面共用同一套 token
（取自 `frontend/src/assets/theme/tokens.css`，视觉层照搬 BookOrbit），
所以改样式时先改这份稿子、再对着改 ArkUI，不要反过来。

## 里面有什么

- 登录（服务器地址 + `GET /health` 预检 + 版本门禁）
- 书架（网格 / 列表两种排布）
- 详情（按卷分组目录，只显示服务端给的 `title` 与 spine `index`）
- 阅读面（纸 / 夜 / 护眼三档，**全站生效**，不只是阅读面）
- 设置、关于
- 两个覆盖层：连不上 NAS、服务端版本过旧

## 参数

URL 查询参数可以直开某个画面，便于截图与评审：

```
?view=login|shelf|detail|read|settings|about|offline|stale
&skin=paper|night|green
&tools=1            阅读面唤出工具栏
&sheet=toc|anno     目录 / 批注浮层
&book=hlm&ch=1      指定书与回目
```

例：`harmonyos-client.html?view=read&skin=night&tools=1`

## 截图不入库

21 张真渲染截图（共约 7.9 MB）**不提交**，需要时用 Edge 无头重新生成到
`design/shots/`（该目录已在 `.gitignore` 里）：

```powershell
$edge='C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
$html=(Resolve-Path .\clients\harmony\design\harmonyos-client.html).Path
New-Item -ItemType Directory -Force .\clients\harmony\design\shots | Out-Null
& $edge --headless=new --disable-gpu --hide-scrollbars --no-first-run `
  --user-data-dir="$env:TEMP\edge-harmony" --window-size=1440,1120 `
  --virtual-time-budget=2500 `
  --screenshot=".\clients\harmony\design\shots\01-login.png" `
  "file:///$html`?view=login"
```

把 `?view=…` 换成上表任一组合即可补齐其它画面。

⚠️ 两个坑：`--screenshot` **必须给绝对路径**（相对路径按 Edge 自己的 cwd 解析，
会报「系统找不到指定的路径」）；`file:///` 后面要用正斜杠。
