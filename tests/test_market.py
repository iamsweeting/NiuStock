# -*- coding: utf-8 -*-
"""大盘信息模块单元测试（纯解析函数，不访问网络）。"""
import json
from datetime import datetime, time, timezone, timedelta

from app import market


# --------------------------------------------------------------------------
# 新浪 hq 解析
# --------------------------------------------------------------------------

SINA_TEXT = (
    'var hq_str_sh000001="上证指数,3891.1751,3903.7210,3905.2026,3912.1314,'
    '3883.7870,0,0,446895868,883423480099,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,'
    '0,0,2026-08-21,15:43:32,00,";\n'
    'var hq_str_sh000852="中证1000,7555.5478,7589.7793,7601.8044,7634.0839,'
    '7472.4948,0,0,219518440,415934986591,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,'
    '0,0,2026-08-21,15:30:36,00,";\n'
    'var hq_str_rt_hkHSI="HSI,恒生指数,25807.610,25698.490,26009.460,25807.610,'
    '26009.459,310.970,1.210,0.000,0.000,257277433.846,13796988552,0.000,0.000,'
    '28056.100,22518.000,2026/08/21,16:09:01,,,,,,";\n'
    'var hq_str_hf_XAU="4594.62,4519.140,4594.62,4594.97,4604.28,4508.75,'
    '23:06:00,4519.14,4517.98,0,0,0,2026-08-21,伦敦金现货黄金";\n'
    'var hq_str_nf_AU0="黄金9999,230851,990.520,997.500,990.160,0.000,995.800,'
    '995.820,995.820,0.000,978.800,10,5,210955.000,115967,空,黄金,2026-08-21,'
    '1,,,,,,,,,993.811,0.000,0,0.000,0,0.000,0,0.000,0,0.000,0,0.000,0,0.000,'
    '0,0.000,0";\n'
    'var hq_str_zz9999="";\n'
)


def test_parse_sina_hq_cn_index():
    q = market.parse_sina_hq(SINA_TEXT)
    assert "sh000001" in q
    assert q["sh000001"]["name"] == "上证指数"
    assert q["sh000001"]["price"] == 3905.2026
    assert abs(q["sh000001"]["pct"] - 0.0381) < 0.001  # (3905.20-3903.72)/3903.72


def test_parse_sina_hq_hk():
    q = market.parse_sina_hq(SINA_TEXT)
    assert q["rt_hkHSI"]["name"] == "恒生指数"
    assert q["rt_hkHSI"]["price"] == 26009.460
    assert abs(q["rt_hkHSI"]["pct"] - 1.210) < 1e-9


def test_parse_sina_hq_gold_futures():
    q = market.parse_sina_hq(SINA_TEXT)
    assert q["hf_XAU"]["name"] == "伦敦金现货黄金"
    assert q["hf_XAU"]["price"] == 4594.62
    assert abs(q["hf_XAU"]["pct"] - (4594.62 - 4519.14) / 4519.14 * 100) < 1e-6
    assert q["nf_AU0"]["name"] == "黄金9999"
    assert q["nf_AU0"]["price"] == 995.820
    assert abs(q["nf_AU0"]["pct"] - (995.82 - 978.80) / 978.80 * 100) < 1e-6


def test_parse_sina_hq_skip_empty():
    q = market.parse_sina_hq(SINA_TEXT)
    assert "zz9999" not in q


def test_parse_sina_hq_amount():
    amt = market.parse_sina_hq_amount(SINA_TEXT)
    assert amt["sh000001"] == 883423480099.0
    assert "rt_hkHSI" not in amt  # 港股不解析为成交额


# --------------------------------------------------------------------------
# 沪深300中位数
# --------------------------------------------------------------------------

def test_median_price():
    assert market.median_price([]) is None
    assert market.median_price([5, 3, 1]) == 3
    assert market.median_price([4, 2, 1, 3]) == 2.5


def test_parse_sina_hs300():
    text = ('var _=([{"symbol":"sh600000","trade":"10.5"},'
            '{"symbol":"sz000001","trade":"12.3"},'
            '{"symbol":"sh600036","trade":""}]);')
    prices = market.parse_sina_hs300(text)
    assert prices == [10.5, 12.3]


