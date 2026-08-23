# -*- coding: utf-8 -*-
"""大盘信息数据模块（牛票 Nstock）。

需求：
一、本日实时（页面切换前自动刷新，不做高频轮询，避免触发反爬）
  1. A股成交总金额（沪深两市）、本日预测额（按已交易时长线性外推）
  2. 上证 / 中证1000 / 沪深300 / 恒生 / 恒生科技 / 伦敦金 / 沪金 / 韩国KOSPI / 日经
  3. 沪深300成分股价格中位数
二、历史（近 5 个交易日）
  1. A股成交总金额  2. 美元兑人民币中间价  3. WTI原油  4. 伦敦金  5. 韩国半导体(三星电子+SK海力士)

数据源（低请求量、批量合并、请求间隔节流）：
  - 新浪 hq.sinajs.cn：A股/港股指数、伦敦金、沪金 —— 1 个批量请求
  - 新浪成分股接口：沪深300成分价格（3 页）
  - 新浪国际期货日K：伦敦金历史
  - Yahoo chart：日经/韩国KOSPI/WTI/韩国半导体
  - 中国货币网 chinamoney：美元中间价
  - 东方财富 push2his：两市成交额历史（带重试；失败则该小节显示占位）
所有解析函数为纯函数，便于单元测试（不访问网络）。
"""
import re
import threading
import time
from datetime import date, datetime, time as dtime, timedelta, timezone

try:
    import requests
except ImportError:  # 纯逻辑测试环境
    requests = None

UA = ("Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36")

SINA_HQ = "https://hq.sinajs.cn/list="
SINA_HS300 = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
              "Market_Center.getHQNodeData")
SINA_GLOBAL_KLINE = ("https://stock2.finance.sina.com.cn/futures/api/jsonp.php/"
                     "var%20_=/GlobalFuturesService.getGlobalFuturesDailyKLine")
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/"
CHINAMONEY_CCPR = "https://www.chinamoney.com.cn/ags/ms/cm-u-bk-ccpr/CcprHisNew"
EM_KLINE = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
# 乐咕乐股：沪深300市盈率(TTM)中位数（用户指定数据源）
LEGULEGU_HS300 = "https://legulegu.com/stockdata/hs300-ttm-lyr"

# 本日实时：新浪批量代码（同一请求）
SINA_LIVE_CODES = [
    ("sh000001", "上证指数", "cn"),
    ("sh000510", "中证A500", "cn"),
    ("sh000852", "中证1000", "cn"),
    ("sh000300", "沪深300", "cn"),
    ("sz399001", "深证成指", "cn"),      # 仅用于两市成交额合计
    ("rt_hkHSI", "恒生指数", "hk"),
    ("rt_hkHSTECH", "恒生科技", "hk"),
    ("hf_XAU", "伦敦金", "gold"),
    ("nf_AU0", "沪金", "fut"),
]
# 本日实时：Yahoo 代码（韩国KOSPI / 日经）
YAHOO_LIVE = [
    ("^KS11", "韩国KOSPI"),
    ("^N225", "日经225"),
]

# 历史：Yahoo 代码（仅保留无其他免费源的：韩国KOSPI/日经/韩国半导体）
YAHOO_HISTORY = [
    ("005930.KS", "三星电子", "krw"),
    ("000660.KS", "SK海力士", "krw"),
]

TOTAL_TRADE_MINUTES = 240.0          # 9:30-11:30 + 13:00-15:00
SESSION_START = (9, 30)
SESSION_END = (15, 0)
REFRESH_TTL = 90                     # 页面切换刷新冷却（秒）


def _cn_now():
    return datetime.now(timezone(timedelta(hours=8)))


def elapsed_trade_minutes(now=None):
    """当日已交易分钟数：开盘前 0，收盘后 240，盘中按当前时刻。"""
    now = now or _cn_now()
    t = now.time()
    if now.weekday() >= 5 or t < dtime(*SESSION_START):
        return 0.0
    if t >= dtime(*SESSION_END):
        return TOTAL_TRADE_MINUTES
    if t <= dtime(11, 30):
        return (t.hour * 60 + t.minute) - (SESSION_START[0] * 60 + SESSION_START[1])
    return 120.0 + (t.hour * 60 + t.minute) - (13 * 60)


def predict_turnover(amount_yuan, now=None):
    """本日预测成交额（元）：amount / 已交易分钟 * 全天分钟；未开盘返回 None。"""
    el = elapsed_trade_minutes(now)
    if el <= 0 or not amount_yuan or amount_yuan <= 0:
        return None
    return amount_yuan / el * TOTAL_TRADE_MINUTES


