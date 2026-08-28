# -*- coding: utf-8 -*-
"""大盘信息数据模块（牛票 Nstock）。

需求：
一、本日实时（页面切换前自动刷新，不做高频轮询，避免触发反爬）
  1. A股成交总金额（沪深两市）、本日预测额（按已交易时长线性外推）
  2. 上证 / 中证A500 / 中证1000 / 沪深300 / 深证成指 / 恒生 / 恒生科技 / 伦敦金 / 沪金
  3. 沪深300成分股价格中位数
二、历史（近 5 个交易日）
  1. A股成交总金额  2. 美元兑人民币中间价  3. WTI原油  4. 伦敦金

数据源（低请求量、批量合并、请求间隔节流）：
  - 新浪 hq.sinajs.cn：A股/港股指数、伦敦金、沪金 —— 1 个批量请求
  - 新浪成分股接口：沪深300成分价格（3 页）
  - 新浪国际期货日K：伦敦金历史
  - 中国货币网 chinamoney：美元中间价
  - 腾讯 day/query：两市成交额历史（当日分时末条累计成交额；东方财富 push2his 兜底）
所有解析函数为纯函数，便于单元测试（不访问网络）。
"""
import os
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
# 新浪财经 7x24 快讯（zhibo feed：rich_text=消息主题全文，docurl=详情链接）——
# "本周重大关注"数据源（需求：直接显示消息主题，不点链接也能看到内容）
SINA_7X24 = "https://zhibo.sina.com.cn/api/zhibo/feed"
# 新浪财经要闻（滚动列表，备选源）
SINA_ROLL_NEWS = "https://feed.mix.sina.com.cn/api/roll/get"
CHINAMONEY_CCPR = "https://www.chinamoney.com.cn/ags/ms/cm-u-bk-ccpr/CcprHisNew"
EM_KLINE = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
# 腾讯当日分时（day/query）：每交易日末累计成交额(元)，含指数/ETF/个股 —— 两市成交额历史主源
TX_DAY_QUERY = "https://web.ifzq.gtimg.cn/appstock/app/day/query"
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

# 历史：韩国KOSPI/日经/韩国半导体依赖 Yahoo，手机网络不可达（429/超时），
# 按需求删除（免费源查不到即去掉），不再请求。

TOTAL_TRADE_MINUTES = 240.0          # 9:30-11:30 + 13:00-15:00
SESSION_START = (9, 30)
SESSION_END = (15, 0)
REFRESH_TTL = 90                     # 页面切换刷新冷却（秒）


def _cn_now():
    return datetime.now(timezone(timedelta(hours=8)))


def elapsed_trade_minutes(now=None):
    """当日已交易分钟数：开盘前 0，收盘后 240，盘中按当前时刻。

    修复：11:30-13:00 午休返回 120（上午已结束），否则午休期间会落入
    下午分支算出错误分钟数（如 11:34 算出 34 分钟 → 预测额严重虚高）。
    """
    now = now or _cn_now()
    t = now.time()
    if now.weekday() >= 5 or t < dtime(*SESSION_START):
        return 0.0
    if t >= dtime(*SESSION_END):
        return TOTAL_TRADE_MINUTES
    if t <= dtime(11, 30):
        return (t.hour * 60 + t.minute) - (SESSION_START[0] * 60 + SESSION_START[1])
    if t <= dtime(13, 0):   # 午休（11:30-13:00）返回 120：上午已结束
        return 120.0
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


# ---- 本周关注：预告类关键词 + 重大性评分（需求：千亿级以上重大事件，非普通新股）----
# 预告类（"即将发生"）：命中即可入选候选
WEEK_NEWS_PREVIEW = (
    "本周", "下周", "今日", "明日", "将公布", "即将", "将于", "举行", "召开",
    "会议", "决议", "休市", "财报", "业绩预告", "CPI", "PCE", "非农",
    "利率决议", "美联储", "央行", "关税", "发布", "公布", "月", "日",
)
# 重大性加分：巨头/千亿级/权重/宏观大事 + 半导体/金融行业重大消息（需求）
WEEK_NEWS_BIG = (
    "千亿", "万亿", "巨头", "权重", "指数", "大盘", "龙头", "苹果", "微软",
    "英伟达", "台积电", "特斯拉", "亚马逊", "谷歌", "Meta", "茅台", "宁德",
    "比亚迪", "中芯", "华为", "阿里", "腾讯", "平安", "工行", "建行", "中石油",
    "中石化", "联通", "移动", "电信", "中国船舶", "中远", "国家", "国务院",
    "证监会", "央行", "财政部", "商务部", "美联储", "欧央行", "日本央行",
    "OPEC", "非农", "CPI", "PCE", "GDP", "IPO", "上市首日",
    # 半导体/金融等行业重大消息（需求：关注影响股市的半导体、金融等）
    "半导体", "芯片", "晶圆", "存储", "光刻", "算力", "AI", "人工智能",
    "券商", "银行", "保险", "基金", "ETF", "北向", "外资", "机构",
    "中概", "恒生", "纳指", "标普", "道指", "上市", "中签",
)
# 减分/剔除：小额新股、小盘、普通上市（无巨头名）
WEEK_NEWS_SMALL = (
    "申购", "发行价", "募资", "募", "元/股", "每股", "首发", "北交所",
    "科创板新股", "创业板新股", "小型", "小盘", "次新股",
)


# 过滤门槛：至少命中一个"重大词(+2)"（或两个预告词）才入选，剔除普通快讯
WEEK_NEWS_MIN_SCORE = 2


def _news_score(text):
    """新闻重大性评分：预告词+1，重大词+2，小额词-3；负数剔除。"""
    s = 0
    for k in WEEK_NEWS_PREVIEW:
        if k in text:
            s += 1
    for k in WEEK_NEWS_BIG:
        if k in text:
            s += 2
    for k in WEEK_NEWS_SMALL:
        if k in text:
            s -= 3
    return s


_NO_BREAK_RE = None


def _no_break_latin(text):
    """在 拉丁字母/数字 与 CJK（含全角标点）边界插入不换行空格(\u00A0)。

    需求：数字、字母后面不要换行（Kivy 在 CJK↔Latin 边界可断行，且
    拉丁后接全角标点如"ETF）"也常被断行）。\u00A0 显示为普通空格宽度，
    但 Kivy 不会在它处断行。
    """
    global _NO_BREAK_RE
    if _NO_BREAK_RE is None:
        # 正向：拉丁/数字/符号 后接 汉字或全角标点 → 插 \u00A0
        #   （"ETF）"、"10%，" 等边界防断行；\u00A0 显示为空格宽度）
        _NO_BREAK_RE = re.compile(
            r"([A-Za-z0-9%.\-+,./$¥:;])\s*([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef])")
    out = _NO_BREAK_RE.sub(lambda m: m.group(1) + "\u00A0" + m.group(2), text or "")
    # 反向：汉字/全角标点 后紧跟 拉丁/数字（"指数ETF"、"：2026"）防断行
    _NO_BREAK_RE2 = re.compile(
        r"([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef])\s*([A-Za-z0-9%])")
    out = _NO_BREAK_RE2.sub(lambda m: m.group(1) + "\u00A0" + m.group(2), out)
    return out


