# -*- coding: utf-8 -*-
"""指标计算单元测试（在 GitHub Actions 中自动运行）。"""
import random

from app import config, indicator


def _make_rows(n=90, seed=7, with_amount=True):
    rnd = random.Random(seed)
    rows = []
    price = 10.0
    for i in range(n):
        open_ = round(price * (1 + rnd.uniform(-0.01, 0.01)), 3)
        close = round(open_ * (1 + rnd.uniform(-0.02, 0.02)), 3)
        high = round(max(open_, close) * (1 + rnd.uniform(0, 0.01)), 3)
        low = round(min(open_, close) * (1 - rnd.uniform(0, 0.01)), 3)
        volume = round(rnd.uniform(10000, 90000), 1)
        amount = round(volume * 100 * close, 1) if with_amount else None
        rows.append({
            "date": "2024-%02d-%02d" % ((i % 12) + 1, (i % 27) + 1),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "amount": amount,
        })
        price = close
    return rows


def test_nml_qrl_formula():
    rows = _make_rows()
    bars = indicator.compute(rows, config.VERSION_STOCK)
    i = len(bars) - 1
    trs = []
    prev_c = None
    for r in rows:
        if prev_c is None:
            trs.append(r["high"] - r["low"])
        else:
            trs.append(max(r["high"] - r["low"],
                           abs(r["high"] - prev_c),
                           abs(r["low"] - prev_c)))
        prev_c = r["close"]
    atr = sum(trs[i - 13:i + 1]) / 14.0
    hhv = max(r["high"] for r in rows[i - 20:i])
    assert abs(bars[i]["nml"] - (hhv + 0.5 * atr)) < 1e-9
    assert abs(bars[i]["qrl"] - (hhv + 1.0 * atr)) < 1e-9
    assert abs(bars[i]["qrl"] - bars[i]["nml"] - 0.5 * atr) < 1e-9


def test_smx_ma10():
    rows = _make_rows()
    bars = indicator.compute(rows, config.VERSION_STOCK)
    i = 50
    smx = sum(r["close"] for r in rows[i - 9:i + 1]) / 10.0
    assert abs(bars[i]["smx"] - smx) < 1e-9


def test_basic_no_cost_lines():
    rows = _make_rows()
    bars = indicator.compute(rows, config.VERSION_BASIC)
    assert "cbx20" not in bars[-1]
    assert "cbx60" not in bars[-1]


def test_stock_cost_amount_basis():
    rows = _make_rows(with_amount=True)
    bars = indicator.compute(rows, config.VERSION_STOCK)
    i = 70
    amt = sum(r["amount"] for r in rows[i - 19:i + 1])
    vol = sum(r["volume"] for r in rows[i - 19:i + 1])
    assert abs(bars[i]["cbx20"] - amt / vol / 100.0) < 1e-9
    assert bars[i]["cost_basis"] == "amount"


def test_stock_cost_estimate_when_no_amount():
    rows = _make_rows(with_amount=False)
    bars = indicator.compute(rows, config.VERSION_STOCK)
    i = 70
    num = sum(r["close"] * r["volume"] for r in rows[i - 19:i + 1])
    den = sum(r["volume"] for r in rows[i - 19:i + 1])
    assert abs(bars[i]["cbx20"] - num / den) < 1e-9
    assert bars[i]["cost_basis"] == "estimate"


def test_index_always_cv_basis():
    rows = _make_rows(with_amount=True)
    bars = indicator.compute(rows, config.VERSION_INDEX)
    i = 70
    num = sum(r["close"] * r["volume"] for r in rows[i - 19:i + 1])
    den = sum(r["volume"] for r in rows[i - 19:i + 1])
    assert abs(bars[i]["cbx20"] - num / den) < 1e-9
    assert bars[i]["cost_basis"] == "estimate"


def test_early_bars_none_then_available():
    rows = _make_rows()
    bars = indicator.compute(rows, config.VERSION_STOCK)
    assert bars[0]["nml"] is None        # 前20根无 HHV 基准
    assert bars[19]["nml"] is None
    assert bars[20]["nml"] is not None
    assert bars[8]["smx"] is None        # 前10根无均线
    assert bars[9]["smx"] is not None
    assert bars[18]["cbx20"] is None     # 前20根无20日成本
    assert bars[19]["cbx20"] is not None
