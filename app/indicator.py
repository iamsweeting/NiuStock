# -*- coding: utf-8 -*-
"""牛门线指标计算（纯函数，不依赖 Kivy，便于单元测试）。

公式（与通达信一致）：
    TR1   = MAX(H-L, ABS(H-REF(C,1)), ABS(L-REF(C,1)))   # 经典真实波幅
    ATRV  = MA(TR1, 14)                                   # 14 周期 ATR（简单均线）
    NML   = REF(HHV(H,20),1) + 0.5 * ATRV                 # 牛门线
    QRL   = REF(HHV(H,20),1) + 1.0 * ATRV                 # 强阻力线
    SMX   = MA(C,10)                                      # 生命线
    CBX20 = SUM(AMOUNT,20)/SUM(V,20)/100                  # 20 日成本（标的版，成交额口径）
    CBX60 = SUM(AMOUNT,60)/SUM(V,60)/100                  # 60 日成本
    指数版成本线改用  SUM(C*V,N)/SUM(V,N)                 # 收盘价×成交量 加权
"""
from . import config


def _sma(values, window):
    """简单移动平均；数据不足时对应位置为 None。"""
    out = [None] * len(values)
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= window:
            s -= values[i - window]
        if i >= window - 1:
            out[i] = s / window
    return out


def _rolling_max_exclusive(values, window):
    """第 i 个输出 = max(values[i-window : i])，即 REF(HHV(H,window),1)。"""
    out = [None] * len(values)
    for i in range(len(values)):
        if i < window:
            continue
        out[i] = max(values[i - window:i])
    return out


def _sum_ratio(numer, denom, window, is_amount):
    """滚动求和比值：SUM(numer,window)/SUM(denom,window)（/100 仅成交额口径）。"""
    out = [None] * len(numer)
    sn = 0.0
    sd = 0.0
    for i in range(len(numer)):
        sn += numer[i]
        sd += denom[i]
        if i >= window:
            sn -= numer[i - window]
            sd -= denom[i - window]
        if i >= window - 1 and sd > 0:
            val = sn / sd
            out[i] = val / 100.0 if is_amount else val
    return out


def compute(rows, version):
    """按时间升序的 K 线列表计算牛门线，返回等长指标列表。

    rows 元素：{date, open, high, low, close, volume, amount(可为None)}
    """
    n = len(rows)
    highs = [r["high"] for r in rows]
    lows = [r["low"] for r in rows]
    closes = [r["close"] for r in rows]
    vols = [r["volume"] for r in rows]

    # TR1 / ATRV
    trs = []
    prev_c = None
    for r in rows:
        if prev_c is None:
            trs.append(r["high"] - r["low"])
        else:
            trs.append(max(
                r["high"] - r["low"],
                abs(r["high"] - prev_c),
                abs(r["low"] - prev_c),
            ))
        prev_c = r["close"]
    atrv = _sma(trs, config.M)

    # NML / QRL / SMX
    hhv = _rolling_max_exclusive(highs, config.N)
    smx = _sma(closes, config.SMA10)

    # 成本线：标的版优先成交额口径（AMOUNT 全部可得时），否则/指数版用 C*V 加权估算
    amounts = [r.get("amount") for r in rows]
    use_amount = version == config.VERSION_STOCK and all(a is not None for a in amounts)
    if version != config.VERSION_BASIC:
        if use_amount:
            cbx20 = _sum_ratio(amounts, vols, config.CBX20_N, True)
            cbx60 = _sum_ratio(amounts, vols, config.CBX60_N, True)
        else:
            numer = [c * v for c, v in zip(closes, vols)]
            cbx20 = _sum_ratio(numer, vols, config.CBX20_N, False)
            cbx60 = _sum_ratio(numer, vols, config.CBX60_N, False)
    else:
        cbx20 = [None] * n
        cbx60 = [None] * n

    bars = []
    for i in range(n):
        bar = {
            "date": rows[i]["date"],
            "open": rows[i]["open"],
            "high": highs[i],
            "low": lows[i],
            "close": closes[i],
            "volume": vols[i],
        }
        bar["atr"] = atrv[i]
        if hhv[i] is not None and atrv[i] is not None:
            bar["nml"] = hhv[i] + 0.5 * atrv[i]
            bar["qrl"] = hhv[i] + 1.0 * atrv[i]
        else:
            bar["nml"] = None
            bar["qrl"] = None
        bar["smx"] = smx[i]
        if version != config.VERSION_BASIC:
            bar["cbx20"] = cbx20[i]
            bar["cbx60"] = cbx60[i]
            bar["cost_basis"] = "amount" if use_amount else "estimate"
        bars.append(bar)
    return bars