# --------------------------------------------------------------------------
# 纯解析函数
# --------------------------------------------------------------------------

def parse_sina_hq(text):
    """解析新浪 hq.sinajs.cn 批量响应 → {code: {"name","price","pct"}}。

    新浪 hq 全部为逗号分隔，按代码类型取字段：
      - A股/指数 sh000001 等：0=名称 2=昨收 3=现价
      - 港股指数 rt_：1=名称 3=昨收 4=现价 8=涨跌幅%
      - 伦敦金 hf_XAU：0=现价 1=昨收 4=最高 5=最低 13=名称
      - 沪金期货 nf_AU0：0=名称 8=现价 10=昨结算(备选5)
    解析失败的项目跳过。
    """
    out = {}
    for m in re.finditer(r'var hq_str_([A-Za-z0-9_$]+)="([^"]*)"', text):
        code, body = m.group(1), m.group(2)
        if not body:
            continue
        try:
            f = body.split(",")
            if code == "hf_XAU":
                price = _f(f[0])
                prev = _f(f[1]) if len(f) > 1 else 0.0
                name = f[13] if len(f) > 13 and f[13] else code
                pct = (price - prev) / prev * 100.0 if prev > 0 else 0.0
            elif code == "nf_AU0":
                price = _f(f[8]) if len(f) > 8 else 0.0
                prev = _f(f[10]) if len(f) > 10 and _f(f[10]) else (
                    _f(f[5]) if len(f) > 5 else 0.0)
                name = f[0] if f[0] else code
                pct = (price - prev) / prev * 100.0 if prev > 0 else 0.0
            elif code.startswith("rt_"):
                name = f[1] if len(f) > 1 and f[1] else code
                price = _f(f[4]) if len(f) > 4 else 0.0
                pct = _f(f[8]) if len(f) > 8 else 0.0
            else:
                name = f[0] if f[0] else code
                price = _f(f[3]) if len(f) > 3 else 0.0
                prev = _f(f[2]) if len(f) > 2 else 0.0
                pct = (price - prev) / prev * 100.0 if prev > 0 else 0.0
            if price > 0:
                out[code] = {"name": name, "price": price, "pct": pct}
        except Exception:
            continue
    return out


def parse_sina_hq_amount(text):
    """从新浪 hq 响应提取指数当日成交额（元）：A股指数 idx9。"""
    amounts = {}
    for m in re.finditer(r'var hq_str_([A-Za-z0-9_$]+)="([^"]*)"', text):
        code, body = m.group(1), m.group(2)
        if not body or code.startswith("rt_") or code in ("hf_XAU", "nf_AU0"):
            continue
        f = body.split(",")
        if len(f) > 9:
            v = _f(f[9])
            if v > 0:
                amounts[code] = v
    return amounts


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def parse_sina_hs300(text):
    """解析新浪沪深300成分 JSON 列表 → 价格列表。"""
    import json
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []
    prices = []
    try:
        arr = json.loads(m.group(0))
        for item in arr:
            if isinstance(item, dict):
                v = _f(item.get("trade"))
                if v > 0:
                    prices.append(v)
    except Exception:
        return []
    return prices


def median_price(prices):
    """价格中位数；空列表返回 None。"""
    if not prices:
        return None
    s = sorted(prices)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


def parse_legulegu_median_pe(text):
    """解析乐咕乐股 hs300-ttm-lyr 页面 → 沪深300市盈率(TTM)中位数（float）。"""
    m = re.search(r"市盈率\(TTM\)中位数</td>\s*<td>([\d.]+)</td>", text)
    if m:
        v = _f(m.group(1))
        return v if v > 0 else None
    return None


def parse_sina_global_kline(text, n=5):
    """解析新浪国际期货日K JSONP → 最近 n 个交易日的 [(date, close)]。"""
    import json
    m = re.search(r"\((\[.*\])\)", text, re.S)
    if not m:
        return []
    try:
        arr = json.loads(m.group(1))
    except Exception:
        return []
    out = []
    for x in arr:
        if isinstance(x, dict):
            d = str(x.get("date", ""))[:10]
            c = _f(x.get("close"))
            if d and c > 0:
                out.append((d, c))
    return out[-n:]


