# -*- coding: utf-8 -*-
"""文字判读单元测试。"""
from app import config, interpreter


def _bar(close, nml=10.0, qrl=11.0, smx=9.0, cbx20=8.5, cbx60=8.0):
    return {
        "close": close, "nml": nml, "qrl": qrl, "smx": smx,
        "cbx20": cbx20, "cbx60": cbx60,
    }


def test_strong_uptrend():
    res = interpreter.interpret(_bar(11.5), config.VERSION_STOCK)
    assert res["verdict"] == "偏多"
    assert "强势上攻" in res["stage"]
    assert res["flags"]["nml"][0] == "已突破"
    assert res["flags"]["qrl"][0] == "已突破"
    # 结论不再引用数值，改为线序描述（需求：数值没有相对位置重要）
    assert "多头排列" in res["summary"]
    assert "11.5" not in res["summary"]


def test_just_broke_nml():
    res = interpreter.interpret(_bar(10.3), config.VERSION_STOCK)
    assert res["verdict"] in ("偏多", "震荡偏多")
    assert "突破确认" in res["stage"]
    assert res["flags"]["nml"][0] == "已突破"


def test_waiting_breakout_like_doc_example():
    # 文档示例场景：收盘站上 CBX60/CBX20/SMX，但 NML 未突破
    res = interpreter.interpret(
        _bar(8.3, nml=10.0, qrl=11.0, smx=8.0, cbx20=8.1, cbx60=7.7),
        config.VERSION_STOCK,
    )
    assert "底部确认中" in res["stage"]
    # 回踩观察位提示只保留在 levels，summary 中不再重复
    assert "加仓观察位" not in res["summary"]
    assert any("回踩" in l[3] for l in res["levels"])
    assert res["verdict"] in ("震荡偏多", "偏多")


def test_weak_trend():
    res = interpreter.interpret(
        _bar(6.0, nml=10.0, qrl=11.0, smx=9.0, cbx20=8.5, cbx60=8.0),
        config.VERSION_STOCK,
    )
    assert res["verdict"] == "偏空"
    assert "走弱" in res["stage"]


def test_advice_present_and_color():
    # 强势（≥5分）→ 持股/低吸建议
    res = interpreter.interpret(_bar(11.5), config.VERSION_STOCK)
    assert res["advice"]
    assert "买入" in res["advice"] or "持股" in res["advice"] or "低吸" in res["advice"]
    assert res["advice_color"] == interpreter.COLOR_UP
    # 弱市 → 减仓/回避
    res2 = interpreter.interpret(
        _bar(6.0, nml=10.0, qrl=11.0, smx=9.0, cbx20=8.5, cbx60=8.0),
        config.VERSION_STOCK,
    )
    assert "减仓" in res2["advice"] or "回避" in res2["advice"]
    assert res2["advice_color"] == interpreter.COLOR_DOWN


def test_advice_basic_version():
    b = {"close": 9.2, "nml": 10.0, "qrl": 11.0, "smx": 9.0}
    res = interpreter.interpret(b, config.VERSION_BASIC)
    assert res["advice"]


def test_basic_version_no_cost_lines():
    b = {"close": 9.2, "nml": 10.0, "qrl": 11.0, "smx": 9.0}
    res = interpreter.interpret(b, config.VERSION_BASIC)
    assert "cbx20" not in res["flags"]
    assert not any("CBX" in l[1] for l in res["levels"])


def test_fmt_price():
    assert interpreter.fmt_price(0.77) == "0.770"
    assert interpreter.fmt_price(1234.5) == "1234.50"
    assert interpreter.fmt_price(None) == "—"
