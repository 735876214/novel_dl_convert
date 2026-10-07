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

#: 允许出现在 workflow 里的 `uses:`（**去重**后的 5 个）。
#: 每个都是 **node24** 运行时的大版本（2026-10-08 逐个抓上游 `action.yml` 的 `runs.using` 核过）：
#:   `actions/checkout`            v4 = node20 → **v5 起 node24**（本仓取最新 v7）
#:   `docker/build-push-action`    v6 = node20 → **v7 起 node24**
#:   `docker/setup-buildx-action`  v3 = node20 → **v4 起 node24**
#:   `docker/setup-qemu-action`    v3 = node20 → **v4 起 node24**
#:   `docker/login-action`         v3 = node20 → **v4 起 node24**
#: 升级时同批核过 `inputs:` 无更名 —— 本仓用到的那些一个都没动，所以是纯版本号替换。
ALLOWED = frozenset({
    "actions/checkout@v7",
    "docker/build-push-action@v7",
    "docker/login-action@v4",
    "docker/setup-buildx-action@v4",
    "docker/setup-qemu-action@v4",
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
