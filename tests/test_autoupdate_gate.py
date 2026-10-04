"""第 93 期：**追更也过闸门** —— 补掉第 71 / 80 期口径里的那个「假开关」。

原先 `autoupdate.tick()` 枚举完 sidecar 就逐本 `manager.update_report`，**一次都不问闸门**。
而 `download.enabled` 的默认值是 **False**，设置页也明写着「关闭时书源仅做规则管理，
不搜也不下」—— 于是「关掉下载」这个开关对定时追更完全无效，它照常逐本外呼抓正文。
这正是第 71 期修 `/api/search` / `/api/download` / `/api/preview` 时漏掉的第四个调用方。

本文件钉三件事：

1. **闸门关 ⇒ 一次外呼都没有**。判据不是「报告里写了 blocked」，而是把 `_run_one` 换成
   记录调用的桩：一个都不许被调到（与 `test_sources_gate.py` 用必失败的桩钉「拦截先于业务」
   同一手法 —— 只看返回值的用例挡不住「先跑了再补一句抱歉」）。
2. **闸门开 ⇒ 照常逐本跑**。这一条还是**回归位**：`tick` 原先写的是无参
   ``DownloadManager()``，而构造函数签名是必填的 ``__init__(self, cfg: dict)`` ⇒ 每轮都在
   `except` 里退化成「构造下载器失败（本轮跳过）」，**定时追更从来没真正跑过一本**。
   既有用例钉不到它（要么 monkeypatch 掉 `tick`、要么只测候选枚举）。补 cfg 之后
   「mgr 能构造出来 ⇒ `_run_one` 真被调到」才成立。
3. **「被拦下」与「源上没有新章」在报告里分得开**：前者 `blocked` 非空且
   `skipped == total`，后者 `blocked` 为空。合成一句「新增 0 章」会把「你关着开关」
   说成「源站没更新」—— 那条提示比不提示更坏（用户会去查源站）。

⚠️ 全程零网络：`_run_one`（唯一外呼处）在本文件里一律换成桩。
"""
import pathlib

import pytest

from novelforge import config
from novelforge.core import autoupdate, library


def _set_download(monkeypatch, tmp_path, *, enabled: bool) -> None:
    """把配置覆盖层指到本用例的临时文件（与 `test_sources_gate.py` 同一手法：不动真实配置）。"""
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    config.save_overrides({"download": {"enabled": enabled}})


@pytest.fixture
def books(isolated, default_root):  # noqa: ARG001
    """三本**有留档**的书（sidecar 是「这本书是下载来的」的唯一持久痕迹）。

    只造登记与留档，不造正文 —— 本文件关心的是「有没有外呼」，不是追更本身
    （追更的正确性在 `tests/test_update_report.py`）。

    ⚠️ 成品在书库根、留档在**收书目录**（`config.INPUT_DIR`）—— 与真实下载链路同一布局，
    理由见 `test_autoupdate.py::test_留档要在收书目录里找`。
    """
    default_root.mkdir(parents=True, exist_ok=True)
    inp = pathlib.Path(config.INPUT_DIR)
    inp.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        (default_root / f"书{i}.epub").write_bytes(b"PK")
        (inp / f"书{i}.meta.json").write_text(
            '{"source": "stub", "chapters": 1}', encoding="utf-8")
    library.invalidate()
    return default_root


@pytest.fixture
def calls(monkeypatch):
    """把唯一的外呼处换成记录器（返回一份「没有新章」的报告，与真报告同形）。"""
    got: list = []
    monkeypatch.setattr(
        autoupdate, "_run_one",
        lambda mgr, txt: (got.append(txt), {"added": 0, "note": "", "missing": 0})[1])
    return got


