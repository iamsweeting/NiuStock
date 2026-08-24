# -*- coding: utf-8 -*-
"""趋势判读（纯函数，便于单元测试）。

输出：结构判断（偏多/震荡偏多/震荡偏空/偏空）、阶段描述、概述段落、关键位清单。
指标命名：YL 压力线（原NML）、QL 止盈线（原QRL）、ZS 止损线（原SMX）。
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
        stage = "止损线上方运行，等待突破"
    else:
        stage = "跌破止损线，短期趋势走弱"

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

    # ---- 操作建议（需求：结构判断给出买卖参考） ----
    advice, advice_color = _advice_for(score, c, qrl, nml, smx,
                                       cbx20, cbx60, has_cost)

    # ---- 关键位（精简：只列最重要的压力/支撑）----
    levels = []
    if nml is not None:
        if c < nml:
            levels.append(("压力", "YL 压力线", nml, "距 %.1f%%" % abs(_pct_above(c, nml))))
        else:
            levels.append(("支撑", "YL 压力线", nml, "已站上"))
    if qrl is not None and nml is not None and c >= nml:
        levels.append(("压力", "QL 止盈线", qrl, "上方空间"))
    if smx is not None:
        levels.append(("支撑", "ZS 止损线", smx, "上方" if c >= smx else "下方"))
    if has_cost and cbx60 is not None and cbx20 is not None and c >= cbx60 and c < cbx20:
        levels.append(("提示", "CBX20", cbx20, "短期压力"))

    # ---- 概述（1-2 行，只讲相对位置，不再引用各线数值）----
    if qrl is not None and c >= qrl:
        pos_line = "收盘站上止盈线，强势区"
    elif nml is not None and c >= nml:
        pos_line = "收盘在压力线与止盈线之间，突破确认区"
    elif smx is not None and c >= smx:
        pos_line = "收盘在止损线上方、压力线下方，待突破"
    elif smx is not None:
        pos_line = "收盘跌破止损线，弱势区"
    else:
        pos_line = ""
    if has_cost:
        cost_line = "短期成本%s支撑、中期成本%s" % (
            "提供" if (cbx20 is not None and c >= cbx20) else "承压",
            "已收复" if (cbx60 is not None and c >= cbx60) else "未收复")
    else:
        cost_line = "均线%s运行" % ("上方" if (smx is not None and c >= smx) else "下方")
    summary = "%s；%s" % (pos_line, cost_line) if pos_line else cost_line

    return {
        "verdict": verdict,
        "verdict_color": vcolor,
        "stage": stage,
        "summary": summary,
        "levels": levels,
        "flags": flags,
        "score": score,
        "advice": advice,
        "advice_color": advice_color,
    }


def _advice_for(score, c, qrl, nml, smx, cbx20, cbx60, has_cost):
    """根据结构得分给出买卖参考建议。

    规则：
      - 强势（站上 QL 止盈线 / 5 分以上）：持股/可低吸，回踩不破加仓
      - 偏多（站上 YL 压力线 / 3-4 分）：逢低分批买入，突破 QL 加仓
      - 震荡（2-3 分）：观望为主，等方向明确
      - 偏空（<2 分或跌破 ZS 止损线）：反弹减仓/回避，等企稳
    """
    if score >= 5:
        return "持股为主，回踩不破可低吸加仓", COLOR_UP
    if score >= 3:
        return "逢低分批买入，站稳强阻力线后可加仓", COLOR_UP
    if score >= 2:
        return "观望为主，等突破或回踩确认再动", COLOR_MID
    if smx is not None and c < smx:
        return "反弹减仓，跌破生命线宜回避", COLOR_DOWN
    return "观望，暂不宜追高", COLOR_NEUTRAL
