# -*- coding: utf-8 -*-
"""批量枢轴辅助函数单元测试（名称显示规则）。"""
from app import batch


def test_name_display_one_line_full():
    assert batch.name_display("上证指数") == ("上证指数", 1)
    assert batch.name_display("A股", chars_per_line=5) == ("A股", 1)


def test_name_display_two_lines_full():
    # 超过单行但两行可放下 → 写全名换行
    text, lines = batch.name_display("中韩半导体ETF精选", chars_per_line=5)
    assert text == "中韩半导体ETF精选"
    assert lines == 2


def test_name_display_truncate_beyond_two_lines():
    # 两行仍放不下 → 截断 + 省略号
    text, lines = batch.name_display("中韩半导体ETF精选增强", chars_per_line=5)
    assert lines == 2
    assert text.endswith("…")
    assert len(text) == 5 * 2 - 1 + 1  # 9 字 + …