# --------------------------------------------------------------------------
# 新浪国际期货日K
# --------------------------------------------------------------------------

def test_parse_sina_global_kline():
    text = ('var _=([{"date":"2026-08-19","open":"1","high":"1","low":"1","close":"4600.00"},'
            '{"date":"2026-08-20","open":"1","high":"1","low":"1","close":"4590.00"},'
            '{"date":"2026-08-21","open":"1","high":"1","low":"1","close":"4610.00"}]);')
    rows = market.parse_sina_global_kline(text, n=2)
    assert rows == [("2026-08-20", 4590.0), ("2026-08-21", 4610.0)]


# --------------------------------------------------------------------------
# Yahoo chart
# --------------------------------------------------------------------------

def test_parse_yahoo_chart():
    import json
    ts0 = 1787184000
    payload = {
        "chart": {"result": [{
            "meta": {"regularMarketPrice": 86.64},
            "timestamp": [ts0, ts0 + 86400, ts0 + 172800],
            "indicators": {"quote": [{"close": [84.5, 84.94, 86.64]}]},
        }]}
    }
    price, hist = market.parse_yahoo_chart(json.dumps(payload))
    assert price == 86.64
    assert len(hist) == 3
    assert hist[-1][1] == 86.64


# --------------------------------------------------------------------------
# 中国货币网中间价
# --------------------------------------------------------------------------

def test_parse_chinamoney():
    import json
    payload = {
        "data": {
            "head": ["USD/CNY", "EUR/CNY"],
            "searchlist": ["USD/CNY", "EUR/CNY"],
        },
        "records": [
            {"date": "2026-08-19", "values": ["7.1401", "8.3120"]},
            {"date": "2026-08-20", "values": ["7.1450", "8.3200"]},
            {"date": "2026-08-21", "values": ["7.1500", "8.3300"]},
        ],
    }
    rows = market.parse_chinamoney(json.dumps(payload))
    assert rows == [("2026-08-19", 7.1401), ("2026-08-20", 7.1450), ("2026-08-21", 7.1500)]


def test_parse_chinamoney_no_usd():
    import json
    payload = {"data": {"head": ["EUR/CNY"]}, "records": [
        {"date": "2026-08-21", "values": ["8.33"]}]}
    assert market.parse_chinamoney(json.dumps(payload)) == []


def test_parse_legulegu_median_pe():
    html = ('<table><tr><td class="table-title-larger">沪深300市盈率(TTM)中位数</td>'
            ' <td>20.25</td></tr>'
            '<tr><td>沪深300市盈率(TTM)等权平均</td><td>34.5</td></tr></table>')
    assert market.parse_legulegu_median_pe(html) == 20.25
    assert market.parse_legulegu_median_pe("<html>无数据</html>") is None


def test_parse_chinamoney_newest_five():
    import json
    # records 倒序（最新在前）→ 只取最近 5 个交易日且升序返回
    payload = {
        "data": {"head": ["USD/CNY"]},
        "records": [{"date": "2026-08-%02d" % d, "values": ["7.1%03d" % d]}
                    for d in (21, 20, 17, 16, 15, 14, 13)],
    }
    rows = market.parse_chinamoney(json.dumps(payload))
    assert rows == [("2026-08-15", 7.1015), ("2026-08-16", 7.1016),
                    ("2026-08-17", 7.1017), ("2026-08-20", 7.102),
                    ("2026-08-21", 7.1021)]


# --------------------------------------------------------------------------
# 东财K线
# --------------------------------------------------------------------------

def test_parse_em_kline():
    import json
    payload = {"data": {"klines": [
        "2026-08-20,3900,3910,3920,3890,1000,1200000000.0",
        "2026-08-21,3910,3905,3912,3883,900,1100000000.0",
    ]}}
    rows = market.parse_em_kline(json.dumps(payload))
    assert rows[0] == ("2026-08-20", 1000.0, 1200000000.0)
    assert rows[1][2] == 1100000000.0


# --------------------------------------------------------------------------
# 本日预测额 / 交易分钟
# --------------------------------------------------------------------------

