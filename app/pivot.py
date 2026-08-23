# -*- coding: utf-8 -*-
"""枢轴点计算（纯函数，不依赖 Kivy/Flet，便于单元测试）。

移植自 workspaceStock/StockPivot/main.py（V1.5.6）与 BatchStock/main.py：
  - 代码解析（含全球特殊代码映射表）
  - 五种枢轴算法：经典 / 斐波那契 / 卡玛利亚 / 伍迪 / 迪马克（按日/按周共用）
  - 批量代码解析与单算法计算
  - 验证标色逻辑（下一交易日/周误差 ≤1% 标红/绿，≤2% 标橙/黄）
"""
import re

from . import config

# 常见特殊代码映射表（腾讯接口格式）
_SPECIAL_CODE_MAP = {
    # 贵金属/期货
    "AU9999": ("AU9999", "hf"),      # 上海黄金
    "AG9999": ("AG9999", "hf"),      # 上海白银
    "CU9999": ("CU9999", "hf"),      # 沪铜
    "AU": ("AU9999", "hf"),          # 黄金简写
    # 全球指数
    "N225": ("N225", "us"),          # 日经225
    "NIKKEI": ("N225", "us"),        # 日经225
    "DJI": ("DJIA", "us"),           # 道琼斯
    "DOW": ("DJIA", "us"),           # 道琼斯
    "IXIC": ("IXIC", "us"),          # 纳斯达克
    "NASDAQ": ("IXIC", "us"),        # 纳斯达克
    "SPX": ("SPX", "us"),            # 标普500
    "SP500": ("SPX", "us"),          # 标普500
    "HSI": ("HSI", "hk"),            # 恒生指数
    "HSTECH": ("HSTECH", "hk"),      # 恒生科技
    "HSAHP": ("HSAHP", "hk"),        # 恒生AH股
    # 外汇/商品
    "USDCNY": ("USDCNY", "fx"),      # 美元兑人民币
    "USDJPY": ("USDJPY", "fx"),      # 美元兑日元
    "XAU": ("XAU", "hf"),            # 国际黄金
    "XAG": ("XAG", "hf"),            # 国际白银
    "WTI": ("WTI", "hf"),            # 美原油
    "BRENT": ("BRENT", "hf"),        # 布伦特原油
}

_PREFIXES = ("SH.", "SZ.", "HK.", "US.", "HF.", "BJ.", "FX.",
             "SH", "SZ", "HK", "US", "HF", "BJ", "FX")


def parse_stock_code(stock_code):
    """解析股票代码，支持格式：
    - 纯数字：600519 → (600519, sh, False)
    - 带前缀：sh600519 / sz000852 / usN225 / hfAU9999 → 直接解析
    - 英文代码：HSTECH / AAPL → (HSTECH, hk, True)
    - 特殊代码：au9999 → (AU9999, hf, False)  自动映射
    - 港股数字：00700 → (00700, hk, False)
    返回：(clean_code, market_prefix, is_english)
    """
    code = (stock_code or "").strip().upper()
    if not code:
        return "", "", False
    # 带前缀格式：sh600519, sz000852, hk00700, usN225, hfAU9999
    if code.startswith(_PREFIXES) and len(code) > 2:
        if code[2:3] == ".":
            prefix = code[:2].lower() if not code.startswith("FX.") else "fx"
            clean = code[3:]
        else:
            prefix = code[:2].lower() if not code.startswith("FX") else "fx"
            clean = code[2:]
        return clean, prefix, False
    # 先查特殊代码映射表（如 au9999 → hf.AU9999）
    if code in _SPECIAL_CODE_MAP:
        clean, prefix = _SPECIAL_CODE_MAP[code]
        return clean, prefix, False
    # 纯英文代码（不含数字）
    if code.isalpha():
        return code, "hk", True  # 英文代码默认港股
    # 纯数字代码
    if code.isdigit():
        # 港股：5位数字（如00700、09988）
        if len(code) == 5:
            return code, "hk", False
        # A股：6位数字
        if code.startswith(("5", "6", "68", "69")):
            return code, "sh", False
        elif code.startswith(("0", "1", "3", "00", "30", "39")):
            return code, "sz", False
        elif code.startswith("8"):
            return code, "bj", False  # 北交所
        elif code.startswith("4"):
            return code, "bj", False  # 北交所/新三板
        else:
            return code, "sz", False  # 默认深圳
    # 混合代码（字母+数字）且不在映射表中，尝试作为英文代码
    return code, "hk", True


