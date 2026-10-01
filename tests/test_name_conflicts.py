"""重名 / 副本判定（第 87 期第③步）。

用户口径（原话）：「当前书库对大量无意义重名书籍的识别逻辑存在问题，需改进去重或
重名判定机制，避免因相似命名导致**误判或冗余展示**」，并点名四件：
① 判据要从「只看文件名」升级为「文件名 + 目录 + 体积/页数/内容」综合；
② 主标题相同的**不同卷**不该被拉进同一组冲突；
③ 标点 / 破折号 / 全角半角 / 空格差异**该视为同一**；
④ ` (2)` 这类副本后缀**不该**算成不同书或冲突。

本文件钉住这四条的判据。零网络、零外呼。
"""
import pathlib

from novelforge.core import library


# ---------------- ① 基底键：该合的合 ----------------

def test_副本后缀_破折号_全角_空格差异都归到同一个键():
    """③④：这四种写法在用户眼里是**同一本书**，判据必须一致。"""
    base = library.conflict_key("三体 Vol.01.zip")
    for variant in ("三体 Vol.01 (2).zip", "三体 Vol.01（2）.zip",
                    "三体  Vol.01.zip",        # 多一个空格
                    "三体－Vol.01.zip",        # 全角连字符
                    "三体–Vol.01.zip",         # en dash
                    "三体—Vol.01.zip"):        # em dash
        assert library.conflict_key(variant) == base, f"{variant} 应当与基准同名"


def test_副本后缀只在主名上_扩展名仍参与判定():
    """`X (2).zip` 的 `(2)` 不在字符串末尾（后面还有 `.zip`）—— 摘扩展名再去后缀。

    而扩展名本身要留在键里：`X.zip` 与 `X.cbz` 是两种形态的文件，
    把它们当「同一本的副本」会误导用户去删掉另一种格式。
    """
    assert library.conflict_key("X (2).zip") == library.conflict_key("X.zip")
    assert library.conflict_key("X.zip") != library.conflict_key("X.cbz")
    assert library.conflict_key("X Vol.01 (2).zip") == library.conflict_key("X Vol.01.zip")


# ---------------- ② 不同卷不许合并 ----------------

def test_不同卷得到不同的键():
    """②：主标题相同的不同卷是**不同的书**，不许被当成同一本。"""
    assert library.conflict_key("X Vol.01.zip") != library.conflict_key("X Vol.02.zip")
    assert not library.is_copy_name("X Vol.01.zip", "X Vol.02.zip")
    assert library.volume_of("X Vol.01.zip") == "1"
    assert library.volume_of("X Vol.02.zip") == "2"


def test_卷号解析覆盖常见写法_解析不出就空():
    assert library.volume_of("第3卷.zip") == "3"
    assert library.volume_of("书名 第 12 册.epub") == "12"
    assert library.volume_of("X v2.cbz") == "2"
    assert library.volume_of("X Volume.07.pdf") == "7"
    assert library.volume_of("三体.epub") == "", "没写卷号就是空 —— 不猜位置"


# ---------------- 组级结论（说清「这是什么」）----------------

def test_同一物理文件被扫两遍判成重复扫描():
    kind, reason = library.conflict_kind(["sub/x.cbz", "x.cbz"],
                                        ["/lib/sub/x.cbz", "/lib/sub/x.cbz"], ["L1", "L1"])
    assert kind == "duplicate_scan"
    assert "同一个文件" in reason and "库配置" in reason, "要告诉用户该改的是库配置，不是改名"


def test_跨库同路径判成跨库冲突():
    kind, _ = library.conflict_kind(["x.cbz", "x.cbz"],
                                    ["/a/x.cbz", "/b/x.cbz"], ["L1", "L2"])
    assert kind == "cross_library"


def test_同库同名不同目录判成不同的书():
    kind, reason = library.conflict_kind(["科幻/Vol.01.cbz", "奇幻/Vol.01.cbz"],
                                         ["/lib/科幻/Vol.01.cbz", "/lib/奇幻/Vol.01.cbz"],
                                         ["L1", "L1"])
    assert kind == "same_name_different_dirs"
    assert "不同目录" in reason


# ---------------- 与书库接起来（真扫盘）----------------