def test_elapsed_trade_minutes():
    tz = timezone(timedelta(hours=8))
    assert market.elapsed_trade_minutes(datetime(2026, 8, 21, 9, 20, tzinfo=tz)) == 0.0   # 开盘前
    assert market.elapsed_trade_minutes(datetime(2026, 8, 21, 10, 0, tzinfo=tz)) == 30.0  # 上午盘中
    assert market.elapsed_trade_minutes(datetime(2026, 8, 21, 13, 30, tzinfo=tz)) == 150.0  # 下午盘中
    assert market.elapsed_trade_minutes(datetime(2026, 8, 21, 15, 1, tzinfo=tz)) == 240.0  # 收盘后
    assert market.elapsed_trade_minutes(datetime(2026, 8, 22, 10, 0, tzinfo=tz)) == 0.0    # 周六


def test_predict_turnover():
    assert market.predict_turnover(0) is None
    # 上午 10:00（已交易 30 分钟）：预测 = 额 / 30 * 240
    p = market.predict_turnover(3e11, datetime(2026, 8, 21, 10, 0,
                                               tzinfo=timezone(timedelta(hours=8))))
    assert abs(p - 3e11 / 30 * 240) < 1.0
    # 未开盘 → None
    assert market.predict_turnover(3e11, datetime(2026, 8, 21, 9, 0,
                                                  tzinfo=timezone(timedelta(hours=8)))) is None


# --------------------------------------------------------------------------
# 历史分时占比预测模型
# --------------------------------------------------------------------------

def _flat_curve(final, points):
    """构造一条分时曲线：points=[(elapsed, frac)]，cum = final * frac。"""
    return [(el, final * f) for el, f in points]


def test_minute_elapsed():
    assert market._minute_elapsed(930) == 0
    assert market._minute_elapsed(1000) == 30
    assert market._minute_elapsed(1130) == 120
    assert market._minute_elapsed(1301) == 121
    assert market._minute_elapsed(1500) == 240


def test_build_turnover_profile():
    curves = {
        "20260818": _flat_curve(2.0e12, [(30, 0.10), (120, 0.50), (240, 1.0)]),
        "20260819": _flat_curve(2.2e12, [(30, 0.12), (120, 0.52), (240, 1.0)]),
    }
    profile, avg = market.build_turnover_profile(curves)
    assert abs(avg - 2.1e12) < 1.0
    assert abs(profile[30] - 0.11) < 1e-9
    assert abs(profile[240] - 1.0) < 1e-9


def test_predict_turnover_model():
    curves = {
        "20260818": _flat_curve(2.0e12, [(30, 0.10), (120, 0.50), (240, 1.0)]),
        "20260819": _flat_curve(2.2e12, [(30, 0.12), (120, 0.52), (240, 1.0)]),
    }
    profile, avg = market.build_turnover_profile(curves)
    # 10:00（30 分钟）已成交 2.2e11（占比 0.11）→ 预测 ≈ 2.0e12
    p = market.predict_turnover_model(
        0.11 * avg, profile, avg,
        datetime(2026, 8, 20, 10, 0, tzinfo=timezone(timedelta(hours=8))))
    assert p is not None and abs(p - avg) / avg < 0.02
    # 开盘过短（9:40，10 分钟）→ 不预测（None）
    assert market.predict_turnover_model(
        0.11 * avg, profile, avg,
        datetime(2026, 8, 20, 9, 40, tzinfo=timezone(timedelta(hours=8)))) is None
    # 无历史曲线 → None
    assert market.predict_turnover_model(
        3e11, {}, 0.0, datetime(2026, 8, 20, 10, 0,
                                tzinfo=timezone(timedelta(hours=8)))) is None
    # 数据过少（占比 < min_frac）→ None
    assert market.predict_turnover_model(
        1e9, profile, avg, datetime(2026, 8, 20, 10, 0,
                                    tzinfo=timezone(timedelta(hours=8)))) is None


def test_refresh_ttl_const():
    assert market.REFRESH_TTL >= 60


# --------------------------------------------------------------------------
# 并行小节合并
# --------------------------------------------------------------------------