# ---------------------------------------------------------------------------
# 五种枢轴算法
# ---------------------------------------------------------------------------

def _fmt(v):
    return "%.3f" % v


def calculate_pivot_points(high, low, close, open_price=None):
    """五种算法全量计算，返回文本行列表（与旧版一致，供 parse_results 使用）。"""
    results = []
    pp = (high + low + close) / 3
    s1 = (2 * pp) - high
    r1 = (2 * pp) - low
    s2 = pp - (high - low)
    r2 = pp + (high - low)
    s3 = s2 - (high - low)
    r3 = r2 + (high - low)
    results.append("经典枢轴点-PP: {:.3f}".format(pp))
    results.append("R1: {:.3f}, R2: {:.3f}, R3: {:.3f}".format(r1, r2, r3))
    results.append("S1: {:.3f}, S2: {:.3f}, S3: {:.3f}".format(s1, s2, s3))
    pp = (high + low + close) / 3
    r1 = pp + (high - low) * 0.382
    r2 = pp + (high - low) * 0.618
    r3 = pp + (high - low) * 1.0
    s1 = pp - (high - low) * 0.382
    s2 = pp - (high - low) * 0.618
    s3 = pp - (high - low) * 1.0
    results.append("斐波那契枢轴点-PP: {:.3f}".format(pp))
    results.append("R1: {:.3f}, R2: {:.3f}, R3: {:.3f}".format(r1, r2, r3))
    results.append("S1: {:.3f}, S2: {:.3f}, S3: {:.3f}".format(s1, s2, s3))
    pp = (high + low + close) / 3
    rng = high - low
    r1 = close + rng * 1.1 / 12
    r2 = close + rng * 1.1 / 6
    r3 = close + rng * 1.1 / 4
    r4 = close + rng * 1.1 / 2
    s1 = close - rng * 1.1 / 12
    s2 = close - rng * 1.1 / 6
    s3 = close - rng * 1.1 / 4
    s4 = close - rng * 1.1 / 2
    results.append("卡玛利亚枢轴点-PP: {:.3f}".format(pp))
    results.append("R1: {:.3f}, R2: {:.3f}, R3: {:.3f}, R4: {:.3f}".format(r1, r2, r3, r4))
    results.append("S1: {:.3f}, S2: {:.3f}, S3: {:.3f}, S4: {:.3f}".format(s1, s2, s3, s4))
    pp = (high + low + 2 * close) / 4
    s1 = (2 * pp) - high
    r1 = (2 * pp) - low
    s2 = pp - (high - low)
    r2 = pp + (high - low)
    results.append("伍迪枢轴点-PP: {:.3f}".format(pp))
    results.append("R1: {:.3f}, R2: {:.3f}".format(r1, r2))
    results.append("S1: {:.3f}, S2: {:.3f}".format(s1, s2))
    # 迪马克枢轴点：判断依据为收盘价 vs 开盘价（非高低点）
    if open_price is not None:
        if close < open_price:
            x = high + 2 * low + close
        elif close > open_price:
            x = 2 * high + low + close
        else:
            x = high + low + 2 * close
    else:
        x = high + low + 2 * close
    pp = x / 4
    r1 = x / 2 - low
    s1 = x / 2 - high
    results.append("迪马克枢轴点-PP: {:.3f}".format(pp))
    results.append("R1: {:.3f}".format(r1))
    results.append("S1: {:.3f}\n".format(s1))
    return results


def parse_results(results):
    """把文本行结果解析为分块结构（标题/PP/R/S）。"""
    blocks = []
    current = None
    for line in results:
        line = line.strip()
        if not line:
            continue
        if "枢轴点-PP:" in line:
            if current:
                blocks.append(current)
            title = line.split("枢轴点-PP:")[0].strip()
            pp = line.split("枢轴点-PP:")[1].strip()
            current = {"title": title, "pp": pp, "r": {}, "s": {}}
        elif line.startswith("R"):
            parts = [p.strip() for p in line.split(",") if p.strip()]
            for p in parts:
                if ":" in p:
                    k, v = p.split(":", 1)
                    current["r"][k.strip()] = v.strip()
        elif line.startswith("S"):
            parts = [p.strip() for p in line.split(",") if p.strip()]
            for p in parts:
                if ":" in p:
                    k, v = p.split(":", 1)
                    current["s"][k.strip()] = v.strip()
    if current:
        blocks.append(current)
    return blocks


