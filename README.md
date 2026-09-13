# NovelForge（novel_dl_convert）

TXT 小说转 EPUB 工具，融合 Fanqie-novel-Downloader / kaf-cli / txt2epub / denovel 的思路。
面向 NAS / 服务器部署，输入与导出目录**物理分离**，避免源文件与成品混在一起。

## 功能

- 多正则 + 缩进降级 + **AI 兜底**的章节识别（`-t` 可调试正则；配置 `llm.api_key` 后疑难章节自动调 LLM）
- 编码多层 fallback（utf-8-sig / utf-8 / gb18030 / gbk / big5）
- 文本精排、繁体转简体（opencc）
- 三级元数据（文件名 / 正文头部 / 在线补全）
- 基于 ebooklib 的 EPUB 组装（HTML 净化 + 封面）
- **可插拔书源适配器**：已含 Gutenberg 公版源，并附 `generic.py` 扩展模板
- **下载加固**：类浏览器标头伪造、Cookie 持久化（LWPCookieJar 落盘）、429 退避重试、域名替换、**原生 JS eval**（Node 执行站点解密脚本）
- **增量更新**：为下载得到的 txt 写 sidecar，日后只爬取新增章节再重转
- **内容预览 API**：`/content?url=...` 即时抓取清洗（不落盘即可完美预览），`/supported` 判断 URL 归属
- FastAPI 服务：上传即转、按路径转换、列出文件、下载成品、搜索、下载

## 目录约定（输入 / 导出 / 配置 / 缓存 各自独立）

| 宿主机 | 容器内 | 作用 |
|--------|--------|------|
| `./input`  | `/app/input`  | 待转换的 txt / 电子书源文件 |
| `./output` | `/app/output` | 生成的 epub 等成品 |
| `config.yaml` | `/app/config/config.yaml` | 转换行为配置（只读挂载） |
| `./cookies` | `/app/config/cookies` | 各书源 Cookie 持久化（下载功能，跨重启保留登录态） |
| `./cache`   | `/app/config/cache`   | AI 分章结果缓存（按文本哈希，重复文件不二次计费） |

目录路径由环境变量 `INPUT_DIR` / `OUTPUT_DIR` / `CONFIG_DIR` / `COOKIE_DIR` / `CACHE_DIR` 控制。

## 命令行

```bash
pip install -r requirements.txt

# 转换单个文件
python -m novelforge convert 小说.txt -o ./output --traditionalize

# 批量转换目录（省略路径时默认用 INPUT_DIR / OUTPUT_DIR 环境变量）
python -m novelforge convert ./input -o ./output

# 测试某标题是否能被正则识别
python -m novelforge convert -t "第一章 开端"

# 跨书源搜索（需先在 config.yaml 开启 download.enabled=true）
python -m novelforge search "三体"

# 下载书籍条目并转 EPUB（item 为 search 返回的某条 JSON；或给 --source/--url/--title）
python -m novelforge download --item '{"_source":"gutenberg","url":"...","title":"...","author":"..."}'

# 增量更新本地 txt（需先经 download 生成 .meta.json sidecar）
python -m novelforge update ./input/某书.txt
```

## Web 服务（NAS 部署）

### 第一步：把 docker-compose.yml 放到 NAS（只需这一个文件）

本仓库的 `docker-compose.yml` 已内置「启动自动拉取源码」逻辑：**容器启动时若发现挂载目录里缺 `start.sh`
（即源码不完整），会自动从 GitHub `git clone` 完整仓库到 `/app`**，自动修复此前「缺 start.sh / requirements.txt」
的报错。因此你在 NAS 上**只需要这一个 `docker-compose.yml` 文件**即可，其余源码由容器自动拉取，无需手动同步、也不用手拷文件。

```bash
# 在 NAS 上建个目录，只放 docker-compose.yml 即可
mkdir -p novel_dl_convert && cd novel_dl_convert
# 把本仓库的 docker-compose.yml 下载/拷到这个目录（单独这一个文件就够）
```

> 如果你本机已有完整 git 仓库，也可以直接 `git clone https://github.com/735876214/novel_dl_convert.git`
> 后 `docker compose up -d`——这种情况下源码已完整，容器会跳过 clone、直接用本地源码，启动更快。

### 第二步：启动（免 build，自动拉源码）

