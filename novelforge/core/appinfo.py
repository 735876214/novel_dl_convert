"""应用自身的静态事实 —— 目前只有**版本号**。

## 为什么单独一个模块

版本号一度只有 `server.APP_VERSION` 一处，而 `core/updater.py` 要拿它做「有没有新版本」
的比较 —— 领域层于是只能 `import novelforge.server`（还得**延迟导入**才躲开循环）
⇒ **分层倒置**：`core/` 反向依赖 Web 层。`tests/test_layering_265.py` 现在钉住这条边界。

读 `VERSION` 这件事实在**领域**里（服务端 / CLI / 后台更新检查都要），不在 Web 层。
所以读取逻辑落在这里，`server.py` 与 `updater.py` 都往下依赖它。

## 口径

- 读到什么就报什么（不加工、不归一）；
- 读不到 ⇒ **哨兵值** + error 日志，不阻断启动（部署缺 `VERSION` 是运维问题，
  不该让整个应用起不来），但**绝不假装成一个具体版本号** ——
  那会把「部署不完整」伪装成「本应用就是那个版本」。
"""
from __future__ import annotations

import logging
import pathlib

#: 读不到 `VERSION` 时上报的**哨兵值**。刻意不是一个像样的版本号：
#: `updater.parse_version(VERSION_UNKNOWN) == (0, 0, 0)` ⇒ 任何真实版本都比它新，
#: 更新提示照常给出。
VERSION_UNKNOWN = "0.0.0-unknown"


def read_version() -> str:
    """从仓库根 / 镜像内的 `VERSION` 读版本号；读不到回 :data:`VERSION_UNKNOWN`。"""
    candidates = [
        pathlib.Path("/app/VERSION"),                                    # 容器内（Dockerfile COPY 到 /app）
        pathlib.Path(__file__).resolve().parents[2] / "VERSION",          # 开发态：core/appinfo.py → 仓库根
    ]
    for p in candidates:
        try:
            v = p.read_text(encoding="utf-8").strip()
        except Exception:
            v = ""
        if v:
            return v
    logging.getLogger("novelforge").error(
        "读不到 VERSION 文件（试过 %s）—— 版本号按 %s 上报。请确认 VERSION 进了仓库根 / 镜像",
        " / ".join(str(p) for p in candidates), VERSION_UNKNOWN)
    return VERSION_UNKNOWN
