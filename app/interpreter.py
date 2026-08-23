# -*- coding: utf-8 -*-
"""牛门线文字判读（纯函数，便于单元测试）。

输出：结构判断（偏多/震荡偏多/震荡偏空/偏空）、阶段描述、概述段落、关键位清单。
"""
from . import config

# 红/绿与 config 中涨跌色同义，直接引用避免两处漂移；
# 橙/蓝为本模块语义（中性/偏空提示），保留本地定义。
COLOR_UP = config.COLOR_UP        # 红 = 偏多 / 突破
COLOR_MID = (1.00, 0.65, 0.15, 1.0)  # 橙 = 中性（与 config.COLOR_QRL 同值，语义独立）
COLOR_NEUTRAL = (0.36, 0.62, 0.86, 1.0)  # 蓝 = 偏空提示
COLOR_DOWN = config.COLOR_DOWN    # 绿 = 偏空


def fmt_price(v):
    """价格格式化：小于 1 保留 3 位小数，否则 2 位。"""
    if v is None:
        return "—"
    return "%.3f" % v if abs(v) < 1 else "%.2f" % v


def _pct_above(c, v):
    if not v:
        return 0.0
    return (c - v) / v * 100.0


def interpret(bar, version):
    """对单根K线（含指标值）进行文字判读。bar 需含 close/nml/qrl/smx，标的版还需 cbx20/cbx60。"""
    c = bar["close"]
    nml = bar.get("nml")
    qrl = bar.get("qrl")
    smx = bar.get("smx")
    cbx20 = bar.get("cbx20")
    cbx60 = bar.get("cbx60")
    has_cost = version != config.VERSION_BASIC

    # ---- 各线相对位置标记 ----
    flags = {}
    if nml is not None:
        if c >= nml:
            flags["nml"] = ("已突破", COLOR_UP)
        elif c >= nml * 0.98:
            flags["nml"] = ("逼近", COLOR_MID)
        else:
            flags["nml"] = ("未突破", COLOR_DOWN)
    if qrl is not None:
        flags["qrl"] = ("已突破", COLOR_UP) if c >= qrl else ("未突破", COLOR_DOWN)
    if smx is not None:
        flags["smx"] = ("上方", COLOR_UP) if c >= smx else ("下方", COLOR_DOWN)
    if has_cost:
        if cbx20 is not None:
            flags["cbx20"] = ("上方", COLOR_UP) if c >= cbx20 else ("下方", COLOR_DOWN)
        if cbx60 is not None:
            flags["cbx60"] = ("上方", COLOR_UP) if c >= cbx60 else ("下方", COLOR_DOWN)

    # ---- 阶段判断 ----
    if qrl is not None and c >= qrl:
        stage = "强势上攻，趋势加速"
    elif nml is not None and c >= nml:
        stage = "突破确认，回踩不破则持有"
    elif has_cost and cbx60 is not None and c >= cbx60 and \
            cbx20 is not None and c >= cbx20 and smx is not None and c >= smx:
        stage = "底部确认中，等待突破"
    elif has_cost and cbx60 is not None and c >= cbx60 and \
            cbx20 is not None and c < cbx20:
        stage = "中期成本上方、短期成本下方，震荡整理"
    elif has_cost and cbx60 is not None and c < cbx60 and smx is not None and c >= smx:
        stage = "中期成本下方，以反弹对待"
    elif smx is not None and c >= smx:
        stage = "均线上方运行，等待突破"
    else:
        stage = "跌破生命线，短期趋势走弱"

    # ---- 综合得分与结构判断 ----
    score = 0
    if qrl is not None and c >= qrl:
        score += 2
    if nml is not None and c >= nml:
        score += 1
    if smx is not None and c >= smx:
        score += 1
    if has_cost:
        if cbx20 is not None and c >= cbx20:
            score += 1
        if cbx60 is not None and c >= cbx60:
            score += 1
    if score >= 5:
        verdict, vcolor = "偏多", COLOR_UP
    elif score >= 3:
        verdict, vcolor = "震荡偏多", COLOR_MID
    elif score >= 2:
        verdict, vcolor = "震荡偏空", COLOR_NEUTRAL
    else:
        verdict, vcolor = "偏空", COLOR_DOWN

    # ---- 关键位清单 ----
    levels = []
    if nml is not None:
        if c < nml:
            levels.append(("压力", "NML 牛门线", nml, "距突破 %.1f%%" % abs(_pct_above(c, nml))))
        else:
            levels.append(("突破", "NML 牛门线", nml, "已站上，上看 QRL"))
    if qrl is not None and nml is not None and c >= nml:
        levels.append(("压力", "QRL 强阻力线", qrl, "上方空间"))
    if smx is not None:
        levels.append(("支撑", "SMX 生命线", smx, "上方运行" if c >= smx else "下方运行"))
    if has_cost:
        if cbx20 is not None:
            levels.append(("支撑", "CBX20 短期成本", cbx20, "上方" if c >= cbx20 else "下方"))
        if cbx60 is not None:
            levels.append(("支撑", "CBX60 中期成本", cbx60, "上方" if c >= cbx60 else "下方"))
    if has_cost and cbx60 is not None and nml is not None and c < nml and c >= cbx60:
        levels.append(("提示", "回踩观察位", cbx60, "若回踩不破，是较好的加仓观察位"))

    # ---- 概述段落（只讲相对位置与线序，不再引用各线数值）----
    parts = []
    # 1) 收盘价相对各线的位置（数值无关）
    if qrl is not None and c >= qrl:
        parts.append("收盘已站上强阻力线，处于强势区")
    elif nml is not None and c >= nml:
        parts.append("收盘位于牛门线与强阻力线之间，突破确认区")
    elif smx is not None and c >= smx:
        parts.append("收盘位于生命线上方、牛门线下方，待突破区")
    elif smx is not None:
        parts.append("收盘跌破生命线，弱势区")
    # 2) 成本线关系
    if has_cost:
        parts.append("短期成本提供支撑" if (cbx20 is not None and c >= cbx20) else "短期成本承压")
        parts.append("中期成本已收复" if (cbx60 is not None and c >= cbx60) else "中期成本尚未收复")
    else:
        parts.append("均线系统上方运行" if (smx is not None and c >= smx) else "均线系统下方运行")
    # 3) 五线线序（从高到低；相对位置比数值更重要）
    order_items = []
    for k, v in (("QRL", qrl), ("NML", nml), ("SMX", smx),
                 ("CBX20", cbx20), ("CBX60", cbx60)):
        if v is not None:
            order_items.append((k, v))
    order_items.sort(key=lambda x: x[1], reverse=True)
    order_str = " > ".join(k for k, _v in order_items)
    if len(order_items) >= 3:
        keys = [k for k, _v in order_items]
        if keys[:3] == ["QRL", "NML", "SMX"]:
            parts.append("核心线序 QRL>NML>SMX 呈多头排列")
        else:
            parts.append("线序 %s" % order_str)
    summary = "结构%s；阶段：%s。%s。" % (verdict, stage, "；".join(parts))

    return {
        "verdict": verdict,
        "verdict_color": vcolor,
        "stage": stage,
        "summary": summary,
        "levels": levels,
        "flags": flags,
        "score": score,
    }