def compute_pivot_blocks(high, low, close, open_price=None):
    """一站式：输入 OHLC，返回五种算法的分块结果。"""
    return parse_results(calculate_pivot_points(high, low, close, open_price))


def calculate_single_pivot(high, low, close, open_price=None, algorithm="经典"):
    """单算法计算（批量版用），返回含 pp/r1..r4/s1..s4 的字典，缺省位为 "-"。"""
    if algorithm == "经典":
        pp = (high + low + close) / 3
        r1 = (2 * pp) - low
        s1 = (2 * pp) - high
        r2 = pp + (high - low)
        s2 = pp - (high - low)
        r3 = r2 + (high - low)
        s3 = s2 - (high - low)
        return {"pp": round(pp, 3), "r1": round(r1, 3), "s1": round(s1, 3),
                "r2": round(r2, 3), "s2": round(s2, 3), "r3": round(r3, 3),
                "s3": round(s3, 3), "r4": "-", "s4": "-"}
    elif algorithm == "斐波那契":
        pp = (high + low + close) / 3
        r1 = pp + (high - low) * 0.382
        s1 = pp - (high - low) * 0.382
        r2 = pp + (high - low) * 0.618
        s2 = pp - (high - low) * 0.618
        r3 = pp + (high - low) * 1.0
        s3 = pp - (high - low) * 1.0
        return {"pp": round(pp, 3), "r1": round(r1, 3), "s1": round(s1, 3),
                "r2": round(r2, 3), "s2": round(s2, 3), "r3": round(r3, 3),
                "s3": round(s3, 3), "r4": "-", "s4": "-"}
    elif algorithm == "卡玛利亚":
        # 标准卡玛利亚公式带 1.1 系数：R = C ± (H-L) * 1.1/N
        pp = (high + low + close) / 3
        rng = high - low
        r1 = close + rng * 1.1 / 12
        s1 = close - rng * 1.1 / 12
        r2 = close + rng * 1.1 / 6
        s2 = close - rng * 1.1 / 6
        r3 = close + rng * 1.1 / 4
        s3 = close - rng * 1.1 / 4
        r4 = close + rng * 1.1 / 2
        s4 = close - rng * 1.1 / 2
        return {"pp": round(pp, 3), "r1": round(r1, 3), "s1": round(s1, 3),
                "r2": round(r2, 3), "s2": round(s2, 3), "r3": round(r3, 3),
                "s3": round(s3, 3), "r4": round(r4, 3), "s4": round(s4, 3)}
    elif algorithm == "伍迪":
        pp = (high + low + 2 * close) / 4
        r1 = (2 * pp) - low
        s1 = (2 * pp) - high
        r2 = pp + (high - low)
        s2 = pp - (high - low)
        return {"pp": round(pp, 3), "r1": round(r1, 3), "s1": round(s1, 3),
                "r2": round(r2, 3), "s2": round(s2, 3), "r3": "-", "s3": "-",
                "r4": "-", "s4": "-"}
    elif algorithm == "迪马克":
        # 迪马克枢轴点：判断依据为收盘价 vs 开盘价（非高低点）
        if open_price is not None:
            if close < open_price:
                x = high + 2 * low + close
            elif close > open_price:
                x = 2 * high + low + close
            else:
                x = high + low + 2 * close
        else:
            x = high + low + 2 * close
        pp = x / 4
        r1 = x / 2 - low
        s1 = x / 2 - high
        return {"pp": round(pp, 3), "r1": round(r1, 3), "s1": round(s1, 3),
                "r2": "-", "s2": "-", "r3": "-", "s3": "-", "r4": "-", "s4": "-"}
    else:
        pp = (high + low + close) / 3
        r1 = (2 * pp) - low
        s1 = (2 * pp) - high
        r2 = pp + (high - low)
        s2 = pp - (high - low)
        return {"pp": round(pp, 3), "r1": round(r1, 3), "s1": round(s1, 3),
                "r2": round(r2, 3), "s2": round(s2, 3), "r3": "-", "s3": "-",
                "r4": "-", "s4": "-"}


