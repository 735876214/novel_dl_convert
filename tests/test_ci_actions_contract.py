"""CI action 运行时契约（第 114 期）：workflow 里的每个 `uses:` 都必须落在**已登记的大版本**上。

起因是 `Build and Push Image` 从第 105 期起每次都给的一条 warning：

    Node.js 20 is deprecated. The following actions target Node.js 20 but are being forced to
    run on Node.js 24: actions/checkout@v4, docker/build-push-action@v6, docker/login-action@v3,
    docker/setup-buildx-action@v3, docker/setup-qemu-action@v3

第 105 期只修了当时那次构建失败的**真因**（`.gitignore` 把源码吞了），**刻意没顺手升版本**
（`docs/TODO.md` 里写着「独立一件事，别顺手改」）⇒ 这条挂了两期，第 114 期才把这 5 个一起升上去。

**为什么白名单是手写的、不去联网读上游 `action.yml`**：全量 pytest 是**离线**的（`AGENTS.md` §4）。
代价是白名单会随上游发新版而「过期」—— 这正是它的**用途**：换/加 action、或谁把它改回旧大版本时
全量直接红，逼一次有意识的改动，而不是像第 105–113 期那样把这条 warning 放着不管。
"""
import pathlib
import re

WORKFLOWS = pathlib.Path(__file__).resolve().parents[1] / ".github" / "workflows"

#: 允许出现在 workflow 里的 `uses:`（**去重**后的 6 个）。
#: 每个都是 **node24** 运行时的大版本（2026-10-08 逐个抓上游 `action.yml` 的 `runs.using` 核过）：
#:   `actions/checkout`            v4 = node20 → **v5 起 node24**（本仓取最新 v7）
#:   `docker/build-push-action`    v6 = node20 → **v7 起 node24**
#:   `docker/setup-buildx-action`  v3 = node20 → **v4 起 node24**
#:   `docker/setup-qemu-action`    v3 = node20 → **v4 起 node24**
#:   `docker/login-action`         v3 = node20 → **v4 起 node24**
#:   `actions/setup-python`        **v6 = node24**（第 118 期新增：`.github/workflows/tests.yml`
#:                                用它装 3.12 跑后端全量；2026-10-19 抓 `v6/action.yml` 核过 `runs.using: node24`）
#: 升级时同批核过 `inputs:` 无更名 —— 本仓用到的那些一个都没动，所以是纯版本号替换。
ALLOWED = frozenset({
    "actions/checkout@v7",
    "docker/build-push-action@v7",
    "docker/login-action@v4",
    "docker/setup-buildx-action@v4",
    "docker/setup-qemu-action@v4",
    "actions/setup-python@v6",
})

#: `uses:` 行（带不带 `- ` 前缀都要认）；`[^\s#]+` 顺带把行尾注释切掉。
_USES_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)", re.M)


def _used() -> set[str]:
    """扫 `.github/workflows/` 下所有 `uses:` 的 `owner/repo@ref`，**去重**返回。

    本地复合 action（`./…`）与容器 action（`docker://…`）不在射程内 —— 它们没有 node 运行时，
    钉在这里只会逼出例外规则。
    """
    found: set[str] = set()
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        for spec in _USES_RE.findall(path.read_text(encoding="utf-8")):
            if spec.startswith(("./", "docker://")):
                continue
            found.add(spec)
    return found


def test_workflow_里的_action都在已登记的大版本上():
    """用到的必须在白名单里 —— 升/换 action 时**有意**改一次 `ALLOWED`，而不是悄悄飘。"""
    used = _used()
    assert used, "一个 `uses:` 都没扫到？扫描逻辑大概坏了（这条**必须**报错，不能静默通过）"

    unknown = sorted(used - ALLOWED)
    assert not unknown, (
        "这些 action 没登记在这条契约的白名单里：\n  " + "\n  ".join(unknown)
        + "\n⇒ 若是有意新增/升级：改 `ALLOWED` 之前先核它的 `runs.using`"
          "（`https://raw.githubusercontent.com/<owner>/<repo>/<tag>/action.yml`）"
          "是 **node24**，并同批核 `inputs:` 有没有更名；若只是被改回了旧大版本，改回来。"
    )


def test_白名单与实际用到的一一对应():
    """反向也要钉：白名单里不许有**用不上**的条目。

    否则删掉某个 step（或某个 workflow）之后，那一条会静静烂在 `ALLOWED` 里 ——
    下次真要用它时，白名单已经给不出任何保证。
    """
    stale = sorted(ALLOWED - _used())
    assert not stale, (
        "这些条目在 `ALLOWED` 里，但 workflow 里已经没有任何一步用它了：\n  "
        + "\n  ".join(stale)
        + "\n⇒ 要么把对应的 step 加回来，要么从 `ALLOWED` 里删掉。"
    )


# ---------------------------------------------------------------- 第 145 期：噪音与基础设施抖动

def _workflow_texts() -> dict:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(WORKFLOWS.glob("*.y*ml"))}


def test_每个_workflow_都声明了_concurrency():
    """同一个 ref 的并发 run 必须互相取消/排队。

    2026-09/10 那批红叉里两类都不是代码问题、而是**并发**造成的噪音：
    ① 两次构建同时往同一份 GHA 层缓存里写 ⇒ `ERROR: error writing layer blob: not_found`；
    ② 连推两笔时旧 run 被新 run 挤成 `cancelled`（页面上一样是个灰叉）。

    钉住「每个 workflow 都得有 `concurrency:`」，新增 workflow 时才会被迫想一次这件事。
    """
    texts = _workflow_texts()
    assert texts, "一个 workflow 都没扫到？扫描逻辑大概坏了"
    missing = sorted(name for name, text in texts.items()
                     if not re.search(r"^concurrency:\s*$", text, re.M))
    assert not missing, (
        "这些 workflow 没声明 `concurrency:`（并发 run 会互相挤缓存 / 互相取消）：\n  "
        + "\n  ".join(missing)
        + "\n⇒ 补一段：\n"
          "  concurrency:\n    group: <名字>-${{ github.ref }}\n    cancel-in-progress: true"
    )


def test_镜像构建的缓存导出失败不许判死构建():
    """`cache-to` 必须带 `ignore-error=true`。

    缓存是**加速手段**，不是交付物：GHA 缓存配额满 / 竞态 / 网络抖动都会让**导出层缓存**失败，
    而历史上（2026-09-17 起多笔）这类失败会让整个「Build and Push Image」变红 ——
    镜像其实已经推上去了，人却收到失败通知，只能手动重跑。
    """
    text = _workflow_texts()["docker-image.yml"]
    cache_to = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("cache-to:")]
    assert cache_to, "docker-image.yml 里找不到 `cache-to:`（构建缓存被整个删了？）"
    assert all("ignore-error=true" in ln for ln in cache_to), (
        "`cache-to` 没带 `ignore-error=true` ⇒ 导出缓存失败会把构建判红：\n  "
        + "\n  ".join(cache_to)
    )