**默认免 build**：本仓库的 `docker-compose.yml` 基于官方 `python:3.12-slim` 镜像，挂载源码到容器、
启动时自动安装依赖并拉起服务，**不要求本地 build 镜像**（适合部署平台拿不到 Dockerfile 的环境）。

```bash
# 在 docker-compose.yml 所在目录（即 novel_dl_convert/）内执行
cd novel_dl_convert
docker compose up -d
```

> `input/` `output/` `cookies/` `cache/` `config.yaml` 会由 Docker 自动创建（bind 挂载），
> 首次启动无需手动 `mkdir`。`config.yaml` 若为空文件，应用会回退到内置默认值。

- 访问 http://<NAS-IP>:8000 上传 txt 转 EPUB
- **输入放 `./input`，成品落 `./output`**，互不影响
- 在线书源：`POST /search`、`POST /download`；内容预览：`GET /content?url=`、`GET /supported?url=`
- Synology Container Manager / QNAP Container Station：直接导入本目录的 `docker-compose.yml` 即可

### 启动速度（幂等，重启秒级）

启动逻辑在 `start.sh` 里做了**幂等检查**：

- **首次启动 / 容器重建**（依赖缺失）：才执行 `apt-get + pip install`，约 1~2 分钟。
- 若挂载目录里源码不完整（只有 `docker-compose.yml`），首次还会额外 `apt-get 装 git + git clone`（约再 +1~2 分钟，仅此一次）；之后源码已落地，重建也不再重复 clone。
- **日常重启**（同一容器，依赖已装）：`start.sh` 检测到 `node` 与关键 Python 包已存在，**直接跳过安装、秒级拉起 uvicorn** —— 不再每次重跑 `apt-get update`，NAS 重启 / 容器崩溃恢复等待从分钟级降到秒级。

> 依赖装在容器自身文件系统（非挂载的源码目录），所以「同一容器重启」时保留、可跳过；
> 只有「容器被重建」（如更换基础镜像）导致依赖丢失时才会再次完整安装。
> 若想让重建也秒级启动，见下方「可选自建镜像」。

### 为什么不需要 build（不强制本地 build）

此前部署失败（`failed to read dockerfile` / `pull access denied`）是因为 compose 要求本地 build 镜像，
而部署平台 / NAS 的 build 上下文拿不到完整 `Dockerfile`。现改为**直接用官方 Python 镜像 + 挂载源码**，
彻底绕开 Dockerfile 依赖，部署门槛最低、不再有 build 步骤。

### 首次运行需手动创建的目录

`input/`、`output/`、`cookies/`、`cache/` 若不存在，先建好再启动（避免被挂载成文件）：

```bash
mkdir -p input output cookies cache
```

### （可选，非必须）自建镜像以获得更快启动

若你的环境能正常 build、且希望启动更快，可基于仓库 `Dockerfile` 自行构建镜像（**这一步不是必须**）：

```bash
docker build -t novel_dl_convert .
# 然后把 docker-compose.yml 里的 image 改成 novel_dl_convert 并去掉 command / 源码挂载段
```

> 默认免 build 方案已可直接运行，无需执行上面的 build。

### 目录结构

```
novel_dl_convert/
  docker-compose.yml   部署：input / output / config / cookies / cache 五处挂载
  start.sh             幂等启动脚本（依赖已装则跳过 apt/pip，秒级启动）
  Dockerfile           Python 3.12-slim + Node.js（JS eval 用，可选自建镜像）
  config.yaml          转换行为配置
  .env.example         环境变量示例
  novelforge/          Python 包
    cli.py             命令行入口（convert/search/download/update）
    server.py          FastAPI 服务（NAS 部署 + 内容预览 API）
    config.py          目录与配置解析
    core/              预处理 / 分章 / AI 分章 / 网络加固 / 元数据 / EPUB 组装 / 管线
    sources/           书源适配器（gutenberg / generic 模板 / manager）
```

## 扩展一个新书源

复制 `novelforge/sources/generic.py` 为 `my_site.py`，改 `name` / `domains`，实现 `search()` 与
`fetch_book()`；若有字体加密 / 内容混淆，在 `decryption_js()` 返回解密片段，`render()` 会自动调用
Node 执行。加 `@register` 即可被 `/search`、`/download`、`/supported` 自动识别，零改核心。

## 合规说明

下载功能默认关闭，仅对接公版书源（Project Gutenberg）。使用其他书源请遵守目标站点
robots.txt 与服务条款，仅限合法用途。
