"""AI 分章兜底：正则优先，疑难（零标记 / 命中率低）再调 LLM 核验与补漏。

设计要点（避免全量丢给 AI 又贵又慢）：
- 正则先把整本书压成候选标题行；只有「零命中」或「命中率过低」才触发 AI。
- 大书按窗口切片（带重叠）逐片让 AI 标出章节起始偏移，再合并去重。
- 结果与 (model + 文本哈希) 绑定做文件缓存，重复文件不二次计费。
- 用独立线程跑新事件循环，兼容 CLI（同步）与 Web 服务（已有运行中的 loop）。
- 任何出错都按 fallback（默认 regex）降级，保证管线不中断。
"""
import asyncio
import concurrent.futures
import hashlib
import json
import pathlib

import httpx

from . import detect as regex_detect

WINDOW = 6000          # 单窗口字符数
OVERLAP = 400          # 窗口重叠，消除边界割裂
MAX_WINDOWS = 200      # 成本上限，超出则降级正则
CACHE_DIR = pathlib.Path(
    __import__("os").environ.get("CACHE_DIR", "") or str(
        pathlib.Path(__import__("os").environ.get("CONFIG_DIR", "/app/config")) / "cache"
    )
)


def _run_in_thread(coro):
    """在独立线程里用新事件循环执行协程，避免与调用方已有 loop 冲突。"""
    def _worker():
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    with concurrent.futures.ThreadPoolExecutor(1) as ex:
        return ex.submit(_worker).result()


class HybridChapterDetector:
    def __init__(self, cfg: dict):
        cfg = cfg or {}
        cd = cfg.get("chapter_detection", {}) or {}
        llm = cfg.get("llm", {}) or {}
        self.mode = cd.get("mode", "hybrid")
        self.ctx = cd.get("context_lines", 3)
        self.fallback = cd.get("fallback", "regex")
        self.api_key = llm.get("api_key")
        self.base_url = (llm.get("base_url") or "https://api.openai.com/v1").rstrip("/")
        self.model = llm.get("model", "gpt-4o-mini")
        self.cache_dir = CACHE_DIR

    # ---- 公开入口 ----
    async def detect(self, text: str) -> list[dict]:
        bounds = regex_detect.regex_bounds(text)
        confident = bool(bounds) and len(bounds) * 2000 >= len(text)

        if self.mode == "regex":
            return regex_detect.split_by_offsets(text, bounds) if confident else regex_detect._split_by_indent(text)
        if self.mode == "ai":
            ai = await self._ai_bounds(text)
            return regex_detect.split_by_offsets(text, ai)
        # hybrid：正则自信则直接用；否则用 AI 补漏，并与正则结果合并
        if confident:
            return regex_detect.split_by_offsets(text, bounds)
        ai = await self._ai_bounds(text)
        merged = self._merge_bounds(bounds, ai)
        return regex_detect.split_by_offsets(text, merged) if merged else regex_detect._split_by_indent(text)

    # ---- 合并正则与 AI 的边界（去近邻重复）----
    def _merge_bounds(self, a, b):
        merged = list(a)
        for off, title in b:
            if not any(abs(off - o) < 60 for o, _ in merged):
                merged.append((off, title))
        return sorted(merged)

    # ---- AI 分块识别 ----
    async def _ai_bounds(self, text: str) -> list[tuple[int, str]]:
        cache_key = self._cache_key(text)
        cached = self._read_cache(cache_key)
        if cached is not None:
            return cached

        n = len(text)
        starts = range(0, max(1, n), WINDOW - OVERLAP)
        windows = min(len(list(starts)), MAX_WINDOWS)
        results = []
        for i in range(windows):
            s = i * (WINDOW - OVERLAP)
            chunk = text[s : s + WINDOW]
            try:
                bounds = await self._call_llm(chunk)
            except Exception:
                bounds = []
            for off, title in bounds:
                if 0 <= off <= len(chunk):
                    results.append((s + off, title))

        # 去重 + 单调递增
        results = sorted({(off, t) for off, t in results})
        out = []
        for off, t in results:
            if not out or off > out[-1][0] + 5:
                out.append((off, t))
        self._write_cache(cache_key, out)
        return out

    async def _call_llm(self, chunk: str) -> list[tuple[int, str]]:
        system = (
            "你是一个中文小说章节切分器。下面是一段文本，字符偏移相对本段起点（0 基准）。"
            "请找出每一个章节 / 卷 / 序章 / 楔子的起始位置。"
            "只输出一个 JSON 数组，元素为 {\"offset\":<整数>,\"title\":<字符串>}，"
            "不要输出任何正文或多余说明；若没有章节标记则返回 []。"
        )
        user = "TEXT:\n" + chunk
        content = await self._chat(system, user)
        return self._parse(content)

    async def _chat(self, system: str, user: str) -> str:
        async with httpx.AsyncClient(timeout=60, verify=False) as c:
            r = await c.post(
                self.base_url + "/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "temperature": 0,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

    @staticmethod
    def _parse(content: str) -> list[tuple[int, str]]:
        try:
            # 容忍 ```json 代码块包裹
            s = content.strip()
            if s.startswith("```"):
                s = s.split("```")[1]
                if s.lower().startswith("json"):
                    s = s[4:]
            data = json.loads(s)
            out = []
            for item in data:
                off = int(item.get("offset", -1))
                title = str(item.get("title", "")).strip()
                if off >= 0 and title:
                    out.append((off, title))
            return out
        except Exception:
            return []

    def _cache_key(self, text: str) -> str:
        h = hashlib.sha256((self.model + "|" + text).encode("utf-8")).hexdigest()
        return h

    def _read_cache(self, key: str):
        p = self.cache_dir / f"ai_{key}.json"
        if p.exists():
            try:
                return [(o, t) for o, t in json.loads(p.read_text(encoding="utf-8"))]
            except Exception:
                pass
        return None

    def _write_cache(self, key: str, bounds):
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            p = self.cache_dir / f"ai_{key}.json"
            p.write_text(json.dumps(bounds, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
