# -*- coding: utf-8 -*-
"""第 149 期：部署面（固定镜像 tag / 非 root 配方）与三处能力口径的契约。

这一期修的都是「文档与代码各说一套」和「判据散在两处」的形态：

* 镜像 tag 的真值源散成了三份（`config.DEFAULTS["update"]["image"]` 钉 `:latest`、
  `updater._DEFAULT_IMAGE` 钉 `:latest`、`docker-compose.yml` 本该是部署方说了算）；
* 「是不是压缩包」散成 `zipkind.is_container` 与 `comics.is_comic` 两个判据，
  于是 `.cbr` 在「按内容分派」那条路上两边都漏；
* 「待展开清单」每次请求都为每个候选重开一次归档。

判据尽量钉在**能被下一期复验的形态**上：compose 的 tag 必须等于仓库根 `VERSION`，
非 root 配方的三段（镜像内置 uid 1000 / compose 注释 / start.sh 自检）必须同时在场。
"""
import pathlib
import re

import pytest

from novelforge.core import library_rules, updater, zipkind

REPO = pathlib.Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- 部署面


def test_compose_镜像tag钉死且等于仓库版本():
    """`docker-compose.yml` 的 tag 必须是**确切版本号**并且 == 仓库根 `VERSION`。

    钉 `:latest` 时「我现在跑的是哪个版本」在部署侧无法回答，且本机多部署并行时
    `docker compose up -d` 会把人悄悄带到别人的版本上；tag 与 `VERSION` 脱钩则会
    出现「镜像写着 1.5.0、compose 说 1.4.0」的第二种真值源。
    """
    version = (REPO / "VERSION").read_text(encoding="utf-8").strip()
    text = (REPO / "docker-compose.yml").read_text(encoding="utf-8")
    images = re.findall(r"(?m)^\s*image:\s*(\S+)\s*$", text)
    assert images, "compose 里找不到 image: 行"
    app = [i for i in images if "novel_dl_convert" in i]
    assert len(app) == 1, images
    tag = app[0].rsplit(":", 1)[-1]
    assert tag != "latest", f"镜像 tag 仍钉着 :latest —— {app[0]}"
    assert re.fullmatch(r"\d+\.\d+\.\d+", tag), f"tag 不是确切版本号：{app[0]}"
    assert tag == version, f"compose tag={tag} 与 VERSION={version} 不一致"


def test_非root配方三段同时在场():
    """非 root 运行的三段配方必须齐全：镜像里建账号、compose 给用法、start.sh 自检。

    缺 start.sh 那段的结果是实测过的：容器起得来、写配置时才炸，用户只看到
    PermissionError 堆栈，还得自己去猜是哪个目录、该 chown 成什么。
    """
    dockerfile = (REPO / "Dockerfile").read_text(encoding="utf-8")
    compose = (REPO / "docker-compose.yml").read_text(encoding="utf-8")
    start = (REPO / "start.sh").read_text(encoding="utf-8")

    assert "useradd -u 1000" in dockerfile, "镜像没有内置 uid 1000 的账号"
    assert "chown 1000:1000" in dockerfile, "镜像没有把挂载点交给该账号"
    assert 'user: "1000:1000"' in compose, "compose 没给非 root 的用法"
    assert "chown -R" in compose, "compose 没写宿主机目录该 chown 成什么"
    assert ".novelforge-write-check" in start, "start.sh 缺挂载目录可写性自检"
    assert "id -u" in start, "start.sh 自检没判当前 uid"


def test_start_sh_仍是_lf_行尾():
    """`.sh` 必须是 LF（CRLF 会让容器里 `sh /app/start.sh` 报 `set: Illegal option -`）。"""
    raw = (REPO / "start.sh").read_bytes()
    assert b"\r\n" not in raw, "start.sh 出现了 CRLF 行尾"


# ---------------------------------------------------------------- 镜像选择


def test_更新目标换成最新release的确切版本(monkeypatch):
    """官方仓库 + 已知最新 release ⇒ 拉的是那个**确切版本号**，不是 `:latest`。"""
    monkeypatch.setattr(updater, "configured_image",
                        lambda explicit="": "ghcr.io/735876214/novel_dl_convert:1.4.0")
    monkeypatch.setattr(updater, "_state", {"latest": "1.5.2"})
    image, repo, tag = updater._update_target()
    assert (repo, tag) == ("ghcr.io/735876214/novel_dl_convert", "1.5.2")
    assert image == "ghcr.io/735876214/novel_dl_convert:1.5.2"


def test_更新目标查不到版本时原样拉(monkeypatch):
    """离线 / 限流时退回部署文件里那个 tag（行为与改造前一致，不猜）。"""
    monkeypatch.setattr(updater, "configured_image",
                        lambda explicit="": "ghcr.io/735876214/novel_dl_convert:1.4.0")
    monkeypatch.setattr(updater, "_state", {})
    monkeypatch.setattr(updater, "_remote_latest", lambda: (None, ""))
    assert updater._update_target()[2] == "1.4.0"


def test_更新目标不改写私有仓库的tag(monkeypatch):
    """私有仓库 / 加速镜像的 tag 是部署方自己的语义，不能被最新版本号顶掉。"""
    monkeypatch.setattr(updater, "configured_image",
                        lambda explicit="": "localhost:5000/ns/img:2")
    monkeypatch.setattr(updater, "_state", {"latest": "9.9.9"})
    image, repo, tag = updater._update_target()
    assert (repo, tag) == ("localhost:5000/ns/img", "2")
    assert image == "localhost:5000/ns/img:2"