def parse_sina_7x24(text, n=10):
    """解析新浪 7x24 快讯 → 最近 n 条 [(时间, 主题, 详情链接)]。

    feed 按时间倒序（最新在前）。需求：最新消息 10 条、只标题展示；
    过滤：评分>0（重大消息：半导体/金融/千亿级/宏观大事），剔除小额新股；
    保持时间倒序（不按评分重排），取前 n 条。
    """
    import json
    try:
        d = json.loads(text)
        feed = d["result"]["data"]["feed"]
        items = feed.get("list") if isinstance(feed, dict) else []
    except Exception:
        return []
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        ct = str(it.get("create_time") or "")[:16]
        rt = str(it.get("rich_text") or "").strip()
        if not rt:
            continue
        if _news_score(rt) < WEEK_NEWS_MIN_SCORE:
            continue
        out.append((ct, rt, str(it.get("docurl") or "")))
        if len(out) >= n:
            break
    return out


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
    """实时①：新浪批量行情 + 两市成交额 + 本日预测额 + 较上日同时段变化。"""
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
            pred = _predict_turnover_model_or_linear(total)
            data["turnover_pred_yi"] = round(pred / 1e8, 2) if pred else None
            # 较上日变化：今日成交额 - 上一交易日同时段累计成交额（需求）
            data["turnover_vs_prev"] = _turnover_vs_prev_yi(total)
        data["sources"] = {"新浪": True}
    except Exception as e:  # noqa: BLE001
        data["errors"].append("新浪行情：%s" % e)
    return data


def _turnover_vs_prev_yi(amount_yuan):
    """较上一交易日同时段变化（亿元）：今日累计成交额 - 上一交易日同一分钟累计成交额。

    用腾讯 day/query 上一交易日分时曲线，按当前已交易分钟取累计值；
    数据不足返回 None。
    """
    try:
        el = elapsed_trade_minutes()
        if el <= 0:
            return None
        prev = None
        curves = _tx_intraday_curves(5)
        days = sorted(curves.keys())
        if not days:
            return None
        prev_day = days[-1]
        pts = curves[prev_day]
        prev_cum = None
        for m, cum in pts:
            if m <= el:
                prev_cum = cum
            else:
                break
        if prev_cum:
            prev = round((amount_yuan - prev_cum) / 1e8, 2)
        return prev
    except Exception:  # noqa: BLE001
        return None


def _predict_turnover_model_or_linear(total):
    """本日预测成交额：优先历史分时占比模型，失败/过早回退线性外推。

    需求：开盘初期纯线性外推会严重夸大（如 9:47 预测 6 万亿），
    改用近 5 个交易日分时占比曲线（历史 + 实时动态）。
    """
    try:
        curves = _tx_intraday_curves(5)
        profile, avg_daily = build_turnover_profile(curves)
        pred = predict_turnover_model(total, profile, avg_daily)
        if pred:
            return pred
    except Exception:  # noqa: BLE001（模型构建失败 → 回退线性）
        pass
    return predict_turnover(total)


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


def _tx_day_query_raw(symbol, n=5):
    """腾讯 day/query：返回 [(date8, [分钟串...])]，最近 n 个交易日（升序）。"""
    sess = _session()
    url = TX_DAY_QUERY + "?code=" + symbol
    text = _get_text(sess, url, tries=2, pause=1.0)
    import json
    data = json.loads(text)
    blk = data["data"][symbol]
    out = []
    for day in blk.get("data", []):
        d = str(day.get("date", ""))
        recs = day.get("data") or []
        if recs:
            out.append((d, recs))
    return out[-n:]


def _tx_day_query_amount(symbol, n=5):
    """腾讯 day/query：返回 [(date, amount_yuan)]，最近 n 个交易日（升序）。

    每交易日分时最后一条的累计成交额即当日成交额(元)，对指数/ETF/个股均有效。
    """
    out = []
    for d, recs in _tx_day_query_raw(symbol, n):
        last = recs[-1].split()
        if len(last) >= 4:
            out.append(("%s-%s-%s" % (d[:4], d[4:6], d[6:8]), float(last[3])))
    return out


