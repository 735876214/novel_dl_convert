# NovelForge（novel_dl_convert）

TXT 小说转 EPUB 工具，融合 Fanqie-novel-Downloader / kaf-cli / txt2epub / denovel 的思路。
面向 NAS / 服务器部署，输入与导出目录**物理分离**，避免源文件与成品混在一起。

## 功能

- 多正则 + 缩进降级 + AI 兜底的章节识别（`-t` 可调试正则）
- 编码多层 fallback（utf-8-sig / utf-8 / gb18030 / gbk / big5）
- 文本精排、繁体转简体（opencc）
- 三级元数据（文件名 / 正文头部 / 在线补全）
- 基于 ebooklib 的 EPUB 组装（HTML 净化 + 封面）
- 可插拔书源适配器（已含 Gutenberg 公版源）
- FastAPI 服务：上传即转、按路径转换、列出文件、下载成品

## 目录约定（输入 / 导出分离）

| 目录 | 容器内 | 作用 |
|------|--------|------|
| `./input`  | `/app/input`  | 待转换的 txt / 电子书源文件 |
| `./output` | `/app/output` | 生成的 epub 等成品 |
| `config.yaml` | `/app/config/config.yaml` | 转换行为配置（只读） |

目录路径由环境变量 `INPUT_DIR` / `OUTPUT_DIR` / `CONFIG_DIR` 控制，默认值即上方容器内路径。

## 命令行

```bash
pip install -r requirements.txt

# 转换单个文件（显式指定输入与导出）
python -m novelforge 小说.txt -o ./output --traditionalize

# 批量转换目录（省略路径时默认用 INPUT_DIR / OUTPUT_DIR 环境变量）
python -m novelforge ./input -o ./output

# 本地不设环境变量时，也支持省略路径（回退到 /app/input、/app/output）
python -m novelforge

# 测试某标题是否能被正则识别
python -m novelforge -t "第一章 开端"
```

## Docker / NAS 部署（输入导出分离）

```bash
# 在仓库目录下
docker compose up -d --build
```

- 访问 http://<NAS-IP>:8000 上传 txt 转 EPUB
- **输入文件放 `./input`**，转换后**成品落在 `./output`**，两者互不影响
- 配置改 `./config.yaml`（已只读挂载进容器）
- Synology Container Manager / QNAP Container Station 均可直接导入本 `docker-compose.yml`

### 目录结构

```
novel_dl_convert/
  docker-compose.yml   部署：input / output / config.yaml 三处挂载
  Dockerfile
  config.yaml          转换行为配置
  .env.example         环境变量示例
  novelforge/          Python 包
    cli.py             命令行入口
    server.py          FastAPI 服务（NAS 部署）
    config.py          目录与配置解析（输入/导出分离核心）
    core/              预处理 / 分章 / 元数据 / EPUB 组装 / 管线
    sources/           书源适配器
```

## 合规说明

下载功能默认关闭，仅对接公版书源（Project Gutenberg）。使用其他书源请遵守目标站点
robots.txt 与服务条款，仅限合法用途。
