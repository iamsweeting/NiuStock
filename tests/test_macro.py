# -*- coding: utf-8 -*-
"""宏观数据模块测试：解析 + 派生纯函数（不访问网络）。"""
import json

from app import market


def _esdata_body(rows):
    """构造 esData 响应 JSON 文本：rows=[(name, [values...])]（倒序）。"""
    data = [{"name": n, "values": [{"value": v} for v in vals]}
            for n, vals in rows]
    return json.dumps({"data": data})


def test_month_key_variants():
    assert market._month_key("2026年7月") == "2026-07"
    assert market._month_key("2026年07月") == "2026-07"
    assert market._month_key("202607") == "2026-07"
    assert market._month_key("2026-07") == "2026-07"
    assert market._month_key("") == ""


def test_month_short():
    assert market._month_short("2026-07") == "26-07"


def test_parse_nbs_esdata_desc_and_filter():
    # esData 倒序：最新在前，未来空值在前，取最近 n 个有值月份升序
    rows = [
        ("2026年9月", ["", "", ""]),
        ("2026年8月", ["", "50.0", ""]),
        ("2026年7月", ["49.2", "49.9", "48.5"]),
        ("2026年6月", ["50.3", "51.4", ""]),
        ("2026年5月", ["50.0", "51.2", "49.9"]),
    ]
    d = market.parse_nbs_esdata(_esdata_body(rows), n=12)
    assert d["months"] == ["2026-05", "2026-06", "2026-07", "2026-08"]
    assert d["series"][0] == [50.0, 50.3, 49.2, None]      # 2026-08 第一列无值 → None
    assert d["series"][1] == [51.2, 51.4, 49.9, 50.0]
    assert d["series"][2] == [49.9, None, 48.5, None]


def test_parse_nbs_esdata_limit_n():
    rows = [("%d年%d月" % (2026, i), ["%d" % (i + 10)]) for i in range(1, 13)]
    rows.reverse()
    d = market.parse_nbs_esdata(_esdata_body(rows), n=5)
    assert len(d["months"]) == 5
    assert d["months"] == ["2026-08", "2026-09", "2026-10", "2026-11", "2026-12"]


def test_parse_nbs_esdata_bad_json():
    d = market.parse_nbs_esdata("not json")
    assert d == {"months": [], "series": []}


def test_parse_em_rows():
    t = json.dumps({"result": {"data": [{"A": 1}, {"A": 2}]}})
    assert market.parse_em_rows(t) == [{"A": 1}, {"A": 2}]
    assert market.parse_em_rows("bad") == []
    assert market.parse_em_rows(json.dumps({"result": None})) == []


def test_parse_mexc_kline():
    t = json.dumps([
        [1787702400000, "78000", "79000", "77500", "78519.77", "1", 1787788800000, "1"],
        [1787788800000, "78519", "80500", "78500", "79015.85", "2", 1787875200000, "2"],
    ])
    out = market.parse_mexc_kline(t, n=5)
    # 1787788800000 = 2026-08-26 08:00 UTC = 16:00 北京
    assert len(out) == 2
    assert out[-1][1] == 79015.85
    assert out[0][1] == 78519.77
    assert market.parse_mexc_kline("bad") == []


def test_parse_jin10():
    t = json.dumps({"data": {"values": [
        ["2025-09-10", None, None, 0],
        ["2025-08-09", 0.1, -0.1, 0.2],
        ["2025-07-09", 0.0, 0.1, 0.0],
    ]}})
    p = market.parse_jin10(t)
    assert p == {"date": "2025-08-09", "value": 0.1, "prev": 0.2}
    assert market.parse_jin10("bad") is None
    # 全部今值为空 → None
    t2 = json.dumps({"data": {"values": [["2025-09-10", None, None, 0]]}})
    assert market.parse_jin10(t2) is None


def test_parse_mofcom_shrzgm():
    t = json.dumps([
        {"date": "202604", "tiosfs": 6245, "rmblaon": -4006},
        {"date": "202603", "tiosfs": 22000, "rmblaon": 31522},
        {"date": "202602", "tiosfs": 0, "rmblaon": 0},
    ])
    out = market.parse_mofcom_shrzgm(t, n=12)
    assert out == [("2026-03", 22000.0), ("2026-04", 6245.0)]
    assert market.parse_mofcom_shrzgm("bad") == []


def test_monthly_last():
    pairs = [("2026-01-05", 10.0), ("2026-01-06", 11.0),
             ("2026-02-03", 12.0), ("2026-02-28", 13.0)]
    out = market._monthly_last(pairs, n=2)
    assert out == [("2026-01", 11.0), ("2026-02", 13.0)]


def test_quarter_shift():
    assert market._quarter_shift("2026-06", -4) == "2025-06"
    assert market._quarter_shift("2026-03", -4) == "2025-03"
    assert market._quarter_shift("2026-09", 0) == "2026-09"
    assert market._quarter_shift("bad", -4) is None


def test_derive_macro_pmi():
    series = {
        "PMI": [49.0, 50.2, 49.2],
        "生产": [49.8, 52.5, 49.9],
        "新订单": [49.2, 51.1, 48.5],
        "产成品库存": [47.3, 48.3, 48.6],
        "采购量": [46.3, 52.1, 49.4],
        "原材料库存": [47.0, 47.0, 48.3],
    }
    d = market.derive_macro_pmi(series)
    assert abs(d["经济势能"] - (-0.1)) < 1e-9          # 48.5 - 48.6
    assert abs(d["供需差"] - 1.4) < 1e-9               # 49.9 - 48.5
    assert abs(d["备料差"] - 1.1) < 1e-9               # 49.4 - 48.3
    assert abs(d["TEC"] - (-2.9)) < 1e-9               # (48.5-51.1) - (48.6-48.3)


