"""并发访问契约（第 39 期）：共享连接的**读路径也必须持锁**。

来历（第 39 期 T5 实测查明的根因，不是推测）：

本模块全进程共享一个 sqlite3 连接（``check_same_thread=False``）。CPython 的
``sqlite3`` **不保证**同一连接可被多线程并发使用 —— 原先只有**写路径**持
``_lock``、读路径裸调 ``_connect().execute(...)``，于是两个线程同时进这个连接时抛
``InterfaceError: bad parameter or other API misuse``（底层 SQLITE_MISUSE），
急起来还能把解释器**打成段错误**。

后果不是「报个错」那么轻：``library.get_library`` 把这个异常吞成 ``None`` ⇒
``lib_settings.overrides()`` 得空 dict ⇒ **每库覆写静默回落全局值**。
``tests/test_scrape_publish.py`` 里「扫描后按开关自动入队」那例的偶发失败
（用户关掉某库的自动刮削，读回来又是开的）就是它。

修法是让 ``_connect()`` 返回一个**按语句持锁**的代理（``db._Conn``），169 处
调用点一行不改 —— 比逐处手改更不容易漏。本文件钉住三件事：代理还在、锁仍是
重入锁、真并发下既不抛异常也不丢覆写。

⚠️ 本文件是仓库里**唯一**主动开线程的测试（纪律是「测试不养后台轮询」）——
所以线程一律在用例内 ``join`` 并断言已退出，绝不留给下一个用例。
"""
import json
import sqlite3
import threading
import time

from novelforge import config
from novelforge.core import db, lib_settings

#: 本文件自建的库（不蹭 `isolated` 那条，免得与别的断言互相干扰）。
CONC_LIB = "conc-lib"

#: 并发窗口时长（秒）。原实现下放大探针 5 秒复现两千余次，这里取小值就够
#: —— 本用例要的是「**不能**再发生」，不是「一定会发生」。
WINDOW = 1.2


def _hammer(fn, stop, errs):
    """把 ``fn`` 循环跑到 ``stop`` 置位；捕获的异常收进 ``errs``。

    子线程里**不断言**：断言只在主线程做，否则失败信息会散在 traceback 之外。
    """
    def run():
        while not stop.is_set():
            try:
                fn()
            except Exception as e:                    # noqa: BLE001 —— 交给主线程断言
                errs.append(f"{type(e).__name__}: {e}")
                return

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def test_读路径拿到的是持锁代理而非裸连接(isolated):  # noqa: ARG001
    """``_connect()`` 不能再把裸连接交出去 —— 那等于把锁关在门外。"""
    c = db._connect()
    assert not isinstance(c, sqlite3.Connection), \
        "读路径又直接暴露裸 sqlite3 连接了 ⇒ 回到「读写不同锁」的竞态"
    # 代理至少要覆盖全仓用到的这个面（db.py 里的用法盘点见第 39 期记录）
    for name in ("execute", "executemany", "executescript", "commit", "rollback"):
        assert callable(getattr(c, name, None)), f"连接代理缺 {name}"


def test_语句结果在锁内就已物化(isolated):  # noqa: ARG001
    """代理不得把「还没取完的语句」留到锁外，否则竞态照旧。"""
    cur = db._connect().execute("SELECT 1 AS n")
    assert not isinstance(cur, sqlite3.Cursor), \
        "execute 又返回裸游标 ⇒ 语句可能被留到锁外取"
    assert cur.fetchone()["n"] == 1
    assert cur.fetchone() is None, "取完必须返回 None（照 sqlite3.Cursor 口径）"


def test_锁是重入锁(isolated):  # noqa: ARG001
    """``with _lock:`` 块里还会再调 ``c.execute`` —— 非重入锁会把自己锁死。"""
    assert isinstance(db._lock, type(threading.RLock())), \
        "必须是 RLock：代理会对同一线程重入取锁"
    assert db._lock.acquire(blocking=False)
    assert db._lock.acquire(blocking=False), "重入失败：会与既有 with _lock 块死锁"
    db._lock.release()
    db._lock.release()


def test_并发读写下不抛异常且每库覆写不丢(isolated):  # noqa: ARG001
    """真并发：三个线程反复读该库生效设置，一个线程反复写它。

    原实现下这里必红 —— `InterfaceError` 满屏，且覆写被读成全局的 True。
    """
    db.create_library(CONC_LIB, "并发库", "ebook", "inplace",
                      str(config.OUTPUT_DIR),
                      settings=json.dumps({"scrape.enabled": False}))

    pre = lib_settings.effective(CONC_LIB)
    assert pre["global"]["scrape.enabled"] is True, \
        "前置不成立：全局默认须为「开」，否则观测不到覆写丢失"
    assert pre["values"]["scrape.enabled"] is False, \
        "前置不成立：单线程下就该看到覆写值"

    errs: list = []
    lost: list = []
    stop = threading.Event()

    def read():
        # 用户看到的那条路
        v = lib_settings.effective(CONC_LIB)["values"]["scrape.enabled"]
        if v is not False:
            lost.append(f"覆写丢了，读成 {v!r}")

    def write():
        db.update_library(CONC_LIB,
                          settings=json.dumps({"scrape.enabled": False}))

    threads = [_hammer(read, stop, errs) for _ in range(3)]
    threads.append(_hammer(write, stop, errs))
    time.sleep(WINDOW)
    stop.set()
    for t in threads:
        t.join(5.0)
        assert not t.is_alive(), "压测线程没收干净 —— 本文件不得留线程给下一个用例"

    assert errs == [], f"并发下仍抛异常：{errs[:3]}"
    assert lost == [], f"每库覆写被静默丢弃：{lost[:3]}"
