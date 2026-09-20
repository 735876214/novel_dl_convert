"""成就体系对齐上游（第 31 期）：分组键与条目钉死。

上游 `packages/types/src/achievement.ts` 定义 5 分类，本项目对齐前 4 个
（library / reading / exploration / dedication）；`devices` 因缺 reading_sessions.source
刻意不做。本测试保证「分组只在这 4 个之内」「dedication 新成就存在」「key 唯一」
「evaluate 返回的 group 也对齐」。
"""
from novelforge.core import achievements

ALLOWED = {"library", "reading", "exploration", "dedication"}


def test_achievement_groups_aligned_to_upstream():
    groups = {a["group"] for a in achievements.ACHIEVEMENTS}
    assert groups <= ALLOWED, f"出现未对齐分组：{groups - ALLOWED}"
    assert "devices" not in groups, "devices 分类刻意不做（缺 source 列）"


def test_dedication_achievements_present():
    keys = {a["key"] for a in achievements.ACHIEVEMENTS}
    for k in ("streak_100", "hours_500", "active_days_100", "finished_50"):
        assert k in keys, f"缺少 dedication 成就 {k}"


def test_achievement_keys_unique():
    keys = [a["key"] for a in achievements.ACHIEVEMENTS]
    assert len(keys) == len(set(keys)), "成就 key 必须唯一（前端/统计可能引用）"


def test_evaluate_groups_aligned(client, auth_headers):
    # auto_unlock=False：契约测试只看分组，不借机写解锁记录（保持用例无副作用）
    res = achievements.evaluate(auto_unlock=False)
    groups = {it["group"] for it in res["items"]}
    assert groups <= ALLOWED
