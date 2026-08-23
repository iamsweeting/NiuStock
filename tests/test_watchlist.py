# -*- coding: utf-8 -*-
"""查询名单（自选）持久化单元测试。"""
import json

from app import config, watchlist


def _wl(tmp_path):
    return watchlist.Watchlist(path=str(tmp_path / "watchlist.json"))


def test_default_items_when_missing(tmp_path):
    wl = _wl(tmp_path)
    items = wl.items()
    assert [it["code"] for it in items] == ["sz159516", "sh513310", "sz159845"]


def test_touch_recent_first_dedup(tmp_path):
    wl = _wl(tmp_path)
    wl.touch("sh600519", "贵州茅台")
    wl.touch("sz159516", "半导体设备ETF")
    items = wl.items()
    assert items[0]["code"] == "sz159516"       # 最新在前
    assert items[1]["code"] == "sh600519"
    assert len(items) == 4                       # 默认3 + 新增1


def test_touch_persists(tmp_path):
    wl = _wl(tmp_path)
    wl.touch("sh600519", "贵州茅台")
    wl2 = watchlist.Watchlist(path=str(tmp_path / "watchlist.json"))
    assert wl2.items()[0]["code"] == "sh600519"


def test_remove_and_clear(tmp_path):
    wl = _wl(tmp_path)
    wl.touch("sh600519", "贵州茅台")
    wl.remove("sh600519")
    assert "sh600519" not in [it["code"] for it in wl.items()]
    wl.touch("sz000001", "平安银行")
    wl.clear()
    assert [it["code"] for it in wl.items()] == ["sz159516", "sh513310", "sz159845"]


def test_limit_cap(tmp_path):
    wl = _wl(tmp_path)
    for i in range(config.WATCHLIST_LIMIT + 10):
        wl.touch("sh6%05d" % i, "测试%d" % i)
    assert len(wl.items()) == config.WATCHLIST_LIMIT


def test_top_fills_from_defaults(tmp_path):
    wl = _wl(tmp_path)
    wl.clear()
    # 清空后 top(3) 仍回退到默认名单
    top = wl.top(3)
    assert [it["code"] for it in top] == ["sz159516", "sh513310", "sz159845"]


def test_corrupt_file_falls_back(tmp_path):
    p = tmp_path / "watchlist.json"
    p.write_text("{not json", encoding="utf-8")
    wl = watchlist.Watchlist(path=str(p))
    assert [it["code"] for it in wl.items()] == ["sz159516", "sh513310", "sz159845"]