def test_merge_section_live_and_hist():
    out = market._new_state()
    market._merge_section(out, "live_sina", {
        "quotes": [{"name": "上证指数", "price": 3905.2, "pct": 0.04, "src": "新浪"}],
        "turnover_yi": 8823.0, "turnover_pred_yi": 9600.0,
        "errors": [], "sources": {"新浪": True},
    })
    market._merge_section(out, "hist_turnover", {
        "turnover": [("2026-08-21", 8823.0)], "errors": [],
    })
    assert len(out["live"]["quotes"]) == 1
    assert out["live"]["turnover_yi"] == 8823.0
    assert out["history"]["turnover"] == [("2026-08-21", 8823.0)]
    assert out["sources"].get("新浪") is True


def test_merge_section_errors_routed():
    out = market._new_state()
    market._merge_section(out, "live_median", {
        "csi300_median": 21.5, "errors": ["成分页挂了"]})
    market._merge_section(out, "hist_ccpr", {"ccpr": [], "errors": ["货币网挂了"]})
    assert "成分页挂了" in out["live"]["errors"]
    assert "货币网挂了" in out["history"]["errors"]


def test_new_state_shape():
    out = market._new_state()
    assert out["live"]["quotes"] == [] and out["live"]["errors"] == []
    assert out["history"]["turnover"] == [] and "kr" not in out["history"]
    assert "news" in out["history"]
    assert "turnover_vs_prev" in out["live"]


# --------------------------------------------------------------------------
# 本周重大关注（新浪 7x24 解析）
# --------------------------------------------------------------------------

def test_parse_sina_7x24():
    payload = json.dumps({
        "result": {"data": {"feed": {"list": [
            {"create_time": "2026-08-27 01:16:21", "rich_text": "美联储隔夜逆回购使用规模7万亿", "docurl": "https://finance.sina.cn/7x24/1.shtml"},
            {"create_time": "2026-08-27 01:15:23", "rich_text": "新交所办公交易骤减", "docurl": ""},
            {"create_time": "2026-08-27 01:10:00", "rich_text": "英伟达即将发布新季度财报", "docurl": "https://finance.sina.cn/7x24/2.shtml"},
            {"create_time": "", "rich_text": "  "},
        ]}}}
    })
    news = market.parse_sina_7x24(payload, n=5)
    # 评分过滤：美联储7万亿/英伟达财报（重大）保留；"新交所办公交易骤减"无重大词被剔除
    texts = [t for _, t, _ in news]
    assert len(news) == 2
    assert any("美联储" in t for t in texts)
    assert any("英伟达" in t for t in texts)
    assert not any("新交所" in t for t in texts)
    # 重大性：美联储（央行/万亿）应排在英伟达前
    assert "美联储" in news[0][1]
    # 空主题被过滤
    assert all(t for _, t, _ in news)


def test_news_score_filters_small_ipo():
    # 需求：普通小新股上市不推送，千亿级重大才入选
    assert market._news_score("某小型公司申购发行价5元每股") < 0
    assert market._news_score("宁德时代即将发布业绩预告") > 0
    assert market._news_score("美联储下周召开利率决议会议") > 0


def test_merge_week_news():
    out = market._new_state()
    market._merge_section(out, "week_news", {
        "news": [("2026-08-27 01:16", "美联储逆回购7万亿", "https://x")],
        "errors": [],
    })
    assert out["history"]["news"][0][1] == "美联储逆回购7万亿"


def test_merge_turnover_vs_prev():
    out = market._new_state()
    market._merge_section(out, "live_sina", {
        "turnover_yi": 10000.0, "turnover_vs_prev": 123.0, "errors": []})
    assert out["live"]["turnover_vs_prev"] == 123.0


def test_no_break_latin():
    # 数字/字母与中文边界插入不换行空格，防止 Kivy 在 CJK↔Latin 边界断行
    assert market._no_break_latin("涨10%后回落") == "涨\u00A010%\u00A0后回落"
    assert market._no_break_latin("ETF半导体") == "ETF\u00A0半导体"
    assert market._no_break_latin("半导体ETF大涨") == "半导体\u00A0ETF\u00A0大涨"
    assert market._no_break_latin("纯中文消息") == "纯中文消息"
    assert market._no_break_latin("") == ""