def _minute_elapsed(hhmm):
    """HHMM → 距 9:30 的已交易分钟数（剔除午休；如 0930→0，1130→120，1500→240）。"""
    t = (hhmm // 100) * 60 + (hhmm % 100)
    if t <= 11 * 60 + 30:
        return t - (9 * 60 + 30)
    if t >= 13 * 60:
        return 120 + t - (13 * 60)
    return 120


def _tx_intraday_curves(n=5):
    """沪深两市各交易日分时累计成交额曲线（两市逐分钟求和）。

    返回 {date8: [(elapsed_min, 两市累计成交额(元)), ...]}（升序），
    用于构建"当日已完成占比"预测模型；剔除当日未完成的今天。
    注意：腾讯分时含午休回显（1300 与 1130 累计相同），同分钟只取一次。
    """
    sess = _session()
    per_sym = {}   # sym -> {date8: {elapsed: cum}}
    today = _cn_now().strftime("%Y%m%d")
    last = time.monotonic()
    for sym in ("sh000001", "sz399001"):
        m = {}
        for d, recs in _tx_day_query_raw(sym, n):
            if d >= today:
                continue
            dd = m.setdefault(d, {})
            for r in recs:
                parts = r.split()
                if len(parts) >= 4:
                    el = _minute_elapsed(int(parts[0][:4]))
                    # 同分钟重复（午休回显等）取最大累计值
                    dd[el] = max(dd.get(el, 0.0), float(parts[3]))
        per_sym[sym] = m
        last = _pacing(last)
    dates = set()
    for m in per_sym.values():
        dates.update(m.keys())
    out = {}
    for d in dates:
        sums = {}
        for m in per_sym.values():
            dd = m.get(d)
            if not dd:
                continue
            for el, cum in dd.items():
                sums[el] = sums.get(el, 0.0) + cum
        out[d] = sorted(sums.items())
    return out


def build_turnover_profile(curves):
    """由历史分时曲线构建预测模型。

    curves: {date: [(elapsed, cum)]} → 返回 (profile, avg_daily)：
      profile = {elapsed: 当日已完成占比均值}（fraction = 累计/全天最终）
      avg_daily = 历史日均全天成交额(元)
    数据不足返回 ({}, 0)。
    """
    fracs = {}
    finals = []
    for _d, pts in curves.items():
        if not pts:
            continue
        final = pts[-1][1]
        if final <= 0:
            continue
        finals.append(final)
        for el, cum in pts:
            if cum > 0:
                fracs.setdefault(el, []).append(cum / final)
    profile = {el: sum(v) / len(v) for el, v in fracs.items()}
    avg_daily = sum(finals) / len(finals) if finals else 0.0
    return profile, avg_daily


def predict_turnover_model(amount_yuan, profile, avg_daily, now=None,
                           min_elapsed=15, min_frac=0.04):
    """用"历史分时占比"模型预测全日成交额（元）。

    核心：当日某时刻成交额 ÷ 该时刻历史平均已完成占比 = 全日预估。
    较纯时间线性外推更稳（开盘急拉时段占比曲线陡，不会被夸大）；
    开盘过短 / 数据不足 / 占比异常 → 返回 None（界面显示"—"）。
    """
    import bisect
    el = elapsed_trade_minutes(now)
    if el < min_elapsed or amount_yuan <= 0 or not profile or avg_daily <= 0:
        return None
    keys = sorted(profile)
    if el <= keys[0]:
        f = profile[keys[0]]
    elif el >= keys[-1]:
        f = profile[keys[-1]]
    else:
        i = bisect.bisect_left(keys, el)
        k0, k1 = keys[i - 1], keys[i]
        f = profile[k0] + (profile[k1] - profile[k0]) * (el - k0) / (k1 - k0)
    if not (min_frac <= f <= 1.0):
        return None
    pred = amount_yuan / f
    # 防发散：明显偏离历史日均范围（[0.3, 3.0] 倍）视为数据异常，不预测
    lo, hi = avg_daily * 0.3, avg_daily * 3.0
    if not (lo <= pred <= hi):
        return None
    return pred


def _sec_hist_turnover():
    """历史①：两市成交额 5 日（腾讯 day/query 主 → 东方财富兜底）。

    实测（2026-08-24）：上证 9520亿 + 深证 10554亿 ≈ 2.0万亿，与实时口径一致。
    """
    sess = _session()
    data = {"errors": []}
    try:
        days = {}
        last = time.monotonic()
        for sym in ("sh000001", "sz399001"):
            for d, amt in _tx_day_query_amount(sym, 5):
                days[d] = days.get(d, 0.0) + amt
            last = _pacing(last)
        if days:
            data["turnover"] = [
                (d, round(days[d] / 1e8, 2)) for d in sorted(days)[-5:]]
            data["sources"] = {"腾讯": True}
        else:
            raise RuntimeError("腾讯无数据")
    except Exception as e:  # noqa: BLE001
        data["errors"].append("两市成交额历史(腾讯)：%s" % e)
        # 兜底：东方财富 push2his（sh000001 + sz399001 日K 成交额合计）
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
            if em_days:
                data["turnover"] = [
                    (day, round(em_days[day] / 1e8, 2)) for day in sorted(em_days)[-5:]]
                data["sources"] = {"东方财富": True}
                data["errors"] = []   # 兜底成功则清除错误
        except Exception as e2:  # noqa: BLE001
            data["errors"].append("两市成交额历史(东财)：%s" % e2)
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


def _sec_week_news():
    """四、本周重大关注：新浪 7x24 快讯 ≤5 条（主题全文 + 隐式链接）。

    多抓 60 条，优先筛"即将/本周/公布/上市/会议"等预告类消息（需求）。
    """
    sess = _session()
    data = {"errors": []}
    try:
        text = _get_text(sess, SINA_7X24, params={
            "page": "1", "page_size": "60", "zhibo_id": "152",
            "tag_id": "0", "dire": "f", "dpc": "1"},
            headers={"Referer": "https://finance.sina.com.cn/"})
        data["news"] = parse_sina_7x24(text)
        data["sources"] = {"新浪": True}
    except Exception as e:  # noqa: BLE001
        data["errors"].append("本周关注：%s" % e)
    return data


def _sec_hist_btc():
    """历史⑤：比特币近 5 日（MEXC；不可达时留空，UI 显示说明行）。"""
    sess = _session()
    data = {"errors": []}
    try:
        text = _get_text(sess, MEXC_KLINE, params={
            "symbol": "BTCUSDT", "interval": "1d", "limit": "10"},
            tries=2, pause=0.6)
        data["btc"] = parse_mexc_kline(text, 5)
        data["sources"] = {"MEXC": True}
    except Exception as e:  # noqa: BLE001
        data["errors"].append("比特币：%s" % e)
    return data


_SECTIONS = [
    ("live_sina", _sec_live_sina),
    ("live_median", _sec_live_median),
    ("hist_turnover", _sec_hist_turnover),
    ("hist_ccpr", _sec_hist_ccpr),
    ("hist_xau", _sec_hist_xau),
    ("hist_wti", _sec_hist_wti),
    ("hist_btc", _sec_hist_btc),
    ("week_news", _sec_week_news),
]

_LIVE_KEYS = {"live_sina", "live_median"}
_HIST_KEYS = {"hist_turnover", "hist_ccpr", "hist_xau", "hist_wti"}


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
        if data.get("turnover_vs_prev") is not None:
            live["turnover_vs_prev"] = data["turnover_vs_prev"]
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
    elif key == "hist_btc":
        hist["btc"] = data.get("btc", [])
    elif key == "week_news":
        hist["news"] = data.get("news", [])
    for e in data.get("errors", []):
        (live["errors"] if key in _LIVE_KEYS else hist["errors"]).append(e)
    for s, v in (data.get("sources") or {}).items():
        out["sources"][s] = v


def _new_state():
    return {
        "ok": True, "ts": _cn_now().strftime("%H:%M:%S"), "sources": {},
        "live": {"quotes": [], "turnover_yi": None, "turnover_pred_yi": None,
                 "turnover_vs_prev": None,
                 "csi300_median": None, "hs300_median_pe": None, "errors": []},
        "history": {"turnover": [], "ccpr": [], "wti": [], "xau": [], "btc": [],
                    "news": [], "errors": []},
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


# ==========================================================================
# 宏观数据（近 12 个月）—— 「宏观数据」tab
#   数据源（全部国内可达、低请求量）：
#     - 国家统计局新站 esData：PMI 及细分、PPIRM、不变价GDP当季值（普通 POST 即可，
#       无需 curl_cffi 指纹伪装）
#     - 东方财富 datacenter-web：CPI/PPI（月度）、M1/M2、新增人民币贷款、
#       中美国债收益率（日）、LPR（月度）、新房价格（月度）、美国关键指标发布日历
#     - 商务部数据：社会融资规模增量（月度）
#     - MEXC：比特币日K（币安/OKX/火币在本网络不可达）
#     - 新浪国际期货日K：伦敦金/WTI（复用）
#     - 金十 datacenter：美国核心PCE年率（免费层滞后，标注数据月份）
# ==========================================================================

EM_DC = "https://datacenter-web.eastmoney.com/api/data/v1/get"
EM_TOKEN = "894050c76af8597a853f5b408b759f5d"
NBS_ESDATA = "https://data.stats.gov.cn/dg/website/publicrelease/web/external/stream/esData"
NBS_REF = "https://data.stats.gov.cn/dg/website/page.html#/pc/national/monthData"
NBS_QREF = "https://data.stats.gov.cn/dg/website/page.html#/pc/national/quarterData"
NBS_ROOT = "fc982599aa684be7969d7b90b1bd0e84"      # 月度数据
NBS_QROOT = "a94b8b7365a94874968cabbe392cf679"     # 季度数据
NBS_PMI_CID = "93ffbb1aa85740d3aa2618371508b606"   # 制造业采购经理指数
NBS_PMI_IDS = [
    ("PMI", "a09aa989bdcf4cffa2021795722eb916"),
    ("生产", "6729aa00f9ed46d8b30c5d2312214b89"),
    ("新订单", "4151df33b53f4d02ae9f51fe402f1a50"),
    ("产成品库存", "48ec2904ba8848cf9488fa99d3731525"),
    ("采购量", "c83954218ae645cf975ed4f66b4a57f2"),
    ("原材料库存", "c149709d0c48422d83a59d4b94d03bbb"),
]
NBS_PPIRM_CID = "50f683df1f8b4da9831b7047d5091571"  # 工业生产者购进价格(上年同月=100)
NBS_PPIRM_IDS = [("PPIRM", "69b783fe106944bea4ae8db4b413acc8")]
NBS_GDP_CID = "b676631776424600bdae363df047559f"    # 国内生产总值(不变价)
NBS_GDP_Q = "b704155cd926437b8ee9c65fe058210d"      # 不变价GDP 当季值(亿元)
MEXC_KLINE = "https://api.mexc.com/api/v3/klines"
JIN10_LIST = "https://datacenter-api.jin10.com/reports/list_v2"
JIN10_H = {"x-app-id": "rU6QIu7JHe2gOUeR", "x-csrf-token": "x-csrf-token", "x-version": "1.0.0"}
MOFCOM_SHRZGM = "https://data.mofcom.gov.cn/datamofcom/front/gnmy/shrzgmQuery"
# 中国人民银行：社会融资规模增量统计表（列表页 → htm 附件 → 表格）
PBC_BASE = "http://www.pbc.gov.cn"
PBC_REF = PBC_BASE + "/diaochatongjisi/"
PBC_SHRZGM = (PBC_BASE +
              "/diaochatongjisi/116219/116319/2026ntjsj/shrzgm/index.html")

MACRO_MONTHS = 12          # 宏观数据展示月份数（需求：近 12 个月）
MACRO_COMMODITY_DAYS = 5   # 大宗商品近 5 日（需求保留）

# 美国关键指标（东财 RPT_ECONOMICVALUE_USA）发布日历展示：INDICATOR_ID 白名单
US_USEFUL = ("EMG00000746", "EMG00000733", "EMG00000771", "EMG00152118",
             "EMG00001039", "EMG00002790", "EMG00002791", "EMG00177897",
             "EMG00177799", "EMG00177909", "EMG00358536", "EMG00342250")
# 美国指标名简化（东财全名过长，两行以上显示怪异，需求）
US_NAME_SHORT = {
    "EMG00358536": "联邦基金利率(下限)",
    "EMG00342250": "联邦基金利率(上限)",
    "EMG00000746": "核心CPI同比",
    "EMG00000733": "CPI同比",
    "EMG00000771": "核心CPI环比",
    "EMG00152118": "非农就业人数",
    "EMG00001039": "失业率",
    "EMG00002790": "ISM制造业PMI",
    "EMG00002791": "ISM服务业PMI",
    "EMG00177897": "PPI环比",
    "EMG00177799": "核心PPI同比",
    "EMG00177909": "核心PPI环比",
}


def _month_key(raw):
    """把 "2026年7月" / "2026年07月" / "202607" / "2026-07" / "2026年第二季度"
    统一为 "2026-07"（季度取季末月 03/06/09/12）。"""
    m = re.search(r"(\d{4})[年\-/](\d{1,2})", str(raw or ""))
    if m:
        return "%s-%s" % (m.group(1), m.group(2).zfill(2))
    q = re.search(r"(\d{4})年(第[一二三四]季度)", str(raw or ""))
    if q:
        return "%s-%s" % (q.group(1),
                          {"一": "03", "二": "06", "三": "09", "四": "12"}[q.group(2)[1]])
    m = re.search(r"(\d{4})(\d{2})", str(raw or ""))
    if m:
        return "%s-%s" % (m.group(1), m.group(2))
    return str(raw or "")


def _month_short(key):
    """"2026-07" → "26-07"。"""
    return key[2:] if len(key) >= 7 else key


def parse_nbs_esdata(text, n=MACRO_MONTHS):
    """解析统计局 esData 响应 → {"months": [升序月份], "series": [[按指标顺序的值]]}。

    esData 返回倒序（未来空值在前），这里取最近 n 个"有值月份"（任一指标非空），
    升序输出；缺值以 None 占位。纯函数，可测试。
    """
    import json
    try:
        d = json.loads(text)
    except Exception:
        return {"months": [], "series": []}
    rows = d.get("data") or []
    picked = []
    for m in rows:
        vals = [((v or {}).get("value") or "") for v in (m.get("values") or [])]
        if any(v for v in vals):
            picked.append((m.get("name", ""), vals))
            if len(picked) >= n:
                break
    picked.reverse()  # 升序
    months = [_month_key(p[0]) for p in picked]
    ncols = max((len(p[1]) for p in picked), default=0)
    series = []
    for i in range(ncols):
        series.append([(_f(p[1][i]) or None) if i < len(p[1]) and p[1][i] else None
                       for p in picked])
    return {"months": months, "series": series}


def parse_em_rows(text):
    """解析东方财富 datacenter 响应 → result.data 列表（空失败返回 []）。"""
    import json
    try:
        d = json.loads(text)
        return (d.get("result") or {}).get("data") or []
    except Exception:
        return []


def parse_mexc_kline(text, n=12):
    """解析 MEXC klines → 最近 n 个交易日 [(date, close)]（升序）。

    MEXC 返回 [[open_time_ms, open, high, low, close, vol, close_time_ms, amount], ...]
    """
    import json
    import datetime
    try:
        arr = json.loads(text)
    except Exception:
        return []
    out = []
    for x in arr:
        try:
            d = datetime.datetime.fromtimestamp(int(x[0]) / 1000.0,
                                                tz=timezone(timedelta(hours=8)))
            c = _f(x[4])
            if c > 0:
                out.append((d.strftime("%Y-%m-%d"), c))
        except Exception:
            continue
    return out[-n:]


def parse_jin10(text):
    """解析金十 reports/list_v2 → 最新一条 {"date": "YYYY-MM-DD", "value", "prev"}。"""
    import json
    try:
        d = json.loads(text)
        vals = (d.get("data") or {}).get("values") or []
    except Exception:
        return None
    for v in vals:
        if len(v) >= 2 and v[1] is not None:
            return {"date": str(v[0])[:10], "value": _f(v[1]),
                    "prev": _f(v[3]) if len(v) > 3 and v[3] is not None else None}
    return None


def parse_mofcom_shrzgm(text, n=MACRO_MONTHS):
    """解析商务部社融增量 → [(month_key, 增量亿元)] 最近 n 期（升序）。

    返回 JSON 数组：[{"date": "202604", "tiosfs": 6245, ...}]，tiosfs=社会融资规模增量。
    """
    import json
    try:
        arr = json.loads(text)
    except Exception:
        return []
    out = []
    for r in arr:
        mk = _month_key(r.get("date", ""))
        v = _f(r.get("tiosfs"))
        if mk and v:
            out.append((mk, v))
    return list(reversed(out[-n:]))


def parse_pbc_shrzgm(text):
    """解析央行"社会融资规模增量统计表" htm → [(month_key, 社融增量亿元, 新增人民币贷款亿元)] 升序。

    表格行格式："2026.07 | 14017 | -5896 | 85 | ..."，第一列日期、第二列
    社会融资规模增量(AFRE flow)、第三列人民币贷款（单位：亿元）。
    """
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S)
    out = []
    for r in rows:
        cells = [re.sub(r"<[^>]+>", "", c).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)]
        cells = [c for c in cells if c and c not in ("", "\xa0")]
        if not cells:
            continue
        m = re.match(r"(\d{4})\.(\d{2})", cells[0])
        if not m:
            continue
        mk = "%s-%s" % (m.group(1), m.group(2))
        afre = _f(cells[1]) if len(cells) > 1 else 0.0
        loan = _f(cells[2]) if len(cells) > 2 else 0.0
        if afre:
            out.append((mk, afre, loan))
    return out


