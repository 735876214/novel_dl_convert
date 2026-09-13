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

### 部署方式：直接拉预构建镜像（源码 + 依赖已烤进镜像）

镜像 `ghcr.io/735876214/novel_dl_convert:latest` 由 GitHub Actions 在每次推送到 `main` 时自动构建并发布，
**源码与全部 Python 依赖已在「构建镜像时」烤进镜像**——不需要 NAS 本地 build，也不需要容器启动时 clone 源码。
因此在 NAS 上**只需要一个 `docker-compose.yml` 文件**，一条命令即可运行：

```bash
# 在 NAS 上建个目录，只放 docker-compose.yml（整份文件已含镜像地址与挂载配置）
mkdir -p novel_dl_convert && cd novel_dl_convert
# 把本仓库的 docker-compose.yml 下载/拷到这个目录

# 启动：自动从 ghcr.io 拉取「已含源码+依赖」的镜像并运行（无需 git / 无需 build / 无运行时 clone）
docker compose up -d
```

> 首次会下载镜像（含 Python 依赖，约几百 MB，视网速 1~3 分钟，仅此一次，之后本地有缓存）；
> 镜像下载完成即**秒级启动**，彻底告别之前「启动时 git clone 源码」的 2~4 分钟等待。
> 之后日常重启 / NAS 重启恢复都是秒级。

> 数据目录（`input/` `output/` `config/` `cookies/` `cache/`）首次启动由 Docker 自动创建，无需手动 `mkdir`；
> 配置放 `./config/config.yaml`（留空则应用回退到内置默认值）。

- 访问 http://<NAS-IP>:8000 上传 txt 转 EPUB
- **输入放 `./input`，成品落 `./output`**，互不影响
- 在线书源：`POST /search`、`POST /download`；内容预览：`GET /content?url=`、`GET /supported?url=`
- Synology Container Manager / QNAP Container Station：直接导入本目录的 `docker-compose.yml` 即可

### 更新代码

仓库推新后，GitHub Actions 会自动重建并发布新镜像。NAS 上拉取最新镜像即可：

```bash
docker compose pull && docker compose up -d
```

### 为什么既没有本地 build、也没有运行时 clone

之前两种方案都有等待：免 build 方案在**容器启动时** `git clone` 源码（2~4 分钟）；
本地 build 方案则要求 NAS 能 build 镜像（部署平台常拿不到 Dockerfile）。
现改为 **CI 构建并把「源码 + 依赖」烤进 `ghcr.io` 公开镜像**：NAS 只是下载一个现成镜像，
既不 build 也不 clone，部署后等待时间降到最低、更新也只需 `docker compose pull`。

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