def test_news_min_score_threshold():
    # 门槛放宽：至少命中一个预告词(+1)即可入选（原 MIN=2 导致新闻太少，需求）
    assert market.WEEK_NEWS_MIN_SCORE == 1
    assert market._news_score("上证指数收盘微涨") >= 1        # 指数/大盘
    assert market._news_score("半导体板块资金流入") >= 1       # 半导体
    assert market._news_score("券商股集体走强") >= 1           # 券商
    # 小额新股仍被剔除
    assert market._news_score("某公司上市申购募资3亿") < 0


def test_parse_sina_7x24_keeps_time_order():
    # 新需求：最新消息按时间倒序（重大过滤后保持原顺序，不按评分重排）
    payload = json.dumps({
        "result": {"data": {"feed": {"list": [
            {"create_time": "2026-08-27 03:00:00", "rich_text": "英伟达财报出炉",
             "docurl": ""},
            {"create_time": "2026-08-27 02:00:00", "rich_text": "央行降准0.5个百分点",
             "docurl": ""},
            {"create_time": "2026-08-27 01:00:00", "rich_text": "普通生活新闻",
             "docurl": ""},
        ]}}}
    })
    news = market.parse_sina_7x24(payload, n=10)
    texts = [t for _, t, _ in news]
    assert len(news) == 2
    assert texts[0] == "英伟达财报出炉"   # 时间最新在前（不因"央行"评分更高而重排）
    assert texts[1] == "央行降准0.5个百分点"
    assert "普通生活新闻" not in texts


def test_split_news_title():
    # 标题/正文拆分：按首个 ： : ——
    assert market.split_news_title("英伟达发布财报：营收大增50%") == ("英伟达发布财报", "营收大增50%")
    assert market.split_news_title("央行降准0.5个百分点——释放长期资金") == (
        "央行降准0.5个百分点", "释放长期资金")
    # 无分隔符 → 整条作为标题（不忽略，需求：新闻数量不能太少）
    assert market.split_news_title("半导体ETF资金流入 规模创新高") == (
        "半导体ETF资金流入 规模创新高", None)
    assert market.split_news_title("：只有正文") == (None, None)                      # 无标题 → 忽略
    assert market.split_news_title("") == (None, None)                                # 空 → 忽略
    assert market.split_news_title("   ") == (None, None)
    # 正文限制 100 字
    t, b = market.split_news_title("标题：" + "正" * 200)
    assert len(b) == 100


def test_macro_cache_roundtrip(tmp_path):
    # 缓存读写 + refresh_macro_cached 当天命中（不联网）
    orig_path = market._macro_cache_path
    orig_refresh = market.refresh_macro
    try:
        market._macro_cache_path = lambda: str(tmp_path / "c.json")
        state = market._new_macro_state()
        state["pmi"] = {"months": ["2026-07"], "series": {"PMI": [49.2]}}
        assert market._save_macro_cache(state) is True
        cached, cdate = market._load_macro_cache()
        assert cached is not None
        assert cached["pmi"]["series"]["PMI"] == [49.2]
        assert cdate == market._cn_now().strftime("%Y-%m-%d")

        # 缓存日期==今天 → refresh_macro_cached 直接返回缓存（不联网）
        called = []

        def fake_refresh(on_done=None):
            called.append(1)
            s = market._new_macro_state()
            s["pmi"] = {"months": ["2026-08"], "series": {"PMI": [50.0]}}
            return s

        market.refresh_macro = fake_refresh
        out = market.refresh_macro_cached(None, force=False)
        assert not called
        assert out["from_cache"] is True
        assert out["pmi"]["series"]["PMI"] == [49.2]

        # 强制刷新 → 联网并写缓存
        out2 = market.refresh_macro_cached(None, force=True)
        assert called
        assert out2["from_cache"] is False
        assert out2["pmi"]["series"]["PMI"] == [50.0]
        cached2, _ = market._load_macro_cache()
        assert cached2["pmi"]["series"]["PMI"] == [50.0]
    finally:
        market._macro_cache_path = orig_path
        market.refresh_macro = orig_refresh
