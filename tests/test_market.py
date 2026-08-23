# -*- coding: utf-8 -*-
"""大盘信息模块单元测试（纯解析函数，不访问网络）。"""
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
    market._merge_section(out, "hist_kr", {
        "kr": {"三星电子": [("08-21", 86000.0)]}, "errors": [],
    })
    assert len(out["live"]["quotes"]) == 1
    assert out["live"]["turnover_yi"] == 8823.0
    assert out["history"]["turnover"] == [("2026-08-21", 8823.0)]
    assert out["history"]["kr"]["三星电子"] == [("08-21", 86000.0)]
    assert out["sources"].get("新浪") is True


def test_merge_section_errors_routed():
    out = market._new_state()
    market._merge_section(out, "live_yahoo", {"quotes": [], "errors": ["Yahoo挂了"]})
    market._merge_section(out, "hist_ccpr", {"ccpr": [], "errors": ["货币网挂了"]})
    assert "Yahoo挂了" in out["live"]["errors"]
    assert "货币网挂了" in out["history"]["errors"]


def test_new_state_shape():
    out = market._new_state()
    assert out["live"]["quotes"] == [] and out["live"]["errors"] == []
    assert out["history"]["turnover"] == [] and out["history"]["kr"] == {}
