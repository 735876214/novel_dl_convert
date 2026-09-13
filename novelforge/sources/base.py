from abc import ABC, abstractmethod

import httpx


class SourceAdapter(ABC):
    """书源适配器基类：search 返回候选列表，download 落地文件。"""

    name: str = "base"
    # 类浏览器标头（伪造标头 / Cookie 持久化由调用方注入 client 完成）
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    @abstractmethod
    async def search(self, client: httpx.AsyncClient, title: str):
        ...

    @abstractmethod
    async def download(self, client: httpx.AsyncClient, item: dict, dest):
        ...


REGISTRY: dict[str, type[SourceAdapter]] = {}


def register(cls):
    REGISTRY[cls.name] = cls
    return cls