def _em_get(sess, report, columns, sort="REPORT_DATE", extra=None,
            ref="https://data.eastmoney.com/cjsj/", token=None):
    """东财 datacenter-web 通用抓取。"""
    params = {
        "reportName": report, "columns": columns,
        "pageNumber": "1", "pageSize": "60",
        "sortColumns": sort, "sortTypes": "-1",
        "source": "WEB", "client": "WEB",
        "p": "1", "pageNo": "1", "pageNum": "1",
    }
    if token:
        params["token"] = token
    if extra:
        params.update(extra)
    return _get_text(sess, EM_DC, params=params, headers={"Referer": ref}, tries=2, pause=0.6)


def _nbs_esdata_post(sess, cid, ids, root, dts="202401MM-203612MM", quarter=False):
    """POST 统计局 esData（月度/季度）。dts=None 时不传（季度接口不接受范围）。

    实测：月度接口 dts 范围生效；季度接口传 dts 范围返回 500，不传返回最近 6 期。
    """
    payload = {
        "cid": cid, "indicatorIds": ids, "daCatalogId": "",
        "das": [{"text": "全国", "value": "000000000000"}],
        "showType": "1", "rootId": root,
    }
    if dts:
        payload["dts"] = [dts]
    r = sess.post(NBS_ESDATA, json=payload, timeout=15, headers={
        "Accept": "application/json, text/plain, */*",
        "Referer": NBS_QREF if quarter else NBS_REF,
        "Origin": "https://data.stats.gov.cn"})
    r.raise_for_status()
    return r.text


