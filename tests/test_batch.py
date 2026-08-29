# -*- coding: utf-8 -*-
"""批量枢轴辅助函数单元测试（名称显示规则，字符宽度语义）。"""
from app import batch


def test_name_display_one_line_full():
    assert batch.name_display("上证指数") == ("上证指数", 1)
    assert batch.name_display("A股") == ("A股", 1)          # 1.5 字符宽 < 8


def test_name_display_width_semantics():
    # 1 汉字=2 字符、1 半角字母/数字=1 字符（ETF 三字母=3 字符）
    assert batch._display_width("ETF") == 3
    assert batch._display_width("中证800") == 2 * 2 + 3   # 中证(4) + 800(3)
    assert batch._display_width("恒生互联网ETF") == 5 * 2 + 3  # 恒生互联网(10) + ETF(3)
    assert batch._display_width("半导体设备ETF国泰") == 5 * 2 + 3 + 2 * 2  # 17


def test_name_display_two_lines_full():
    # 中韩半导体ETF精选：10+3+4=17 字符 > 8 → 2 行（词边界断行，ETF 不拆开）
    text, lines = batch.name_display("中韩半导体ETF精选", chars_per_line=8)
    assert lines == 2
    assert "ETF" in text
    # 每行宽度 ≤8 字符
    for ln in text.split("\n"):
        assert batch._display_width(ln) <= 8


def test_name_display_etf_not_split():
    # 用户实测：ETF 曾被拆成 E/TF → 词边界断行，ETF 始终完整
    for name in ("恒生互联网ETF华夏", "半导体设备ETF国泰"):
        text, lines = batch.name_display(name, chars_per_line=8)
        assert lines == 2
        for ln in text.split("\n"):
            if "TF" in ln:
                assert "ETF" in ln            # ETF 未被拆散


def test_name_display_truncate_beyond_16():
    # 两行合计 ≤16 字符（=8 汉字），超出截断（不用省略号）
    text, lines = batch.name_display("国泰中证半导体材料设备主题ETF", chars_per_line=8)
    assert lines == 2
    assert not text.endswith("…")
    assert len(text.split("\n")) <= 2
    # 总宽不超 16 字符
    total = sum(batch._display_width(ln) for ln in text.split("\n"))
    assert total <= 16


def test_name_display_single_line_trend():
    # 趋势页快捷按钮：单行 ≤16 字符（=8 汉字），超长截断
    text, lines = batch.name_display("半导体设备ETF国泰", chars_per_line=16, max_lines=1)
    assert lines == 1
    assert "\n" not in text
    assert batch._display_width(text) <= 16
