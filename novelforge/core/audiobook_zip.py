"""整本有声书打包成 ZIP（第 171 期）—— **流式**写，不落临时大文件。

为什么不是「先 zip 到临时文件再 FileResponse」：一本 7,000 轨的有声书可能是几十 GB，
落盘一份等于把磁盘和时间都翻倍；这里用 `zipfile` 写一个**不可 seek 的管道**，
边压边发（ZIP_STORED，音频本身已压缩，再 deflate 只烧 CPU）。

⚠️ `zipfile` 对不可 seek 的输出会改用 data descriptor（`_Tellable` 包装），这是标准
ZIP 的合法形态；测试里用 `zipfile.ZipFile(BytesIO(...))` 读回校验。
"""
from __future__ import annotations

import io
import queue
import threading
import zipfile

_CHUNK = 1024 * 1024
_QUEUE_MAX = 8


class _Writer(io.RawIOBase):
    """把 `zipfile` 的写入转成队列；`tell/seek` 不可用 ⇒ 触发 data descriptor 路径。"""

    def __init__(self) -> None:
        self.q: "queue.Queue[bytes | None]" = queue.Queue(maxsize=_QUEUE_MAX)

    def writable(self) -> bool:
        return True

    def write(self, b) -> int:                       # noqa: ANN001 —— RawIOBase 约定
        self.q.put(bytes(b))
        return len(b)


def stream_zip(files) -> "object":
    """`files = [(归档内文件名, 本地路径), …]` → 逐块产出 ZIP 字节的生成器。

    生产者线程只读文件与写队列；读取端（Starlette）慢时队列会反压（maxsize=8），
    不会把整本读进内存。任何异常都只结束流（客户端收到的是不完整 ZIP，而不是 500 后
    再拼半截 —— 分块响应已经发出去了，改不了状态码）。
    """
    w = _Writer()

    def produce() -> None:
        try:
            with zipfile.ZipFile(w, "w", compression=zipfile.ZIP_STORED,
                                 allowZip64=True) as zf:
                for name, path in files:
                    with zf.open(str(name), "w") as dst:
                        with open(path, "rb") as src:
                            while True:
                                chunk = src.read(_CHUNK)
                                if not chunk:
                                    break
                                dst.write(chunk)
        except Exception:                            # noqa: BLE001 —— 见 docstring
            pass
        finally:
            w.q.put(None)

    t = threading.Thread(target=produce, name="audio-zip", daemon=True)
    t.start()
    while True:
        chunk = w.q.get()
        if chunk is None:
            break
        yield chunk
    t.join(timeout=1.0)