def _latest_month_values(rows, field, fmt=None):
    """从东财报表行（倒序）取最近 MACRO_MONTHS 期 (month_key, 值) 升序。"""
    out = []
    for r in rows[:MACRO_MONTHS]:
        mk = _month_key(r.get("REPORT_DATE") or r.get("TIME"))
        v = r.get(field)
        if v is None or v == "":
            continue
        out.append((mk, _f(v) if fmt is None else fmt(v)))
    return list(reversed(out))


# --------------------------------------------------------------------------
# 宏观小节抓取（并行）
# --------------------------------------------------------------------------

def _sec_macro_pmi():
    """一、PMI及细分（近12月）：统计局 esData 6 指标。"""
    sess = _session()
    data = {"errors": [], "months": [], "series": {}}
    try:
        body = _nbs_esdata_post(sess, NBS_PMI_CID, [i for _, i in NBS_PMI_IDS], NBS_ROOT)
        d = parse_nbs_esdata(body)
        data["months"] = d["months"]
        for idx, (name, _i) in enumerate(NBS_PMI_IDS):
            data["series"][name] = d["series"][idx] if idx < len(d["series"]) else []
        data["sources"] = {"国家统计局": True}
    except Exception as e:  # noqa: BLE001
        data["errors"].append("PMI：%s" % e)
    return data


def _sec_macro_inflation():
    """二、通胀（近12月）：CPI/PPI（东财）+ PPIRM（统计局）+ 美国核心PCE（金十）。"""
    sess = _session()
    data = {"errors": [], "months": {}, "series": {}}
    try:
        rows = parse_em_rows(_em_get(sess, "RPT_ECONOMY_CPI", "REPORT_DATE,TIME,NATIONAL_SAME"))
        out = _latest_month_values(rows, "NATIONAL_SAME")
        data["months"]["cpi"] = [m for m, _v in out]
        data["series"]["CPI同比"] = [v for _m, v in out]
        data["sources"] = {"东方财富": True}
    except Exception as e:  # noqa: BLE001
        data["errors"].append("CPI：%s" % e)
    try:
        rows = parse_em_rows(_em_get(sess, "RPT_ECONOMY_PPI", "REPORT_DATE,TIME,BASE_SAME"))
        out = _latest_month_values(rows, "BASE_SAME")
        data["months"]["ppi"] = [m for m, _v in out]
        data["series"]["PPI同比"] = [v for _m, v in out]
    except Exception as e:  # noqa: BLE001
        data["errors"].append("PPI：%s" % e)
    try:
        body = _nbs_esdata_post(sess, NBS_PPIRM_CID, [i for _, i in NBS_PPIRM_IDS], NBS_ROOT)
        d = parse_nbs_esdata(body)
        # 上年同月=100 → 同比% = 值-100
        data["months"]["ppirm"] = d["months"]
        data["series"]["PPIRM同比"] = [
            (v - 100.0) if v is not None else None for v in (d["series"][0] if d["series"] else [])]
        data["sources"]["国家统计局"] = True
    except Exception as e:  # noqa: BLE001
        data["errors"].append("PPIRM：%s" % e)
    # 注：美国核心PCE 已移至"中美关键指标发布"（金十源滞后，不单独成行）
    return data


def _sec_macro_liquidity():
    """三、流动性（近12月）：M1/M2（东财）+ 社融增量/新增人民币贷款（央行）。

    社融用中国人民银行"社会融资规模增量统计表"（htm），最新到当月（比
    商务部源领先 3-4 个月）；新增人民币贷款为央行表第三列（与东财一致）。
    """
    sess = _session()
    data = {"errors": [], "months": {}, "series": {}}
    try:
        rows = parse_em_rows(_em_get(
            sess, "RPT_ECONOMY_CURRENCY_SUPPLY",
            "REPORT_DATE,TIME,CURRENCY_SAME,BASIC_CURRENCY_SAME"))
        out_m1 = _latest_month_values(rows, "CURRENCY_SAME")
        out_m2 = _latest_month_values(rows, "BASIC_CURRENCY_SAME")
        data["months"]["m"] = [m for m, _v in out_m2]
        data["series"]["M1同比"] = [v for _m, v in out_m1]
        data["series"]["M2同比"] = [v for _m, v in out_m2]
        data["sources"] = {"东方财富": True}
    except Exception as e:  # noqa: BLE001
        data["errors"].append("货币供应：%s" % e)
    try:
        # 央行社融增量统计表（含 新增人民币贷款 列）
        r = sess.get(PBC_SHRZGM, timeout=12,
                     headers={"User-Agent": UA, "Referer": PBC_REF})
        r.raise_for_status()
        h = r.content.decode("gbk", "replace")
        m = re.search(r'href="([^"]+\.htm)"[^>]*>\s*htm', h)
        if not m:
            raise RuntimeError("央行社融表链接未找到")
        rel = m.group(1)
        data_url = PBC_BASE + (rel if rel.startswith("/") else "/" + rel)
        r2 = sess.get(data_url, timeout=12, headers={"User-Agent": UA, "Referer": PBC_REF})
        r2.raise_for_status()
        out = parse_pbc_shrzgm(r2.content.decode("gbk", "replace"))
        if out:
            data["months"]["shrzgm"] = [mk for mk, _a, _l in out]
            data["series"]["社融增量"] = [a for _mk, a, _l in out]
            data["months"]["loan"] = [mk for mk, _a, _l in out]
            data["series"]["新增人民币贷款"] = [
                l if l is not None else 0.0 for _mk, _a, l in out]
            data["sources"]["中国人民银行"] = True
        else:
            raise RuntimeError("央行社融表无数据")
    except Exception as e:  # noqa: BLE001
        data["errors"].append("社融/贷款：%s" % e)
    return data