def test_闸门关时一次外呼都没有(books, calls, monkeypatch, tmp_path):  # noqa: ARG001
    """**本期的核心**：关掉下载 ⇒ 定时追更一本都不许跑。

    ⚠️ 默认配置（`download.enabled = False`）就是被拦的那一侧 —— 所以这里连
    `_set_download` 都不必调；显式写上只是为了让「这一轮是在什么开关下跑的」一眼可见。
    """
    _set_download(monkeypatch, tmp_path, enabled=False)

    rep = autoupdate.tick()

    assert calls == [], "闸门关着还去外呼书源 —— 假开关又回来了"
    assert rep["total"] == 3, "候选照数（报告要说清「有几本该看、为什么一本没看」）"
    assert rep["skipped"] == 3 and rep["ok"] == 0 and rep["errors"] == 0
    assert rep["added"] == 0
    # 原因必须是闸门那**唯一一处**判定的原文（措辞只有一份，界面与接口共用）
    assert "下载功能未开启" in rep["blocked"], rep
    assert "网络与下载" in rep["blocked"], f"要给出出口：{rep['blocked']}"


def test_闸门开时照常逐本跑(books, calls, monkeypatch, tmp_path):  # noqa: ARG001
    """放行的一侧也要钉：闸门不该拦错人；同时这是「cfg 漏传」那个漏子的回归位。

    原先 `tick` 里是无参 ``DownloadManager()`` ⇒ 构造抛 ``TypeError`` ⇒ 被 `except` 吞成
    「构造下载器失败（本轮跳过）」。所以本用例断言 `len(calls) == 3` 而不是只看 `rep["total"]`：
    **外呼真的发生了**才是这条路径活着的证据。
    """
    _set_download(monkeypatch, tmp_path, enabled=True)

    rep = autoupdate.tick()

    assert len(calls) == 3, "闸门开着却不跑 ⇒ 多半是 DownloadManager 又没传 cfg"
    assert rep["ok"] == 3 and rep["added"] == 0
    assert "blocked" not in rep, "放行的轮次不该带闸门原因"
    assert rep["skipped"] == 3, "没有新章算「跳过」，不算失败"


def test_被拦下与没有新章分得开(books, calls, monkeypatch, tmp_path):  # noqa: ARG001
    """两种「新增 0 章」必须在报告里长得不一样（界面据此说两句不同的话）。"""
    _set_download(monkeypatch, tmp_path, enabled=False)
    blocked = autoupdate.tick()

    _set_download(monkeypatch, tmp_path, enabled=True)
    ran = autoupdate.tick()

    assert blocked["added"] == ran["added"] == 0
    assert bool(blocked.get("blocked")) and not ran.get("blocked"), (blocked, ran)
    assert blocked["ok"] == 0 and ran["ok"] == 3


def test_手动追更在闸门关时进日志而不是记成功(client, auth_headers, books, calls,  # noqa: ARG001
                                              monkeypatch, tmp_path):
    """按了「立即追更」却什么都没跑 ⇒ 活动日志里要留一条**带原因**的账。

    第 93 期之前这里记的是 `STATUS_OK` +「检查 N 本：成功 0、新增 0 章、失败 0」——
    与「源上真的没有新章节」一字之差都没有，而用户按这个按钮唯一的疑问就是
    「为什么什么都没发生」。活动日志的状态词表只有「成功 / 失败」两档（见
    `AuditLogPage.vue` 的筛选器），所以如实记 `失败` 并把「未执行」+ 闸门原文写进 detail。
    """
    _set_download(monkeypatch, tmp_path, enabled=False)
    logged: list = []
    monkeypatch.setattr(autoupdate.activity_log, "log",
                        lambda *a, **kw: logged.append((a, kw)))

    r = client.post("/api/autoupdate/run", headers=auth_headers)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["blocked"] and body["total"] == 3 and body["ok"] == 0, body
    assert calls == [], "接口这条路也不许绕过闸门"
    rows = [kw for a, kw in logged if a and str(a[0]) == autoupdate.activity_log.ACTION_UPDATE]
    assert len(rows) == 1, logged
    assert "未执行" in rows[0]["detail"] and "下载功能未开启" in rows[0]["detail"], rows[0]
