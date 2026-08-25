# -*- coding: utf-8 -*-
"""数据解析与版本识别单元测试（不访问网络，仅验证解析逻辑）。"""
import json

import pytest

from app import api, config


# --------------------------------------------------------------------------
# normalize_code / detect_version
# --------------------------------------------------------------------------

def test_normalize_code():
    assert api.normalize_code("600519") == "sh600519"
    assert api.normalize_code("000001") == "sz000001"
    assert api.normalize_code("200011") == "sz200011"   # 深市 B 股
    assert api.normalize_code("300750") == "sz300750"
    assert api.normalize_code("688981") == "sh688981"
    assert api.normalize_code(" 600519 ") == "sh600519"
    assert api.normalize_code("sh000852") == "sh000852"
    assert api.normalize_code("SH.000852") == "sh000852"
    assert api.normalize_code("HSTECH") == "hstech"
    assert api.normalize_code("hk00700") == "hk00700"
    assert api.normalize_code("usAAPL") == "usaapl"


def test_normalize_code_empty_raises():
    with pytest.raises(ValueError):
        api.normalize_code("")
    with pytest.raises(ValueError):
        api.normalize_code("   ")


def test_detect_version():
    assert api.detect_version("sh000852") == config.VERSION_INDEX   # 中证1000
    assert api.detect_version("sh000001") == config.VERSION_INDEX   # 上证指数
    assert api.detect_version("sz399006") == config.VERSION_INDEX   # 创业板指
    assert api.detect_version("sz399001") == config.VERSION_INDEX   # 深证成指
    assert api.detect_version("sh600519") == config.VERSION_STOCK   # 贵州茅台
    assert api.detect_version("sz000001") == config.VERSION_STOCK   # 平安银行
    assert api.detect_version("sz300750") == config.VERSION_STOCK   # 宁德时代
    assert api.detect_version("bj430047") == config.VERSION_STOCK   # 北交所
    assert api.detect_version("hstech") == config.VERSION_BASIC     # 海外英文代码
    assert api.detect_version("hk00700") == config.VERSION_BASIC    # 港股
    assert api.detect_version("usaapl") == config.VERSION_BASIC    # 美股


# --------------------------------------------------------------------------
# 腾讯 K 线解析
# --------------------------------------------------------------------------

def _tencent_payload(key, rows, qt_fields=None):
    return json.dumps({
        "code": 0,
        "msg": "",
        "data": {
            "sh000852": {
                key: rows,
                "qt": {"sh000852": qt_fields or ["1", "中证1000", "000852", "0"]},
            }
        },
    }, ensure_ascii=False)


TENCENT_A = _tencent_payload("qfqday", [
    ["2024-01-02", "100", "102", "103", "99", "1000"],
    ["2024-01-03", "102", "101", "104", "100", "1200"],
    ["2024-01-04", "101", "105", "106", "100.5", "1500"],
])


def test_parse_tencent_format_a():
    res = api.parse_tencent(TENCENT_A)
    assert res["name"] == "中证1000"
    assert res["code_key"] == "sh000852"
    r0 = res["rows"][0]
    assert r0["date"] == "2024-01-02"
    assert r0["open"] == 100.0
    assert r0["close"] == 102.0
    assert r0["high"] == 103.0
    assert r0["low"] == 99.0
    assert r0["volume"] == 1000.0
    assert len(res["rows"]) == 3


def test_parse_tencent_format_b_autodetect():
    # 行序 B：[日期, 开, 高, 低, 收, 量] —— 按 A 解析会破坏 OHLC 合理性，应自动识别
    payload = _tencent_payload("day", [
        ["2024-01-02", "100", "102", "98", "101", "1000"],
        ["2024-01-03", "101", "103", "99", "102", "1100"],
    ])
    res = api.parse_tencent(payload)
    r0 = res["rows"][0]
    assert r0["open"] == 100.0
    assert r0["high"] == 102.0
    assert r0["low"] == 98.0
    assert r0["close"] == 101.0


def test_parse_tencent_amount_field():
    payload = _tencent_payload("qfqday", [
        ["2024-01-02", "100", "102", "103", "99", "1000", "9000000"],
        ["2024-01-03", "102", "101", "104", "100", "1200", "500"],  # 不合理的额被忽略
    ])
    res = api.parse_tencent(payload)
    assert res["rows"][0]["amount"] == 9000000.0
    assert res["rows"][1]["amount"] is None


def test_parse_tencent_newfqkline_amount_wan():
    # newfqkline 格式：第 8 字段为当日成交额(万元) → 换算成元（×1e4）
    payload = _tencent_payload("qfqday", [
        ["2024-01-02", "100", "102", "103", "99", "1000", {}, "0.2", "999.5", ""],
        ["2024-01-03", "102", "101", "104", "100", "1200", {}, "0.3", "0.01", ""],  # 过小被忽略
    ])
    res = api.parse_tencent(payload)
    assert res["rows"][0]["amount"] == 999.5 * 1e4   # 万元 → 元
    assert res["rows"][1]["amount"] is None


def test_parse_tencent_bad_response():
    with pytest.raises(Exception):
        api.parse_tencent('{"code": -1}')
    with pytest.raises(Exception):
        api.parse_tencent('{"code": 0, "data": {}}')


def test_parse_tencent_numeric_date():
    # 兼容 8 位数字日期格式
    payload = _tencent_payload("day", [
        ["20240102", "100", "102", "103", "99", "1000"],
    ])
    res = api.parse_tencent(payload)
    assert res["rows"][0]["date"] == "2024-01-02"


# --------------------------------------------------------------------------
# 新浪 K 线解析
# --------------------------------------------------------------------------

SINA_JSONP = (
    'var _=(['
    '{"day":"2024-01-02","open":"100.0","high":"103.0","low":"99.0",'
    '"close":"102.0","volume":"1000"},'
    '{"day":"2024-01-03","open":"102.0","high":"104.0","low":"100.0",'
    '"close":"101.0","volume":"1200"}'
    ']);'
)


def test_parse_sina():
    res = api.parse_sina(SINA_JSONP)
    assert len(res["rows"]) == 2
    r0 = res["rows"][0]
    assert r0["date"] == "2024-01-02"
    assert r0["open"] == 100.0
    assert r0["high"] == 103.0
    assert r0["low"] == 99.0
    assert r0["close"] == 102.0
    assert r0["volume"] == 1000.0
    assert r0["amount"] is None


def test_parse_sina_bad():
    with pytest.raises(Exception):
        api.parse_sina("var _=(not json);")