def _monthly_last(kv_pairs, n=MACRO_MONTHS):
    """把 (date, value) 日序列压缩为每月末值 [(month_key, 该月最后一条值)] 升序。"""
    by_month = {}
    for d, v in kv_pairs:
        mk = d[:7]
        by_month[mk] = v  # 输入升序 → 后者覆盖 = 月末值
    out = sorted(by_month.items())[-n:]
    return out


def _sec_macro_assets():
    """四、资产价格：黄金/比特币/中国10年国债（月末值）+ 1年期LPR + 派生源（房价/GDP）。"""
    sess = _session()
    data = {"errors": [], "months": {}, "series": {}, "extra": {}}
    try:
        text = _get_text(sess, SINA_GLOBAL_KLINE, params={"symbol": "XAU"},
                         headers={"Referer": "https://finance.sina.com.cn/"})
        out = _monthly_last(parse_sina_global_kline(text, 400))
        data["months"]["gold"] = [m for m, _v in out]
        data["series"]["伦敦金"] = [v for _m, v in out]
        data["sources"] = {"新浪": True}
    except Exception as e:  # noqa: BLE001
        data["errors"].append("黄金：%s" % e)
    try:
        # WTI（近12个月月末值，供月均金油比）
        text = _get_text(sess, SINA_GLOBAL_KLINE, params={"symbol": "CL"},
                         headers={"Referer": "https://finance.sina.com.cn/"})
        out = _monthly_last(parse_sina_global_kline(text, 400))
        data["months"]["wti"] = [m for m, _v in out]
        data["series"]["WTI"] = [v for _m, v in out]
        data["sources"]["新浪"] = True
    except Exception as e:  # noqa: BLE001
        data["errors"].append("WTI：%s" % e)
    try:
        # 比特币（MEXC；手机网络不可达时该项留空，不影响其它指标）
        text = _get_text(sess, MEXC_KLINE, params={
            "symbol": "BTCUSDT", "interval": "1d", "limit": "400"}, tries=2, pause=0.6)
        out = _monthly_last(parse_mexc_kline(text, 400))
        data["months"]["btc"] = [m for m, _v in out]
        data["series"]["比特币"] = [v for _m, v in out]
        data["sources"]["MEXC"] = True
    except Exception:  # noqa: BLE001 网络不可达 → 留空
        pass
    try:
        rows = parse_em_rows(_em_get(
            sess, "RPTA_WEB_TREASURYYIELD", "ALL", sort="SOLAR_DATE",
            token=EM_TOKEN, extra={"pageSize": "500"},
            ref="https://data.eastmoney.com/cjsj/zmgzsyl.html"))
        pairs = [(str(r.get("SOLAR_DATE", ""))[:10], _f(r.get("EMM00166466")))
                 for r in rows if r.get("EMM00166466") not in (None, "")]
        out = _monthly_last([p for p in pairs if p[1] > 0])
        data["months"]["cn10y"] = [m for m, _v in out]
        data["series"]["中国10年国债"] = [v for _m, v in out]
        data["sources"]["东方财富"] = True
    except Exception as e:  # noqa: BLE001
        data["errors"].append("国债收益率：%s" % e)
    try:
        rows = parse_em_rows(_em_get(
            sess, "RPTA_WEB_RATE", "ALL", sort="TRADE_DATE", token=EM_TOKEN,
            ref="https://data.eastmoney.com/cjsj/globalRateLPR.html"))
        out = []
        for r in rows[:MACRO_MONTHS]:
            mk = _month_key(r.get("TRADE_DATE"))
            v = r.get("LPR1Y")
            if mk and v not in (None, ""):
                out.append((mk, _f(v)))
        out.reverse()
        data["months"]["lpr"] = [m for m, _v in out]
        data["series"]["1年期LPR"] = [v for _m, v in out]
    except Exception as e:  # noqa: BLE001
        data["errors"].append("LPR：%s" % e)
    try:
        rows = parse_em_rows(_em_get(
            sess, "RPT_ECONOMY_HOUSE_PRICE",
            "REPORT_DATE,CITY,FIRST_COMHOUSE_SAME",
            extra={"filter": '(CITY in ("北京","上海","广州","深圳"))'},
            ref="https://data.eastmoney.com/cjsj/newhouse.html"))
        if rows:
            cur = rows[0].get("REPORT_DATE", "")[:7]
            vals = [_f(r.get("FIRST_COMHOUSE_SAME")) - 100.0
                    for r in rows[:8] if r.get("FIRST_COMHOUSE_SAME")]
            data["extra"]["house_yoy"] = sum(vals) / len(vals) if vals else None
            data["extra"]["house_month"] = cur
    except Exception as e:  # noqa: BLE001
        data["errors"].append("房价：%s" % e)
    try:
        rows = parse_em_rows(_em_get(sess, "RPT_ECONOMY_GDP", "REPORT_DATE,TIME,SUM_SAME"))
        if rows:
            data["extra"]["gdp_nominal_yoy"] = _f(rows[0].get("SUM_SAME"))
            data["extra"]["gdp_month"] = str(rows[0].get("TIME", ""))[:12]
    except Exception as e:  # noqa: BLE001
        data["errors"].append("GDP：%s" % e)
    try:
        # 季度接口不接受 dts 范围（500），不传返回最近 6 期（够算同比 t-4）
        body = _nbs_esdata_post(sess, NBS_GDP_CID, [NBS_GDP_Q], NBS_QROOT,
                                dts=None, quarter=True)
        d = parse_nbs_esdata(body, n=6)
        sv = d["series"][0] if d["series"] else []
        sm = d["months"]
        # 不变价GDP当季值同比 = V_t / V_t-4 - 1
        pairs = [(m, v) for m, v in zip(sm, sv) if v]
        yoy = None
        if len(pairs) >= 5:
            m_t, v_t = pairs[-1]
            m_base = None
            for m, v in pairs:
                if _quarter_shift(m_t, -4) == m:
                    m_base = (m, v)
                    break
            if m_base and m_base[1]:
                yoy = (v_t / m_base[1] - 1.0) * 100.0
        data["extra"]["gdp_real_yoy"] = round(yoy, 2) if yoy is not None else None
        data["extra"]["gdp_real_month"] = pairs[-1][0] if pairs else None
    except Exception as e:  # noqa: BLE001
        data["errors"].append("不变价GDP：%s" % e)
    return data


