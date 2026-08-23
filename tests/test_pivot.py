# -*- coding: utf-8 -*-
"""枢轴点纯逻辑单元测试（代码解析 / 五种算法 / 批量解析 / 验证标色）。"""
import pytest

from app import config, pivot


# --------------------------------------------------------------------------
# 代码解析
# --------------------------------------------------------------------------

def test_parse_stock_code_a_share():
    assert pivot.parse_stock_code("600519") == ("600519", "sh", False)
    assert pivot.parse_stock_code("159516") == ("159516", "sz", False)
    assert pivot.parse_stock_code("000001") == ("000001", "sz", False)
    assert pivot.parse_stock_code("300750") == ("300750", "sz", False)
    assert pivot.parse_stock_code("688981") == ("688981", "sh", False)
    assert pivot.parse_stock_code("430047") == ("430047", "bj", False)


def test_parse_stock_code_prefix_and_english():
    assert pivot.parse_stock_code("sh600519") == ("600519", "sh", False)
    assert pivot.parse_stock_code("SH.000852") == ("000852", "sh", False)
    assert pivot.parse_stock_code("sz159516") == ("159516", "sz", False)
    assert pivot.parse_stock_code("hk00700") == ("00700", "hk", False)
    # HSTECH 在特殊映射表内（原版契约：前缀 hk，非英文标记）
    assert pivot.parse_stock_code("HSTECH") == ("HSTECH", "hk", False)
    assert pivot.parse_stock_code("usN225") == ("N225", "us", False)


def test_parse_stock_code_special_map():
    assert pivot.parse_stock_code("au9999") == ("AU9999", "hf", False)
    assert pivot.parse_stock_code("N225") == ("N225", "us", False)
    assert pivot.parse_stock_code("HSI") == ("HSI", "hk", False)


# --------------------------------------------------------------------------
# 五种算法
# --------------------------------------------------------------------------

def test_classic_pivot():
    p = pivot.calculate_single_pivot(110, 90, 100, algorithm="经典")
    assert p["pp"] == 100.0
    assert p["r1"] == pytest.approx(110.0)      # 2*PP - low
    assert p["s1"] == pytest.approx(90.0)       # 2*PP - high
    assert p["r2"] == pytest.approx(120.0)      # PP + (H-L)
    assert p["s2"] == pytest.approx(80.0)       # PP - (H-L)
    assert p["r3"] == pytest.approx(140.0)      # r2 + (H-L)
    assert p["s3"] == pytest.approx(60.0)       # s2 - (H-L)


def test_fibonacci_pivot():
    p = pivot.calculate_single_pivot(110, 90, 100, algorithm="斐波那契")
    assert p["pp"] == 100.0
    assert p["r1"] == pytest.approx(100 + 20 * 0.382)
    assert p["s1"] == pytest.approx(100 - 20 * 0.382)
    assert p["r3"] == pytest.approx(120.0)
    assert p["s3"] == pytest.approx(80.0)


def test_camarilla_pivot():
    p = pivot.calculate_single_pivot(110, 90, 100, algorithm="卡玛利亚")
    assert p["pp"] == 100.0
    assert p["r1"] == round(100 + 20 / 12, 3)
    assert p["s1"] == round(100 - 20 / 12, 3)
    assert p["r4"] == pytest.approx(110.0)
    assert p["s4"] == pytest.approx(90.0)


def test_woodie_pivot():
    p = pivot.calculate_single_pivot(110, 90, 100, algorithm="伍迪")
    assert p["pp"] == pytest.approx((110 + 90 + 200) / 4)
    assert p["r3"] == "-"
    assert p["r4"] == "-"


def test_demark_pivot_open_variants():
    # close < open
    p1 = pivot.calculate_single_pivot(110, 90, 95, open_price=100, algorithm="迪马克")
    x1 = 110 + 2 * 90 + 95
    assert p1["pp"] == pytest.approx(x1 / 4)
    # close > open
    p2 = pivot.calculate_single_pivot(110, 90, 105, open_price=100, algorithm="迪马克")
    x2 = 2 * 110 + 90 + 105
    assert p2["pp"] == pytest.approx(x2 / 4)
    # close == open
    p3 = pivot.calculate_single_pivot(110, 90, 100, open_price=100, algorithm="迪马克")
    x3 = 110 + 90 + 2 * 100
    assert p3["pp"] == pytest.approx(x3 / 4)
    # 无开盘价回退
    p4 = pivot.calculate_single_pivot(110, 90, 100, algorithm="迪马克")
    assert p4["pp"] == pytest.approx(x3 / 4)


def test_compute_pivot_blocks_five_algos():
    blocks = pivot.compute_pivot_blocks(110, 90, 100, 100)
    assert [b["title"] for b in blocks] == ["经典", "斐波那契", "卡玛利亚", "伍迪", "迪马克"]
    classic = blocks[0]
    assert float(classic["pp"]) == pytest.approx(100.0)
    assert float(classic["r"]["R3"]) == pytest.approx(140.0)
    assert float(classic["s"]["S3"]) == pytest.approx(60.0)


# --------------------------------------------------------------------------
# 批量解析
# --------------------------------------------------------------------------

def test_parse_batch_codes_dedup_and_separators():
    codes = pivot.parse_batch_codes("600519, 000001；159516\n562800\t159845 600519")
    assert codes == ["600519", "000001", "159516", "562800", "159845"]
    assert pivot.parse_batch_codes("") == []
    assert pivot.parse_batch_codes("HSTECH sh000852") == ["HSTECH", "SH000852"]


# --------------------------------------------------------------------------
# 验证标色
# --------------------------------------------------------------------------

def test_mark_verify_levels_red_green():
    # 构造：经典 R1 恰为验证最高价（误差0）→ 红；S1 恰为验证最低价 → 绿
    high, low, close = 110, 90, 100
    blocks = pivot.compute_pivot_blocks(high, low, close, 100)
    best_r, best_s = pivot.mark_verify_levels(blocks, verify_high=110.0, verify_low=90.0)
    assert ("经典", "R1") in best_r["red"]
    assert ("经典", "S1") in best_s["green"]
    # 次优（误差≤2%）标橙/黄：经典 R2=120 与 110 相差约 9% > 2%，不标
    assert ("经典", "R2") not in best_r["orange"]


def test_mark_verify_levels_no_target():
    blocks = pivot.compute_pivot_blocks(110, 90, 100, 100)
    best_r, best_s = pivot.mark_verify_levels(blocks, verify_high=None, verify_low=None)
    assert not best_r["red"] and not best_r["orange"]
    assert not best_s["green"] and not best_s["yellow"]


# --------------------------------------------------------------------------
# 常量完整性
# --------------------------------------------------------------------------

def test_config_pivot_constants():
    assert config.SOURCE_TENCENT == "腾讯财经"
    assert config.SOURCE_SINA == "新浪财经"
    assert config.PIVOT_SOURCE_CHAIN[0] == config.SOURCE_TENCENT
    assert config.PIVOT_SOURCE_CHAIN[1] == config.SOURCE_SINA
    assert len(config.PIVOT_ALGORITHMS) == 5
    assert config.DISPLAY_POINTS == 10
    assert config.DEFAULT_WATCHLIST[0]["code"] == "sz159516"
    assert config.DEFAULT_WATCHLIST[1]["code"] == "sh513310"
    assert config.DEFAULT_WATCHLIST[2]["code"] == "sz159845"
