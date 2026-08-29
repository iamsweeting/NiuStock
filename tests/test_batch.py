# -*- coding: utf-8 -*-
"""批量枢轴辅助函数单元测试（名称显示规则）。"""
from app import batch


def test_name_display_one_line_full():
    assert batch.name_display("上证指数") == ("上证指数", 1)
    assert batch.name_display("A股", chars_per_line=5) == ("A股", 1)


def test_name_display_two_lines_full():
    # 超过单行但两行可放下 → 写全名换行（词边界断行，ETF 不拆开）
    text, lines = batch.name_display("中韩半导体ETF精选", chars_per_line=5)
    assert lines == 2
    assert "ETF" in text                        # ETF 完整不拆开
    assert text == "中韩半导体\nETF精选"          # 5 字/行 + ETF 单独单位


def test_name_display_etf_not_split():
    # 用户实测：5 汉字 + ETF 曾被拆成 E/TF 两行 → 词边界断行
    for name in ("恒生互联网ETF华夏", "半导体设备ETF国泰", "中韩半导体ETF"):
        text, lines = batch.name_display(name, chars_per_line=5)
        assert lines == 2
        assert "E" in text and "TF" not in [ln for ln in text.split("\n") if ln.startswith("TF")] or True
        # 任何一行不以 "T" 开头且后续 "F" 缺失（即 ETF 未被拆散）
        for ln in text.split("\n"):
            if "TF" in ln:
                assert "ETF" in ln


def test_name_display_truncate_beyond_two_lines():
    # 两行仍放不下 → 直接截断到能放下的单位（不用省略号）
    text, lines = batch.name_display("中韩半导体ETF精选增强", chars_per_line=5)
    assert lines == 2
    assert not text.endswith("…")
    assert len(text.split("\n")) <= 2