def test_镜像回落顺序_配置_环境_部署文件_内置默认(monkeypatch):
    """`configured_image` 的四层顺序——第 149 期把「部署文件里的镜像」插在环境变量之后。"""
    monkeypatch.setattr(updater, "_update_cfg", lambda: {})
    monkeypatch.delenv("NOVELFORGE_UPDATE_IMAGE", raising=False)
    monkeypatch.setattr(updater, "_self_image", lambda: "ghcr.io/735876214/novel_dl_convert:1.4.0")
    assert updater.configured_image() == "ghcr.io/735876214/novel_dl_convert:1.4.0"

    monkeypatch.setenv("NOVELFORGE_UPDATE_IMAGE", "env/from-env:1")
    assert updater.configured_image() == "env/from-env:1"

    monkeypatch.setattr(updater, "_update_cfg", lambda: {"image": "cfg/img:2"})
    assert updater.configured_image() == "cfg/img:2"

    assert updater.configured_image("explicit/img:3") == "explicit/img:3"

    monkeypatch.setattr(updater, "_self_image", lambda: "")
    monkeypatch.setattr(updater, "_update_cfg", lambda: {})
    monkeypatch.delenv("NOVELFORGE_UPDATE_IMAGE", raising=False)
    assert updater.configured_image() == updater._DEFAULT_IMAGE


def test_拿不到自身镜像时安静回落(monkeypatch):
    """没有 docker.sock / 读不到容器 ⇒ `_self_image()` 回空串，绝不抛。"""
    monkeypatch.setattr(updater, "updater_available", lambda: False)
    monkeypatch.setattr(updater, "_self_image_cache", {"at": 0.0, "image": ""})
    assert updater._self_image() == ""


# ---------------------------------------------------------------- 压缩包判据


@pytest.mark.parametrize(
    ("name", "want"),
    [
        ("a.zip", True), ("a.rar", True), ("a.7z", True),
        ("a.cbz", True), ("a.cbr", True),          # ← 第 149 期补上的两个
        ("a.epub", False), ("a.txt", False), ("a", False),
    ],
)
def test_is_archive_覆盖漫画归档(name, want):
    """「要不要打开看看里面是什么」= 通用容器 **或** 漫画归档（单一判据）。"""
    assert zipkind.is_archive(name) is want


def test_cbr不再被短路_识别结果一定说出来(monkeypatch):
    """`.cbr` 的识别结果必须被说出来（此前 `is_container` 只认 `.zip/.rar/.7z` ⇒ 直接空串）。

    第 149 期：这条判据钉在**分流**上，不依赖真实归档解析 —— 造一个假 RAR 头当夹具，
    本机没 bsdtar 时 `analyze` 判 `broken`、CI 有 bsdtar 时判 `empty`（第 149 期
    CI 就这么红过一次）。那是环境的结论，不是这条分流的结论。
    """
    monkeypatch.setattr(zipkind, "analyze",
                        lambda p: {"kind": "comic", "evidence": {"images": 12}})
    hint = library_rules._container_shape_hint([], "缺工具.cbr", "缺工具.cbr")
    assert hint and "漫画" in hint, hint

    monkeypatch.setattr(
        zipkind, "analyze",
        lambda p: {"kind": "broken", "reason": "服务器缺少 RAR 解压能力（需 bsdtar 或 unrar）"},
    )
    hint = library_rules._container_shape_hint([], "缺工具.cbr", "缺工具.cbr")
    assert hint and "RAR" in hint and "解压能力" in hint, hint


# ---------------------------------------------------------------- 待展开记忆


def test_待展开清单结果被记忆且不污染缓存(tmp_path, monkeypatch):
    """同一份容器第二次不再重开归档；调用方拿到的副本随便改也不影响缓存。"""
    src = tmp_path / "书.zip"
    src.write_bytes(b"PK\x03\x04" + b"\x00" * 64)

    calls = {"n": 0}
    real = zipkind.analyze

    def spy(p):
        calls["n"] += 1
        return real(p)

    monkeypatch.setattr(zipkind, "analyze", spy)
    zipkind.clear_plan_cache()

    first = zipkind.unpack_plan(src)
    again = zipkind.unpack_plan(src)
    assert calls["n"] == 1, f"第二次仍重开了归档（analyze 调了 {calls['n']} 次）"
    assert again["ok"] == first["ok"]

    again.setdefault("actions", []).append({"kind": "bogus"})
    third = zipkind.unpack_plan(src)
    assert all(a.get("kind") != "bogus" for a in third["actions"]), "缓存被调用方就地改掉了"


def test_待展开清单指纹变了就重算(tmp_path, monkeypatch):
    """容器的 (大小, mtime_ns) 一变就重算——与扫描期同一把尺子，不另造失效点。"""
    src = tmp_path / "书.zip"
    src.write_bytes(b"PK\x03\x04" + b"\x00" * 64)

    calls = {"n": 0}
    real = zipkind.analyze

    def spy(p):
        calls["n"] += 1
        return real(p)

    monkeypatch.setattr(zipkind, "analyze", spy)
    zipkind.clear_plan_cache()

    zipkind.unpack_plan(src)
    assert calls["n"] == 1
    src.write_bytes(b"PK\x03\x04" + b"\x00" * 128)      # 大小 + mtime 都变
    zipkind.unpack_plan(src)
    assert calls["n"] == 2
