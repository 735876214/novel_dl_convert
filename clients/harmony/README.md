# NovelForge 鸿蒙端（HarmonyOS NEXT）

NovelForge 的 HarmonyOS 客户端。**R1 路线**：登录 / 书架 / 详情 / 设置用原生 ArkTS，
阅读面用 ArkWeb 载入 NAS 上**已有的那套 SPA**。

## 为什么阅读面不原生重写

书内版式注入、批注锚定、四套子阅读器（PDF / 漫画 / 音频 / TXT-EPUB）全在
`frontend/src/views/ReaderView.vue` 那 141 KB 里，位置坐标是渲染容器的 `textContent.length`。
端上重写一遍 = 第二份实现（本项目 AGENTS §1 明令禁止），而且进度对不齐。
所以端上只做两件事：**首帧前把令牌塞进 localStorage**，**把这一回正文缓存到本机**。

## 构建（已实测通过）

本机工具链（DevEco Studio 自带，不需要外部安装）：

| 组件 | 路径 |
|---|---|
| hvigor | `C:\Program Files\Huawei\DevEco Studio\tools\hvigor\bin\hvigorw.js` |
| ohpm | `C:\Program Files\Huawei\DevEco Studio\tools\ohpm\bin` |
| node | `C:\Program Files\Huawei\DevEco Studio\tools\node\node.exe` |
| JDK | `C:\Program Files\Huawei\DevEco Studio\jbr` ← **必须加进 PATH**，否则 `PackageHap` 报 `spawn java ENOENT` |
| SDK | `C:\Program Files\Huawei\DevEco Studio\sdk`（API 26 / HarmonyOS 26.0.0） |

```powershell
$root='C:\Program Files\Huawei\DevEco Studio'
$env:DEVECO_SDK_HOME="$root\sdk"
$env:NODE_HOME="$root\tools\node"
$env:JAVA_HOME="$root\jbr"
$env:PATH="$root\jbr\bin;$root\tools\node;$root\tools\ohpm\bin;$env:PATH"
Set-Location <本目录>
& "$root\tools\node\node.exe" "$root\tools\hvigor\bin\hvigorw.js" `
  --mode module -p product=default -p buildMode=debug assembleHap --no-daemon
```

产物：`entry\build\default\outputs\default\entry-default-unsigned.hap`（约 205 KB）。

### 构建路上踩的三个坑（都已修在工程里）

1. **`compatibleSdkVersion` 的写法按 API 分两套**：API 10–25 是 `"5.0.0(12)"`，
   **API 26 起改成 `"26.0.0"`**（写 `"26.0.0(26)"` 或数字 `26` 都会被 schema 拒）。
2. **`PackageHap` 需要 java**，DevEco 的 JBR 不在 PATH 里就会 `spawn java ENOENT`，
   而 hvigor 只报「Unknown Error 00308018」，真因得去 `.hvigor\outputs\build-logs\build.log` 看。
3. **`arkts-no-props-by-index`**：ArkTS 不允许对 interface 字段做下标赋值，
   `header['Authorization'] = ...` 编译不过，必须写两个完整对象字面量
   （见 `entry\src\main\ets\common\Api.ets:58`）。

## 未验证的部分（重要，别当成已跑通）

| 项 | 状态 | 原因 |
|---|---|---|
| 签名 | **未做** | 需要调试证书；本机 `~\.ohos\config` 为空，DevEco 自动生成调试证书要登录华为账号 |
| 安装 / 真机运行 | **未做** | `hdc list targets` 返回 `[Empty]`，本机没有连接设备 |
| 与服务端联调 | **未做** | 同上；接口契约按 `tests/test_client_contract.py` 的 13 例快照写，但没对真实 NAS 跑过 |
| 交互观感 | **未做** | 原生页面的视觉稿有（`../harmonyos-mockup/`），但 ArkUI 实现没在真机上看过 |

签名 + 侧载的下一步：DevEco 里 `File → Project Structure → Signing Configs` 勾选
「Automatically generate signing」（需登录华为账号），把生成的 `signingConfigs` 写进
`build-profile.json5`，再 `hdc install entry-default-signed.hap`。

## 工程结构

```
AppScope/app.json5                     包名 com.novelforge.reader / versionName 1.0.0
build-profile.json5                    products.compatibleSdkVersion "26.0.0"
entry/src/main/module.json5            INTERNET + GET_NETWORK_INFO 权限
  resources/base/profile/network_config.json   cleartextTrafficPermitted: true（NAS 是 http://）
  ets/common/Api.ets                   唯一出网入口；错误分三类（offline / 401 / 服务端 detail）
  ets/common/Session.ets               服务器地址 + 令牌的持久化（@kit.ArkData 的 preferences）
  ets/common/Cache.ets                 一回正文的本地缓存 + 离线阅读视图
  ets/common/Theme.ets                 纸 / 夜 / 护眼三档配色
  ets/common/Models.ets                接口返回类型（与契约测试的快照同形）
  ets/pages/LoginPage.ets              服务器地址 + 口令 + GET /health 预检与版本门禁
  ets/pages/ShelfPage.ets              GET /api/books?limit=0，网格/列表切换
  ets/pages/DetailPage.ets             GET /api/books/{bid}，按卷分组目录
  ets/pages/ReaderPage.ets             ArkWeb 载入 #/read/{bid}?chapter={index}
  ets/pages/SettingsPage.ets           外观主题 / 服务器 / 设备标识 / 清空本地数据
```

## 端上三条硬约束

1. **只读源**：不写回 NAS 上的任何书文件，进度只经 `PUT /api/books/{bid}/progress`。
2. **不造假数据**：拿不到就如实说「连不上 NAS」，不铺假书目、不猜进度。
3. **不自造判据**：章节编号只用服务端给的 `index` 与 `title`；阅读状态角标不自算；
   令牌过期一律回登录页，不在端上续期。

## 与服务端的接口面

登录 `POST /api/auth/login` → 书架 `GET /api/books` → 详情 `GET /api/books/{bid}` →
章节 `GET /api/books/{bid}/chapter/{index}` → 进度 `GET/PUT /api/books/{bid}/progress` →
会话 `POST /api/books/{bid}/session` → 批注 `/api/books/{bid}/annotations` →
设备偏好 `/api/prefs/devices/{did}` → 版本 `GET /health`。

这九组的字段形状由仓库里的 `tests/test_client_contract.py`（13 例）钉住，
其中 `test_version_is_single_source` 还钉了 `/health.version` 与 `VERSION` 文件一致。