def parse_yahoo_chart(text):
    """解析 Yahoo chart JSON → (price, [(date, close)...])。"""
    import json
    d = json.loads(text)
    res = d["chart"]["result"][0]
    meta = res.get("meta", {})
    price = _f(meta.get("regularMarketPrice"))
    closes = res["indicators"]["quote"][0].get("close", [])
    ts = res.get("timestamp", [])
    out = []
    for t, c in zip(ts, closes):
        if c is None:
            continue
        d = datetime.fromtimestamp(t, timezone.utc)
        out.append((d.strftime("%m-%d"), float(c)))
    return price, out[-5:]


def parse_chinamoney(text):
    """解析中国货币网中间价 → [(date, usdcny)] 最近 5 日。

    结构：{"data": {"head": [...,"USD/CNY",...], ...},
           "records": [{"date": "...", "values": [按 head 顺序], ...}, ...]}
    """
    import json
    d = json.loads(text)
    head = (d.get("data") or {}).get("head") or []
    records = d.get("records") or []
    if "USD/CNY" not in head:
        return []
    idx = head.index("USD/CNY")
    out = []
    for rec in records:
        day = str(rec.get("date", ""))[:10]
        vals = rec.get("values") or []
        if len(vals) > idx:
            v = _f(vals[idx])
            if v > 0 and day:
                out.append((day, v))
    # 取最近 5 个交易日（records 通常倒序，这里显式排序）
    out.sort(key=lambda x: x[0], reverse=True)
    return list(reversed(out[:5]))


def parse_em_kline(text):
    """解析东方财富 K 线 → [(date, vol, amount_yuan)]。"""
    import json
    d = json.loads(text)
    kl = (d.get("data") or {}).get("klines") or []
    out = []
    for k in kl:
        p = k.split(",")
        if len(p) >= 7:
            out.append((p[0], _f(p[5]), _f(p[6])))
    return out


# --------------------------------------------------------------------------
# 网络获取（带重试与节流）
# --------------------------------------------------------------------------

def _session():
    if requests is None:
        raise RuntimeError("缺少 requests 库")
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    return s


def _get_text(sess, url, params=None, headers=None, tries=2, pause=0.8):
    """带重试的 GET；HTTP 429（限流）时退避更久。"""
    last = None
    for i in range(tries):
        try:
            r = sess.get(url, params=params, headers=headers, timeout=12)
            if r.status_code == 429:
                last = RuntimeError("429 Too Many Requests")
                time.sleep(pause * 4)
                continue
            r.raise_for_status()
            return r.text
        except Exception as e:  # noqa: BLE001
            last = e
            if i < tries - 1:
                time.sleep(pause)
    raise last


def _pacing(prev, gap=0.25):
    """请求间节流：距上次至少 gap 秒。"""
    now = time.monotonic()
    gap = gap - (now - prev)
    if gap > 0:
        time.sleep(gap)
    return time.monotonic()


# --------------------------------------------------------------------------
# 小节抓取（并行化：每节独立会话/节流，供大盘页渐进填充）
# --------------------------------------------------------------------------

def _sec_live_sina():
    """实时①：新浪批量行情 + 两市成交额 + 本日预测额。"""
    sess = _session()
    data = {"quotes": [], "errors": []}
    try:
        codes = ",".join(c for c, _n, _t in SINA_LIVE_CODES)
        text = _get_text(sess, SINA_HQ + codes,
                         headers={"Referer": "https://finance.sina.com.cn/"})
        quotes = parse_sina_hq(text)
        amounts = parse_sina_hq_amount(text)
        for code, label, _t in SINA_LIVE_CODES:
            if code == "sz399001":
                continue
            q = quotes.get(code)
            if q:
                data["quotes"].append(
                    {"name": label, "price": q["price"], "pct": q["pct"], "src": "新浪"})
            else:
                data["errors"].append("%s 无行情" % label)
        sh = amounts.get("sh000001")
        sz = amounts.get("sz399001")
        if sh and sz:
            total = sh + sz
            data["turnover_yi"] = round(total / 1e8, 2)
            pred = predict_turnover(total)
            data["turnover_pred_yi"] = round(pred / 1e8, 2) if pred else None
        data["sources"] = {"新浪": True}
    except Exception as e:  # noqa: BLE001
        data["errors"].append("新浪行情：%s" % e)
    return data