def _quarter_shift(month_key, delta):
    """季度"2026-06"往前/后移 delta 个季度 → 同格式（取季度末月）。"""
    try:
        y = int(month_key[:4])
        m = int(month_key[5:7])
        q = (m - 1) // 3 + 1
        qi = (q - 1 + delta) % 4 + 1
        yy = y + (q - 1 + delta) // 4
        return "%s-%02d" % (yy, qi * 3)
    except Exception:
        return None


def china_release_schedule(now=None):
    """中国关键指标下次预计发布时间（按常规发布规律推算，纯函数可测试）。

    返回 [(指标名(与发布表中国行一致), 下次日期"MM-DD", 数据期说明)]。
    规律（遇节假日顺延，此处按常规日近似）：
      - 官方制造业PMI：每月 1 日发布上月
      - CPI / PPI：次月 9 日发布上月
      - 社融增量 / M1 / M2 / 新增人民币贷款：次月 15 日前（央行月中发布）
      - 1年期 LPR：每月 20 日
    """
    now = now or _cn_now()
    y, m = now.year, now.month
    prev_m = "%d-%02d" % ((y - 1, 12) if m == 1 else (y, m - 1))

    def _next(day, desc):
        """今天 ≤ 本月 day 日 → 本月 day 日（发布 desc）；否则下月 day 日。"""
        if now.day <= day:
            return "%02d-%02d" % (m, day), desc
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        return "%02d-%02d" % (nm, day), desc

    cur = "%d-%02d" % (y, m)
    entries = [
        ("PMI", *_next(1, "%s月数据" % prev_m)),
        ("CPI同比", *_next(9, "%s月数据" % prev_m)),
        ("PPI同比", *_next(9, "%s月数据" % prev_m)),
        ("社融增量", *_next(15, "%s月数据" % prev_m)),
        ("M1同比", *_next(15, "%s月数据" % prev_m)),
        ("M2同比", *_next(15, "%s月数据" % prev_m)),
        ("新增人民币贷款", *_next(15, "%s月数据" % prev_m)),
        ("1年期LPR", *_next(20, "%s月报价" % cur)),
    ]
    return entries


def _sec_macro_usdata():
    """六、中美关键指标发布：东财美国经济数据（发布计划 + 结果，白名单）
    + 中国关键指标下次预计发布时间（按常规发布规律推算，无网络）。"""
    sess = _session()
    data = {"errors": [], "us": [], "cn_schedule": []}
    try:
        rows = parse_em_rows(_em_get(
            sess, "RPT_ECONOMICVALUE_USA", "ALL",
            extra={"pageSize": "200"}, ref="https://data.eastmoney.com/cjsj/usa.html"))
        for r in rows:
            iid = r.get("INDICATOR_ID")
            if iid not in US_USEFUL:
                continue
            pd_ = str(r.get("PUBLISH_DATE") or "")[:10]
            if not pd_:
                continue
            data["us"].append({
                "date": pd_,
                "name": US_NAME_SHORT.get(iid,
                          (r.get("INDICATOR_NAME") or "").replace("美国:", "")),
                "value": r.get("VALUE"),
                "prev": r.get("PRE_VALUE"),
                "period": str(r.get("REPORT_DATE_CH") or "")[:12],
            })
        data["us"].sort(key=lambda x: x["date"])          # 时间正向（早→晚，需求）
        data["us"] = data["us"][-12:]                      # 取最近 12 条
        data["sources"] = {"东方财富": True}
    except Exception as e:  # noqa: BLE001
        data["errors"].append("美国指标：%s" % e)
    try:
        data["cn_schedule"] = china_release_schedule()
    except Exception:  # noqa: BLE001
        pass
    try:
        # 美国核心PCE（金十源，免费层滞后）：并入发布表展示，标注数据月份
        t = int(time.time() * 1000)
        text = _get_text(sess, JIN10_LIST, params={"category": "ec", "attr_id": "80", "_": str(t)},
                         headers=JIN10_H, tries=2, pause=0.6)
        p = parse_jin10(text)
        if p:
            data["us"].append({
                "date": p["date"],
                "name": "核心PCE物价指数年率",
                "value": p["value"],
                "prev": p.get("prev"),
                "period": "",
            })
            data["sources"]["金十"] = True
    except Exception:  # noqa: BLE001
        pass
    return data


def _sec_macro_commodity():
    """五、大宗商品近 5 日：伦敦金 / WTI / 金油比（复用历史小节）。"""
    sess = _session()
    data = {"errors": [], "dates": [], "gold": [], "wti": [], "ratio": []}
    try:
        text = _get_text(sess, SINA_GLOBAL_KLINE, params={"symbol": "XAU"},
                         headers={"Referer": "https://finance.sina.com.cn/"})
        xau = dict(parse_sina_global_kline(text, 8))
        text = _get_text(sess, SINA_GLOBAL_KLINE, params={"symbol": "CL"},
                         headers={"Referer": "https://finance.sina.com.cn/"})
        wti = dict(parse_sina_global_kline(text, 8))
        dates = sorted(set(xau) & set(wti))[-MACRO_COMMODITY_DAYS:]
        data["dates"] = dates
        data["gold"] = [xau[d] for d in dates]
        data["wti"] = [wti[d] for d in dates]
        data["ratio"] = [round(xau[d] / wti[d], 1) if wti[d] else None for d in dates]
        data["sources"] = {"新浪": True}
    except Exception as e:  # noqa: BLE001
        data["errors"].append("大宗商品：%s" % e)
    return data


MACRO_SECTIONS = [
    ("macro_pmi", _sec_macro_pmi),
    ("macro_inflation", _sec_macro_inflation),
    ("macro_liquidity", _sec_macro_liquidity),
    ("macro_assets", _sec_macro_assets),
    ("macro_usdata", _sec_macro_usdata),
]


def _new_macro_state():
    return {
        "ok": True, "ts": _cn_now().strftime("%H:%M:%S"), "sources": {},
        "pmi": {"months": [], "series": {}},
        "inflation": {"months": {}, "series": {}},
        "liquidity": {"months": {}, "series": {}},
        "assets": {"months": {}, "series": {}, "extra": {}},
        "us": [],
        "cn_schedule": [],
        "commodity": {"dates": [], "gold": [], "wti": [], "ratio": []},
        "errors": [],
    }


def _merge_macro(out, key, data):
    data = data or {}
    if key == "macro_pmi":
        out["pmi"] = {"months": data.get("months", []), "series": data.get("series", {})}
    elif key == "macro_inflation":
        out["inflation"] = {"months": data.get("months", {}), "series": data.get("series", {})}
    elif key == "macro_liquidity":
        out["liquidity"] = {"months": data.get("months", {}), "series": data.get("series", {})}
    elif key == "macro_assets":
        out["assets"] = {"months": data.get("months", {}), "series": data.get("series", {}),
                         "extra": data.get("extra", {})}
    elif key == "macro_usdata":
        out["us"] = data.get("us", [])
        out["cn_schedule"] = data.get("cn_schedule", [])
    elif key == "macro_commodity":
        out["commodity"] = {k: data.get(k, []) for k in
                            ("dates", "gold", "wti", "ratio")}
    for e in data.get("errors", []):
        out["errors"].append(e)
    for s, v in (data.get("sources") or {}).items():
        out["sources"][s] = v