# ---------------------------------------------------------------------------
# 批量解析
# ---------------------------------------------------------------------------

def parse_batch_codes(text):
    """把多行/多分隔符文本解析为去重后的代码列表（保留原输入大小写风格）。"""
    if not text:
        return []
    unified = (text.replace("\uFF1B", " ").replace(";", " ")
               .replace("\uFF0C", " ").replace(",", " ")
               .replace("\n", " ").replace("\t", " ").replace("\r", " "))
    parts = unified.split()
    codes = []
    for p in parts:
        c = p.strip().upper()
        if not c:
            continue
        # 支持带前缀格式：sh600519, sz000852, hk00700, usN225, hfAU9999
        if c.startswith(_PREFIXES) and len(c) > 2:
            codes.append(c)
        # 特殊映射表代码（如 AU9999, N225）
        elif c in _SPECIAL_CODE_MAP:
            codes.append(c)
        # 纯英文代码（如 HSTECH, AAPL）
        elif c.isalpha() and len(c) >= 2:
            codes.append(c)
        # 纯数字代码（4-8位）
        elif c.isdigit() and 4 <= len(c) <= 8:
            codes.append(c)
    seen = set()
    result = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            result.append(c)
    return result


# ---------------------------------------------------------------------------
# 验证标色（纯函数）：下一交易日/周验证，误差 ≤1% 标红(R)/绿(S)，≤2% 标橙/黄
# ---------------------------------------------------------------------------

_ALGO_KEYS = (("经典", "经典"), ("斐波", "斐波那契"), ("卡玛", "卡玛利亚"),
              ("伍迪", "伍迪"), ("迪马克", "迪马克"))


def mark_verify_levels(blocks, verify_high=None, verify_low=None):
    """返回 (best_r, best_s)：best_r = {"red": set((key,lvl)), "orange": set(...)}。

    R 系列与验证最高价比较、S 系列与验证最低价比较；PP 不参与比较。
    """
    best_r = {"red": set(), "orange": set()}
    best_s = {"green": set(), "yellow": set()}
    block_map = {b["title"]: b for b in blocks}

    def _collect(r_or_s):
        out = []
        for _show, data_key in _ALGO_KEYS:
            data = block_map.get(data_key)
            if not data:
                continue
            for lvl in (["R1", "R2", "R3"] if r_or_s == "R" else ["S1", "S2", "S3"]):
                val = data[r_or_s.lower()].get(lvl, "-")
                if val != "-":
                    try:
                        out.append((float(val), data_key, lvl))
                    except (ValueError, TypeError):
                        pass
        return out

    def _mark(items, target, near_set, far_set, near_color, far_color):
        if target is None or target <= 0:
            return
        scored = []
        for fv, dk, lv in items:
            scored.append((abs(fv - target) / target, dk, lv))
        if not scored:
            return
        scored.sort(key=lambda x: x[0])
        best_err = scored[0][0]
        if best_err > 0.02:
            return
        for pct, dk, lv in scored:
            if abs(pct - best_err) < 0.001:
                near_set.add((dk, lv))
            else:
                break
        # 次优：仅当最优误差≤2%时，次优误差≤2%标远色
        if len(scored) > 1:
            second_start = 0
            for i, (pct, dk, lv) in enumerate(scored):
                if abs(pct - best_err) >= 0.001:
                    second_start = i
                    break
            if 0 < second_start < len(scored):
                second_err = scored[second_start][0]
                if second_err <= 0.02:
                    for i in range(second_start, len(scored)):
                        pct, dk, lv = scored[i]
                        if abs(pct - second_err) < 0.001:
                            far_set.add((dk, lv))
                        else:
                            break

    _mark(_collect("R"), verify_high, best_r["red"], best_r["orange"], "red", "orange")
    _mark(_collect("S"), verify_low, best_s["green"], best_s["yellow"], "green", "yellow")
    return best_r, best_s


# 供 UI 显示用的简短名称
ALGO_SHOW_KEYS = _ALGO_KEYS
LEVELS = ("R3", "R2", "R1", "PP", "S1", "S2", "S3")