def _sec_live_yahoo():
    """实时②：韩国KOSPI / 日经225（Yahoo，限流退避）。"""
    sess = _session()
    data = {"quotes": [], "errors": []}
    last = time.monotonic()
    for code, label in YAHOO_LIVE:
        last = _pacing(last, 1.5)
        try:
            text = _get_text(sess, YAHOO_CHART + code,
                             params={"range": "5d", "interval": "1d"},
                             tries=3, pause=1.2)
            price, _hist = parse_yahoo_chart(text)
            pct = 0.0
            if len(_hist) >= 2:
                pct = (_hist[-1][1] - _hist[-2][1]) / _hist[-2][1] * 100.0
            data["quotes"].append(
                {"name": label, "price": price, "pct": pct, "src": "Yahoo"})
            data["sources"] = {"Yahoo": True}
        except Exception as e:  # noqa: BLE001
            data["errors"].append("%s：%s" % (label, e))
    return data


def _sec_live_median():
    """实时③：沪深300中位数（新浪成分 3 页）+ 乐咕乐股中位数PE(TTM)。"""
    sess = _session()
    data = {"errors": []}
    last = time.monotonic()
    prices = []
    try:
        for page in (1, 2, 3):
            text = _get_text(sess, SINA_HS300, params={
                "page": page, "num": 100, "sort": "symbol", "asc": 1,
                "node": "hs300", "symbol": "", "_s_r_a": "page"},
                headers={"Referer": "https://finance.sina.com.cn/"})
            prices += parse_sina_hs300(text)
            if len(prices) < page * 100:
                break
            last = _pacing(last)
        data["csi300_median"] = median_price(prices)
    except Exception as e:  # noqa: BLE001
        data["errors"].append("沪深300成分：%s" % e)
    last = _pacing(last)
    try:
        text = _get_text(sess, LEGULEGU_HS300, tries=2, pause=1.0)
        data["hs300_median_pe"] = parse_legulegu_median_pe(text)
        data["sources"] = {"乐咕乐股": True}
    except Exception as e:  # noqa: BLE001
        data["errors"].append("乐咕乐股：%s" % e)
    return data


def _sec_hist_turnover():
    """历史①：两市成交额 5 日（东方财富，重试）。"""
    sess = _session()
    data = {"errors": []}
    try:
        em_days = {}
        last = time.monotonic()
        for secid in ("1.000001", "0.399001"):
            text = _get_text(sess, EM_KLINE, params={
                "secid": secid, "fields1": "f1,f2,f3",
                "fields2": "f51,f52,f53,f54,f55,f56,f57",
                "klt": 101, "fqt": 1,
                "beg": (_cn_now() - timedelta(days=10)).strftime("%Y%m%d"),
                "end": (_cn_now() + timedelta(days=1)).strftime("%Y%m%d")},
                tries=3, pause=1.0)
            for day, _v, amt in parse_em_kline(text):
                em_days[day] = em_days.get(day, 0.0) + amt
            last = _pacing(last)
        data["turnover"] = [
            (day, round(em_days[day] / 1e8, 2)) for day in sorted(em_days)[-5:]]
    except Exception as e:  # noqa: BLE001
        data["errors"].append("两市成交额历史：%s" % e)
    return data


def _sec_hist_ccpr():
    """历史②：美元兑人民币中间价 5 日（中国货币网）。"""
    sess = _session()
    data = {"errors": []}
    try:
        end = _cn_now().date()
        text = _get_text(sess, CHINAMONEY_CCPR, params={
            "startDate": (end - timedelta(days=10)).strftime("%Y-%m-%d"),
            "endDate": end.strftime("%Y-%m-%d")},
            headers={"Referer": "https://www.chinamoney.com.cn/chinese/bkccpr/"})
        data["ccpr"] = parse_chinamoney(text)
        data["sources"] = {"中国货币网": True}
    except Exception as e:  # noqa: BLE001
        data["errors"].append("中间价：%s" % e)
    return data


def _sec_hist_xau():
    """历史③：伦敦金 5 日（新浪国际期货日K）。"""
    sess = _session()
    data = {"errors": []}
    try:
        text = _get_text(sess, SINA_GLOBAL_KLINE, params={"symbol": "XAU"},
                         headers={"Referer": "https://finance.sina.com.cn/"})
        data["xau"] = parse_sina_global_kline(text)
        data["sources"] = {"新浪": True}
    except Exception as e:  # noqa: BLE001
        data["errors"].append("伦敦金历史：%s" % e)
    return data


