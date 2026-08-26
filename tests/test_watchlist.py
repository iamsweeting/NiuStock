# -*- coding: utf-8 -*-
"""查询名单（自选）持久化单元测试。

规则：count 累计；前三名门槛保护（进第1名 +30、进第2/3名 +50，每次最多升一位）；
第4名以后纯按 count 降序。
"""
import json

from app import config, watchlist


def _wl(tmp_path):
    return watchlist.Watchlist(path=str(tmp_path / "watchlist.json"))


def _codes(wl):
    return [it["code"] for it in wl.items()]


def test_default_items_when_missing(tmp_path):
    wl = _wl(tmp_path)
    assert _codes(wl) == ["sz159516", "sh688008", "sh513310"]


def test_touch_counts_and_keeps_default_order(tmp_path):
    wl = _wl(tmp_path)
    wl.touch("sh600519", "贵州茅台")
    wl.touch("sh600519", "贵州茅台")
    # 新代码排最后；默认前三不受两次查询影响（阈值 30/50）
    assert _codes(wl) == ["sz159516", "sh688008", "sh513310", "sh600519"]
    it = [i for i in wl.items() if i["code"] == "sh600519"][0]
    assert it["count"] == 2


def test_promote_second_to_first_needs_30(tmp_path):
    wl = _wl(tmp_path)
    # 第二名 688008 查询 29 次：仍不能超过第一名 159516（需 +30）
    for _ in range(29):
        wl.touch("sh688008", "澜起科技")
    assert _codes(wl)[0] == "sz159516"
    # 第 30 次：与第一名差 30 → 超过 → 上升为第一名
    wl.touch("sh688008", "澜起科技")
    assert _codes(wl)[0] == "sh688008"


def test_promote_third_to_second_needs_50(tmp_path):
    wl = _wl(tmp_path)
    # 给第一名 159516 一些计数（30 以内），保证第三名升到第二名后不再连升第一名
    for _ in range(25):
        wl.touch("sz159516", "半导体设备ETF")
    # 第三名 513310 查询 49 次：仍不能超过第二名 688008（需 +50）
    for _ in range(49):
        wl.touch("sh513310", "中韩半导体ETF")
    assert _codes(wl)[1] == "sh688008"
    assert _codes(wl)[2] == "sh513310"
    # 第 50 次：与第二名差 50 → 超过 → 上升一位到第二名
    wl.touch("sh513310", "中韩半导体ETF")
    assert _codes(wl)[1] == "sh513310"
    # 但仍未超过第一名（差 50-25=25 < 30），第一名不变
    assert _codes(wl)[0] == "sz159516"


def test_no_cascade_single_step_per_touch(tmp_path):
    # 级联关闭：一次触摸最多升一位。513310 满 50 次后升到第二，
    # 但要在下一次触摸才可能继续升第一（即使它早已超过第一 +30）。
    wl = _wl(tmp_path)
    for _ in range(50):
        wl.touch("sh513310", "中韩半导体ETF")
    # 50 次触摸后：513310 从第三升到第二（超过 688008 50 次），
    # 但同一次触摸不会继续升第一（无级联）→ 第一名仍是 159516
    assert _codes(wl)[0] == "sz159516"
    assert _codes(wl)[1] == "sh513310"
    # 下一次触摸：513310（51）超过第一（0）30 次 → 升第一
    wl.touch("sh513310", "中韩半导体ETF")
    assert _codes(wl)[0] == "sh513310"


def test_tail_sorted_pure_count(tmp_path):
    # 第4名以后：纯按 count 降序（不设门槛）
    wl = _wl(tmp_path)
    wl.touch("sh600519", "贵州茅台")     # count 1
    wl.touch("sz000001", "平安银行")     # count 1
    wl.touch("sz300750", "宁德时代")     # count 1
    wl.touch("sh600519", "贵州茅台")     # count 2 → 尾部第一
    codes = _codes(wl)
    assert codes[:3] == ["sz159516", "sh688008", "sh513310"]
    assert codes[3] == "sh600519"        # count 2 在 count 1 之前
    assert set(codes[4:]) == {"sz000001", "sz300750"}


def test_rank_persists(tmp_path):
    wl = _wl(tmp_path)
    for _ in range(31):
        wl.touch("sh688008", "澜起科技")
    wl2 = watchlist.Watchlist(path=str(tmp_path / "watchlist.json"))
    assert _codes(wl2)[0] == "sh688008"


def test_old_format_no_count_migrates(tmp_path):
    p = tmp_path / "watchlist.json"
    p.write_text(json.dumps([
        {"code": "sh600519", "name": "贵州茅台"},
        {"code": "sz159516", "name": "半导体设备ETF"},
    ], ensure_ascii=False), encoding="utf-8")
    wl = watchlist.Watchlist(path=str(p))
    items = wl.items()
    assert all("count" in it for it in items)
    # 旧格式迁移：默认前三置顶，其余保留
    assert [it["code"] for it in items[:3]] == ["sz159516", "sh688008", "sh513310"]
    assert "sh600519" in [it["code"] for it in items]


def test_remove_and_clear(tmp_path):
    wl = _wl(tmp_path)
    wl.touch("sh600519", "贵州茅台")
    wl.remove("sh600519")
    assert "sh600519" not in _codes(wl)
    wl.touch("sz000001", "平安银行")
    wl.clear()
    assert _codes(wl) == ["sz159516", "sh688008", "sh513310"]


def test_limit_cap(tmp_path):
    wl = _wl(tmp_path)
    for i in range(config.WATCHLIST_LIMIT + 10):
        wl.touch("sh6%05d" % i, "测试%d" % i)
    assert len(wl.items()) == config.WATCHLIST_LIMIT


def test_top_fills_from_defaults(tmp_path):
    wl = _wl(tmp_path)
    wl.clear()
    top = wl.top(3)
    assert [it["code"] for it in top] == ["sz159516", "sh688008", "sh513310"]


def test_corrupt_file_falls_back(tmp_path):
    p = tmp_path / "watchlist.json"
    p.write_text("{not json", encoding="utf-8")
    wl = watchlist.Watchlist(path=str(p))
    assert _codes(wl) == ["sz159516", "sh688008", "sh513310"]