def refresh_macro(on_done=None):
    """刷新宏观数据（并行小节后合并，返回完整 dict）。"""
    results = {}

    def run(key, fn):
        try:
            data = fn()
        except Exception as e:  # noqa: BLE001
            data = {"errors": [str(e)]}
        results[key] = data

    threads = [threading.Thread(target=run, args=(k, f), daemon=True)
               for k, f in MACRO_SECTIONS]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    out = _new_macro_state()
    for k, _f in MACRO_SECTIONS:
        _merge_macro(out, k, results.get(k))
    if on_done:
        try:
            on_done(out)
        except Exception:  # noqa: BLE001
            pass
    return out


# --------------------------------------------------------------------------
# 宏观月度数据本地缓存（需求：月度数据不必每次查询）
#   策略：默认先读本地缓存——当天已刷新过（缓存日期==今天）就直接用缓存，
#   不联网；缓存日期非今天或首次使用时联网刷新并写缓存；用户手动点"刷新"
#   按钮强制联网刷新。App 据此按"当日日期 vs 缓存日期"决定是否刷新。
# --------------------------------------------------------------------------

MACRO_CACHE_NAME = "nstock_macro_cache.json"
MACRO_CACHE_VERSION = 2   # 缓存结构版本；变更后旧缓存失效（重新联网）


def _normalize_cached_macro(state):
    """缓存数据归一化：发布表强制时间正向排序（旧缓存可能为倒序）。"""
    try:
        us = state.get("us") or []
        us = [u for u in us if u.get("date")]
        us.sort(key=lambda x: x["date"])
        state["us"] = us[-12:]
    except Exception:  # noqa: BLE001
        pass


def _macro_cache_path():
    base = (os.environ.get("ANDROID_PRIVATE")
            or os.environ.get("TMP")
            or os.environ.get("TEMP")
            or os.getcwd())
    return os.path.join(base, MACRO_CACHE_NAME)


def _load_macro_cache():
    """读本地缓存 → (state dict, 缓存日期字符串)；无缓存/版本不符返回 (None, None)。"""
    try:
        import json as _json
        with open(_macro_cache_path(), "r", encoding="utf-8") as f:
            d = _json.load(f)
        if not isinstance(d, dict) or "pmi" not in d:
            return None, None
        if d.get("cache_version") != MACRO_CACHE_VERSION:
            return None, None
        return d, str(d.get("cache_date", ""))
    except Exception:  # noqa: BLE001
        return None, None


def _save_macro_cache(state):
    """把宏观状态写入本地缓存（含缓存日期与版本）。"""
    try:
        import json as _json
        d = dict(state)
        d["cache_date"] = _cn_now().strftime("%Y-%m-%d")
        d["cache_version"] = MACRO_CACHE_VERSION
        with open(_macro_cache_path(), "w", encoding="utf-8") as f:
            _json.dump(d, f, ensure_ascii=False)
        return True
    except Exception:  # noqa: BLE001
        return False


def refresh_macro_cached(on_done=None, force=False):
    """宏观数据入口：默认读本地缓存（当天有效即不联网）。

    - force=True：忽略缓存强制联网刷新并写缓存（用户手动刷新按钮）
    - 无缓存或缓存日期 != 今天：联网刷新并写缓存
    - 缓存日期 == 今天：直接返回缓存（标注 from_cache=True）
    读缓存后统一归一化：中美发布表按时间正向排序（旧缓存可能为倒序）。
    """
    if not force:
        cached, cdate = _load_macro_cache()
        if cached is not None and cdate == _cn_now().strftime("%Y-%m-%d"):
            _normalize_cached_macro(cached)
            cached["from_cache"] = True
            if on_done:
                try:
                    on_done(cached)
                except Exception:  # noqa: BLE001
                    pass
            return cached
    out = refresh_macro(on_done)
    out["from_cache"] = False
    _save_macro_cache(out)
    return out


# --------------------------------------------------------------------------
# 宏观派生指标（纯函数，可测试）
# --------------------------------------------------------------------------

def derive_macro_pmi(series):
    """PMI 派生：经济势能/供需差/备料差/TEC（用最新两期，缺值 None）。

    series: {"PMI","生产","新订单","产成品库存","采购量","原材料库存": [值...]}
    返回 {名称: (最新值, 公式, 说明)}。
    """
    def last2(k):
        v = series.get(k) or []
        return (v[-1] if v else None, v[-2] if len(v) > 1 else None)
    xd, xd_p = last2("新订单")
    ck, ck_p = last2("产成品库存")
    sc, _ = last2("生产")
    gl, _ = last2("采购量")
    yl, _ = last2("原材料库存")
    out = {}
    out["经济势能"] = (xd - ck) if (xd is not None and ck is not None) else None
    out["供需差"] = (sc - xd) if (sc is not None and xd is not None) else None
    out["备料差"] = (gl - yl) if (gl is not None and yl is not None) else None
    if xd is not None and xd_p is not None and ck is not None and ck_p is not None:
        out["TEC"] = (xd - xd_p) - (ck - ck_p)
    else:
        out["TEC"] = None
    return out


def derive_macro_inflation(series):
    """通胀派生：通胀预期指数 = CPI同比 - PPI同比（最新两期对齐）。"""
    cpi = series.get("CPI同比") or []
    ppi = series.get("PPI同比") or []
    n = min(len(cpi), len(ppi))
    if n == 0:
        return {}
    v = None
    for i in range(n - 1, -1, -1):
        if cpi[i] is not None and ppi[i] is not None:
            v = cpi[i] - ppi[i]
            break
    return {"通胀预期指数": v}


def derive_macro_liquidity(series):
    """流动性派生：M1-M2 剪刀差（最新两期对齐）。"""
    m1 = series.get("M1同比") or []
    m2 = series.get("M2同比") or []
    n = min(len(m1), len(m2))
    if n == 0:
        return {}
    v = None
    for i in range(n - 1, -1, -1):
        if m1[i] is not None and m2[i] is not None:
            v = m1[i] - m2[i]
            break
    return {"M1-M2剪刀差": v}


def derive_macro_assets(series, extra):
    """资产价格派生：金比特币 / 中国实际利率 / GDP平减指数。

    series: {"伦敦金","比特币","中国10年国债","1年期LPR": [值...]}
    extra: {"house_yoy","gdp_nominal_yoy","gdp_real_yoy"}
    """
    out = {}
    lpr = (series.get("1年期LPR") or [])
    hy = extra.get("house_yoy")
    if lpr and lpr[-1] is not None and hy is not None:
        out["中国实际利率"] = lpr[-1] - hy
    ny = extra.get("gdp_nominal_yoy")
    ry = extra.get("gdp_real_yoy")
    if ny is not None and ry is not None:
        out["GDP平减指数"] = ny - ry
    return out
