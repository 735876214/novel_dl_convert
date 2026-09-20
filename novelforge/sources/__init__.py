"""书源适配器层：新增站点只需新增一个 SourceAdapter 子类并用 @register 注册。"""

from .base import SourceAdapter, REGISTRY, register  # noqa: F401
from . import gutenberg  # noqa: F401  注册公版源
# 刻意**不**导入 generic：它是给人复制用的模板，类里两个抽象方法都还没实现，
# 注册进 REGISTRY 只会让每次 /api/search 多一条「书源 generic 搜索失败」的假失败日志。
from .manager import DownloadManager  # noqa: F401
from . import store  # noqa: F401
store.load_user_sources()  # 启动时自动加载用户添加的书源（CONFIG_DIR/sources/*.json）