def test_derive_macro_pmi_missing():
    d = market.derive_macro_pmi({"PMI": [49.0]})
    assert d["经济势能"] is None
    assert d["TEC"] is None


def test_derive_macro_inflation():
    series = {"CPI同比": [0.5, 0.4, 0.6], "PPI同比": [3.5, 3.2, 2.9]}
    d = market.derive_macro_inflation(series)
    assert d["通胀预期指数"] == -2.3      # 0.6 - 2.9
    assert market.derive_macro_inflation({"CPI同比": []}) == {}


def test_derive_macro_liquidity():
    series = {"M1同比": [3.0, 4.0], "M2同比": [7.5, 7.7]}
    d = market.derive_macro_liquidity(series)
    assert d["M1-M2剪刀差"] == -3.7       # 4.0 - 7.7
    assert market.derive_macro_liquidity({"M1同比": [1.0]}) == {}


def test_derive_macro_assets():
    series = {"伦敦金": [4000.0, 4641.0], "比特币": [70000.0, 79015.0],
              "1年期LPR": [3.1, 3.0]}
    extra = {"house_yoy": -2.3, "gdp_nominal_yoy": 4.7, "gdp_real_yoy": 3.2}
    d = market.derive_macro_assets(series, extra)
    assert abs(d["金比特币"] - 4641.0 / 79015.0) < 1e-9     # 已恢复
    assert abs(d["中国实际利率"] - (3.0 - (-2.3))) < 1e-9   # 5.3
    assert abs(d["GDP平减指数"] - 1.5) < 1e-9
    # 缺房价 → 无实际利率
    d2 = market.derive_macro_assets(series, {"gdp_nominal_yoy": 4.7, "gdp_real_yoy": 3.2})
    assert "中国实际利率" not in d2


def test_parse_pbc_shrzgm():
    # 央行社融表 htm：第一列日期、第二列社融增量、第三列人民币贷款
    t = ("<html><body><table>"
         "<tr><td>项目</td><td>AFRE(flow)</td><td>RMB loans</td></tr>"
         "<tr><td>2026.06</td><td>33671</td><td>17650</td></tr>"
         "<tr><td>2026.07</td><td>14017</td><td>-5896</td></tr>"
         "<tr><td>2026.08</td><td>&nbsp;</td><td>&nbsp;</td></tr>"
         "</table></body></html>")
    out = market.parse_pbc_shrzgm(t)
    assert out == [("2026-06", 33671.0, 17650.0), ("2026-07", 14017.0, -5896.0)]
    assert market.parse_pbc_shrzgm("no table") == []


def test_elapsed_trade_minutes_lunch_break():
    # 午休 11:30-13:00 应返回 120（上午已结束），修复前 11:34 会算出 34
    from datetime import datetime
    tz = __import__("datetime").timezone(__import__("datetime").timedelta(hours=8))
    now = datetime(2026, 8, 27, 11, 34, tzinfo=tz)   # 周四午休
    assert market.elapsed_trade_minutes(now) == 120.0
    now2 = datetime(2026, 8, 27, 12, 30, tzinfo=tz)
    assert market.elapsed_trade_minutes(now2) == 120.0
    now3 = datetime(2026, 8, 27, 13, 30, tzinfo=tz)
    assert market.elapsed_trade_minutes(now3) == 150.0   # 下午 30 分钟
    now4 = datetime(2026, 8, 27, 10, 0, tzinfo=tz)
    assert market.elapsed_trade_minutes(now4) == 30.0


def test_china_release_schedule_names():
    # 发布表中国行名称与下次发布名称一致（否则"下次发布"列空白）
    sched = market.china_release_schedule()
    names = {s[0] for s in sched}
    assert "CPI同比" in names
    assert "PPI同比" in names
    assert "M1同比" in names and "M2同比" in names
    assert "社融增量" in names and "新增人民币贷款" in names
    assert "1年期LPR" in names and "PMI" in names
    # 8月27日：CPI 下次 = 09-09（发布7月数据）
    from datetime import datetime
    tz = __import__("datetime").timezone(__import__("datetime").timedelta(hours=8))
    s2 = dict((s[0], (s[1], s[2])) for s in market.china_release_schedule(
        datetime(2026, 8, 27, 12, 0, tzinfo=tz)))
    assert s2["CPI同比"][0] == "09-09"
    assert "7月数据" in s2["CPI同比"][1]
    assert s2["PMI"][0] == "09-01"


def test_macro_constants():
    assert market.MACRO_MONTHS == 12
    assert market.MACRO_COMMODITY_DAYS == 5
    assert len(market.NBS_PMI_IDS) == 6
    assert len(market.MACRO_SECTIONS) >= 5


def test_new_macro_state_shape():
    s = market._new_macro_state()
    assert s["ok"] is True
    assert "pmi" in s and "inflation" in s and "liquidity" in s
    assert "assets" in s and "us" in s and "commodity" in s
    assert s["errors"] == []


def test_merge_macro_sections():
    out = market._new_macro_state()
    market._merge_macro(out, "macro_pmi", {"months": ["2026-07"], "series": {"PMI": [49.2]},
                                            "sources": {"国家统计局": True}})
    assert out["pmi"]["series"]["PMI"] == [49.2]
    assert out["sources"]["国家统计局"] is True
    market._merge_macro(out, "macro_usdata", {"us": [{"date": "2026-09-11"}]})
    assert out["us"] == [{"date": "2026-09-11"}]
    market._merge_macro(out, "macro_pmi", {"errors": ["PMI：x"]})
    assert "PMI：x" in out["errors"]