def _sec_hist_wti():
    """历史③b：WTI 5 日（新浪国际期货日K）。"""
    sess = _session()
    data = {"errors": []}
    try:
        text = _get_text(sess, SINA_GLOBAL_KLINE, params={"symbol": "CL"},
                         headers={"Referer": "https://finance.sina.com.cn/"})
        data["wti"] = parse_sina_global_kline(text)
        data["sources"] = {"新浪": True}
    except Exception as e:  # noqa: BLE001
        data["errors"].append("WTI历史：%s" % e)
    return data


def _sec_hist_kr():
    """历史④：韩国半导体（三星电子 + SK海力士，Yahoo）。"""
    sess = _session()
    data = {"kr": {}, "errors": []}
    last = time.monotonic()
    for code, label, unit in YAHOO_HISTORY:
        last = _pacing(last, 1.5)
        try:
            text = _get_text(sess, YAHOO_CHART + code,
                             params={"range": "5d", "interval": "1d"},
                             tries=3, pause=1.2)
            _price, hist = parse_yahoo_chart(text)
            data["kr"][label] = hist
            data["sources"] = {"Yahoo": True}
        except Exception as e:  # noqa: BLE001
            data["errors"].append("%s：%s" % (label, e))
    return data


_SECTIONS = [
    ("live_sina", _sec_live_sina),
    ("live_yahoo", _sec_live_yahoo),
    ("live_median", _sec_live_median),
    ("hist_turnover", _sec_hist_turnover),
    ("hist_ccpr", _sec_hist_ccpr),
    ("hist_xau", _sec_hist_xau),
    ("hist_wti", _sec_hist_wti),
    ("hist_kr", _sec_hist_kr),
]

_LIVE_KEYS = {"live_sina", "live_yahoo", "live_median"}
_HIST_KEYS = {"hist_turnover", "hist_ccpr", "hist_xau", "hist_wti", "hist_kr"}


def _merge_section(out, key, data):
    """把单节结果合并进大盘页完整结构。"""
    live, hist = out["live"], out["history"]
    data = data or {}
    if key == "live_sina":
        live["quotes"].extend(data.get("quotes", []))
        if data.get("turnover_yi") is not None:
            live["turnover_yi"] = data["turnover_yi"]
        if data.get("turnover_pred_yi") is not None:
            live["turnover_pred_yi"] = data["turnover_pred_yi"]
    elif key == "live_yahoo":
        live["quotes"].extend(data.get("quotes", []))
    elif key == "live_median":
        live["csi300_median"] = data.get("csi300_median")
        live["hs300_median_pe"] = data.get("hs300_median_pe")
    elif key == "hist_turnover":
        hist["turnover"] = data.get("turnover", [])
    elif key == "hist_ccpr":
        hist["ccpr"] = data.get("ccpr", [])
    elif key == "hist_xau":
        hist["xau"] = data.get("xau", [])
    elif key == "hist_wti":
        hist["wti"] = data.get("wti", [])
    elif key == "hist_kr":
        hist["kr"] = data.get("kr", {})
    for e in data.get("errors", []):
        (live["errors"] if key in _LIVE_KEYS else hist["errors"]).append(e)
    for s, v in (data.get("sources") or {}).items():
        out["sources"][s] = v


def _new_state():
    return {
        "ok": True, "ts": _cn_now().strftime("%H:%M:%S"), "sources": {},
        "live": {"quotes": [], "turnover_yi": None, "turnover_pred_yi": None,
                 "csi300_median": None, "hs300_median_pe": None, "errors": []},
        "history": {"turnover": [], "ccpr": [], "wti": [], "xau": [],
                    "kr": {}, "errors": []},
    }


def refresh_market_progressive(on_section, on_done=None):
    """并行抓取各小节，每节完成后回调 on_section(key, data)。

    data 为小节字典（含 errors/sources）；全部完成后回调 on_done(完整 dict)。
    """
    results = {}

    def run(key, fn):
        try:
            data = fn()
        except Exception as e:  # noqa: BLE001
            data = {"errors": [str(e)]}
        results[key] = data
        try:
            on_section(key, data)
        except Exception:  # noqa: BLE001
            pass

    threads = [threading.Thread(target=run, args=(k, f), daemon=True)
               for k, f in _SECTIONS]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    out = _new_state()
    for k in _SECTIONS:
        _merge_section(out, k[0], results.get(k[0]))
    if on_done:
        try:
            on_done(out)
        except Exception:  # noqa: BLE001
            pass
    return out


def refresh_market():
    """刷新大盘信息（并行小节后合并，返回完整 dict）。"""
    return refresh_market_progressive(lambda k, d: None)
