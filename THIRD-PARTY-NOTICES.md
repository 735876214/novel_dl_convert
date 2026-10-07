# 第三方组件与许可证

本文件回答两件事：**本项目自己按什么许可分发**、**它用了哪些第三方组件、各自什么许可**。

> 第 110 期新增。此前仓库根目录**没有** `LICENSE`：MOBI/AZW3 直读引入了进程内依赖 `mobi`
> （GPL-3.0-only），把「许可证」从一个可以不写的话题变成了必须写清楚的话题。

## 一、本项目：AGPL-3.0

**GNU Affero 通用公共许可证第 3 版（AGPL-3.0）**，全文见仓库根目录 [`LICENSE`](LICENSE)。

理由（不是随手挑的）：本项目**进程内 import** 了两个 copyleft 组件 ——

| 组件 | 许可 | 用在哪 |
|---|---|---|
| `EbookLib` | **AGPL-3.0** | `novelforge/core/epub_builder.py`（唯一组装成品 EPUB 的地方，第 55 期起） |
| `mobi` | **GPL-3.0-only** | `novelforge/core/mobicache.py`（第 110 期：MOBI/AZW3 直读解包） |

GPLv3 ↔ AGPLv3 的兼容是**单向**的：GPLv3 的代码可以并入 AGPLv3 的作品，反过来不行。
两者合并后的正确落点就是 **AGPL-3.0** —— 所以本项目整体按 AGPL-3.0 分发，而不是 GPL-3.0。

**AGPL §13（网络交互）**：把本服务部署出去、让用户通过网络与之交互时，使用者有权取得
对应源码。本项目**没有闭源部分**：源码即部署物（`Dockerfile` 把源码与依赖一起烤进镜像，
见 README 的「为什么既没有本地 build、也没有运行时 clone」）。

## 二、运行时依赖（`requirements.txt`，会进生产镜像）

按已安装发行包的元数据读取（`importlib.metadata`：优先 `License-Expression`，回落
`License` / `Classifier`）。**不要凭记忆改这张表** —— 升级后重跑一次清单。

| 组件 | 许可 | 用途 / 备注 |
|---|---|---|
| `EbookLib` | **AGPL-3.0** | 组装成品 EPUB（决定本项目的许可证落点，见 §一） |
| `mobi` | **GPL-3.0-only** | MOBI/AZW3 直读解包（同上） |
| `fastapi` · `pydantic` | MIT | HTTP 服务层 |
| `starlette` | BSD-3-Clause | FastAPI 的 ASGI 基座 |
| `uvicorn` | BSD-3-Clause | ASGI 服务器 |
| `python-multipart` | Apache-2.0 | 表单 / 上传解析 |
| `httpx` · `httpcore` · `idna` | BSD-3-Clause | 出网（书源抓取、元数据抓取） |
| `h11` · `anyio` | MIT | httpx / starlette 的协议与并发基座 |
| `certifi` | MPL-2.0 | CA 证书包 |
| `beautifulsoup4` · `soupsieve` | MIT | HTML 解析 |
| `lxml` | BSD-3-Clause | XPath（书源规则）与 XML 解析 |
| `PyYAML` | MIT | `config.yaml` |
| `Pillow` | MIT-CMU | 图片处理（封面缩放等） |
| `opencc-python-reimplemented` | Apache-2.0 | 繁体 → 简体 |
| `regex` | Apache-2.0 AND CNRI-Python | 书源正则的**超时**能力（软依赖，缺了退回长度上限） |
| `numpy` | BSD-3-Clause AND 0BSD AND MIT AND Zlib-acknowledgement | 相似书的 LSA 向量 |
| `croniter` | MIT | 逐库定时扫描 |
| `pypdfium2` | BSD-3-Clause / Apache-2.0（wheel 内含 PDFium，其自身许可见其发行包） | PDF 逐页渲染 |
| `rarfile` | ISC | `.cbr` 读取（**需外部解压器** bsdtar / unrar） |
| `redis` | MIT | 可选缓存层（不配 `NOVELFORGE_REDIS_URL` 时整层空操作） |
| `psycopg` / `psycopg-binary` | LGPL-3.0-only | 可选 PostgreSQL 后端（`NOVELFORGE_DB=pg`） |
| `loguru` | MIT | `mobi` 的传递依赖 |
| `standard-imghdr` | PSF-2.0 | `mobi` 的传递依赖（补 Python 3.13 移除的 `imghdr`） |
| `win32-setctime` | MIT | `loguru` 在 Windows 上的传递依赖 |
| `six` | MIT | `EbookLib` 的传递依赖 |
| `click` · `colorama` · `Pygments` · `python-dateutil` · `tzdata` · `packaging` · `typing_extensions` · `annotated-types` · `typing-inspection` · `opentelemetry-api` | BSD / MIT / Apache-2.0 / 双许可（各见其发行包） | 上面各组件的传递依赖 |

## 三、可选依赖（装了才有的能力；缺了一律**如实降级**，不假装有）

| 组件 | 许可 | 缺了会怎样 |
|---|---|---|
| `quickjs` | ⚠️ **上游未标注**（PyPI 元数据里 `license` 为空、无许可证 classifier，实测 1.19.4） | 书源规则的 `@js:` 片段回落 Node 通道，能力表如实标「非沙箱」。**部署/分发前建议自行向上游确认许可** |
| `pdfium`（`pypdfium2` wheel 内） | 见其发行包 | 无（wheel 自带） |
| `bsdtar`（`libarchive-tools`，系统包） | BSD-2-Clause | `.cbr` 打开返回 503「服务器缺少 RAR 解压能力（需 bsdtar 或 unrar）」 |
| `mobi` | GPL-3.0-only | MOBI/AZW3 章节接口返回 503「服务器缺少 MOBI 解包能力（需 mobi）」 |

## 四、仅开发 / 测试用（不进生产镜像）

`pytest` · `pluggy` · `iniconfig`（均 MIT），以及上面各组件的测试期传递依赖。

## 五、维护约定

1. 新增依赖后**必须**更新本文件与 `requirements.txt` 里那条注释（「为什么装 / 缺了会怎样」是
   本仓既有风格，见第 94 期那几条）。
2. 引入**新的 copyleft**（GPL / AGPL / LGPL）组件时，先照 §一 重新判断本项目的许可证落点；
   引入**未标注许可**的组件时，按 §三 那样显式记下来，不要默默放行。
3. 这张表按**已安装发行包的元数据**生成，不按记忆或上游首页文案写。