def test_同名不同目录_建议名带目录而不是无意义的括号数字(isolated, default_root):  # noqa: ARG001
    default_root.mkdir(parents=True, exist_ok=True)
    (default_root / "科幻").mkdir(parents=True, exist_ok=True)
    (default_root / "奇幻").mkdir(parents=True, exist_ok=True)
    (default_root / "科幻" / "Vol.01.txt").write_text("甲", encoding="utf-8")
    (default_root / "奇幻" / "Vol.01.txt").write_text("乙", encoding="utf-8")
    library.invalidate()

    groups = [g for g in library.id_conflicts() if g["name"].endswith("Vol.01.txt")]
    assert len(groups) == 1, "同名（basename 逐字相同）会撞 id ⇒ 必须列出来"
    g = groups[0]
    assert g["kind"] == "same_name_different_dirs"
    assert g["reason"], "组级结论要能直接给用户看"
    # 保留项 = 扫描顺序的第一条（确定性：目录名按 Unicode 排序，"奇" < "科"）
    assert g["keep"] == "奇幻/Vol.01.txt"
    assert g["keep"] == g["items"][0]["name"]
    assert "科幻 - Vol.01.txt" in g["suggest"], \
        f"建议名要带目录名做区分，而不是 `Vol.01 (2).txt`：{g['suggest']}"


def test_同目录副本被单独列出来并给出该留哪份(isolated, default_root):  # noqa: ARG001
    """④：`X (2)` 这类副本**不会**进「同名冲突」（它们没撞 id），
    但要能被看见 —— 用户真正要决定的是「多出来的那份删不删」。"""
    default_root.mkdir(parents=True, exist_ok=True)
    (default_root / "X Vol.01.txt").write_text("完整的一本" * 10, encoding="utf-8")
    (default_root / "X Vol.01 (2).txt").write_text("半截", encoding="utf-8")
    library.invalidate()

    assert not [g for g in library.id_conflicts() if "Vol.01" in g["name"]], \
        "副本后缀的名字与原名逐字不同 ⇒ 没撞 id ⇒ 不该出现在同名冲突里"
    groups = library.copy_groups()
    assert len(groups) == 1 and groups[0]["count"] == 2
    assert groups[0]["keep"] == "X Vol.01.txt", "保留体积更大的那一份（副本常是被截断的）"
    names = {i["name"] for i in groups[0]["items"]}
    assert names == {"X Vol.01.txt", "X Vol.01 (2).txt"}


def test_不同卷不会被当成副本(isolated, default_root):  # noqa: ARG001
    """②的落地断言：`Vol.01` 与 `Vol.02` **不是**副本，不许出现在同一组。"""
    default_root.mkdir(parents=True, exist_ok=True)
    (default_root / "X Vol.01.txt").write_text("一", encoding="utf-8")
    (default_root / "X Vol.02.txt").write_text("二", encoding="utf-8")
    library.invalidate()
    assert library.copy_groups() == [], "不同卷是两本不同的书"


def test_逐字同名的归同名冲突而不是副本表(isolated, default_root):  # noqa: ARG001
    """两张表**不重复报同一件事**：basename 逐字相同 ⇒ 走「同名冲突」（撞了 id，必须改名）。"""
    default_root.mkdir(parents=True, exist_ok=True)
    (default_root / "甲").mkdir(parents=True, exist_ok=True)
    (default_root / "乙").mkdir(parents=True, exist_ok=True)
    (default_root / "甲" / "同名.txt").write_text("a", encoding="utf-8")
    (default_root / "乙" / "同名.txt").write_text("b", encoding="utf-8")
    library.invalidate()
    assert [g for g in library.id_conflicts() if g["name"].endswith("同名.txt")]
    assert library.copy_groups() == []


def test_建议名撞了就回落括号数字(isolated, default_root, tmp_path):  # noqa: ARG001
    """带目录名的候选若已被占用，仍要给出一个**可用**的候选（不许返回一个撞车的名）。"""
    default_root.mkdir(parents=True, exist_ok=True)
    (default_root / "科幻").mkdir(parents=True, exist_ok=True)
    (default_root / "科幻" / "Vol.01.txt").write_text("x", encoding="utf-8")
    (default_root / "科幻" / "科幻 - Vol.01.txt").write_text("占位", encoding="utf-8")
    library.invalidate()
    got = library.suggest_name("科幻/Vol.01.txt", root=default_root, use_dir=True)
    assert got != "科幻/科幻 - Vol.01.txt", "候选已被占用就不能再建议它"
    assert pathlib.PurePosixPath(got).parent == pathlib.PurePosixPath("科幻"), \
        "建议名必须留在同一个目录里（改名不该顺手搬家）"


def test_副本清单接口存在且形状稳定(client, auth_headers):
    """新增接口要有契约（AGENTS.md：加功能要彻底，含路由与形状断言）。"""
    r = client.get("/api/library-copies", headers=auth_headers)
    assert r.status_code == 200, "接口必须存在（404 说明路由没接上）"
    body = r.json()
    assert set(body) == {"items", "total", "libraries"}
    assert isinstance(body["items"], list) and body["total"] == len(body["items"])
