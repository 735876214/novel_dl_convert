"""NovelForge — TXT 小说转 EPUB 工具。

融合 Fanqie-novel-Downloader / kaf-cli / txt2epub / denovel 的思路：
- 多正则 + 缩进降级 + AI 兜底的章节识别
- 编码多层 fallback、繁体转换、文本精排
- 三级元数据（文件名 / 正文 / 在线）
- 基于 ebooklib 的 EPUB 组装（净化 + 封面）
- 可插拔书源适配器 + 公版源下载
- FastAPI 服务，便于 NAS 部署
"""
__version__ = "0.3.0"
