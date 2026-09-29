"""NovelForge — TXT 小说转 EPUB 工具。

融合 Fanqie-novel-Downloader / kaf-cli / txt2epub / denovel 的思路：
- 多正则 + 缩进降级 + AI 兜底的章节识别
- 编码多层 fallback、繁体转换、文本精排
- 三级元数据（文件名 / 正文 / 在线）
- 基于 ebooklib 的 EPUB 组装（净化 + 封面）
- 可插拔书源适配器 + 公版源下载
- FastAPI 服务，便于 NAS 部署
- 输入目录自动监听 + 活动日志（时间 / 文件名 / 操作 / 成败）
"""

# ⚠️ 这里**刻意不放** `__version__`：版本号的唯一真值源是仓库根 `VERSION` 文件
# （`novelforge/server.py::_read_version()` 读它，只由 `GET /health` 下发）。
# 早先这里的 `__version__ = "0.5.0"` 一直没跟着升，是一条会误导人的**第二份版本**，
# 第 79 期删掉（全仓无引用）。要版本号请读 `VERSION` 或调 `/health`，别再写一个字面量。
