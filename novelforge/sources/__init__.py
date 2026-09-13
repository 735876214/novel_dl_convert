"""书源适配器层：新增站点只需新增一个 SourceAdapter 子类并用 @register 注册。"""

from .base import SourceAdapter, REGISTRY, register  # noqa: F401
from . import gutenberg  # noqa: F401  注册公版源
from . import generic  # noqa: F401   注册模板源（示例）
from .manager import DownloadManager  # noqa: F401
