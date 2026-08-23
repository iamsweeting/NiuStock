# -*- coding: utf-8 -*-
"""统一数据源聚合逻辑单元测试（按日/按周/盘中回退，不访问网络）。"""
from datetime import date, datetime, time, timezone, timedelta

import pytest

from app import api, config


def _rows(days):
    """按日期列表构造升序日K行（日期为 'YYYY-MM-DD' 字符串）。"""
    out = []
    for d in days:
        out.append({
            "date": d.strftime("%Y-%m-%d"),
            "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5,
            "volume": 1000.0, "amount": None,
        })
    return out


def _weekdays(start, n):
    out = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


# --------------------------------------------------------------------------
# 按日聚合
# --------------------------------------------------------------------------

def test_aggregate_daily_exact_date():
    days = _weekdays(date(2026, 1, 5), 10)
    rows = _rows(days)
    res = api.aggregate_pivot(rows, days[5], weekly=False)
    assert res["calc_date"] == days[5].strftime("%Y-%m-%d")
    assert res["high"] == 11.0 and res["low"] == 9.0 and res["close"] == 10.5
    assert res["verify_mode"] == "next_day"
    assert res["verify_date"] == days[6].strftime("%Y-%m-%d")
    assert res["adjusted"] is False


def test_aggregate_daily_fallback_to_previous():
    days = _weekdays(date(2026, 1, 5), 10)
    rows = _rows(days)
    # 目标日无数据（周六）→ 取之前最近交易日
    sat = days[4] + timedelta(days=1)   # 1/9(五)+1 = 1/10(六)
    assert sat.weekday() == 5
    res = api.aggregate_pivot(rows, sat, weekly=False)
    assert res["calc_date"] == days[4].strftime("%Y-%m-%d")


def test_aggregate_daily_skip_today_intraday():
    days = _weekdays(date(2026, 1, 5), 6)   # 周一~周六中的前5个工作日
    rows = _rows(days)
    target = days[-1]
    res = api.aggregate_pivot(rows, target, weekly=False, skip_today=True)
    assert res["adjusted"] is True
    assert res["calc_date"] == days[-2].strftime("%Y-%m-%d")  # 回退到上一收盘日
    assert res["verify_date"] == days[-1].strftime("%Y-%m-%d")  # 验证数据=被跳过的那天


def test_aggregate_daily_no_data_returns_none():
    rows = _rows(_weekdays(date(2026, 1, 5), 3))
    assert api.aggregate_pivot(rows, date(2020, 1, 1)) is None


# --------------------------------------------------------------------------
# 按周聚合
# --------------------------------------------------------------------------

def test_aggregate_weekly():
    # 构造跨周末的两周数据：1/5(一)~1/9(五)，1/12(一)~1/16(五)
    days = _weekdays(date(2026, 1, 5), 10)
    rows = _rows(days)
    # 目标=周四 1/8：计算周=其所在自然周 1/5~1/9
    target = days[3]
    res = api.aggregate_pivot(rows, target, weekly=True)
    assert res["calc_date"].startswith(days[0].strftime("%m-%d"))  # 周一 1/5
    assert res["calc_date"].endswith(days[4].strftime("%m-%d"))    # 周五 1/9
    assert res["high"] == 11.0 and res["low"] == 9.0
    assert res["verify_mode"] == "next_week"
    # 验证周 = 下一自然周：首个验证日为下周一 1/12
    assert res["verify_date"].startswith(days[5].strftime("%m-%d"))
    assert res["verify_date"].endswith(days[9].strftime("%m-%d"))  # 下周五 1/16


def test_aggregate_weekly_midweek_target_uses_calendar_week():
    # 目标=周三：计算周仍是所在自然周（周一~周五），验证周为下一自然周
    days = _weekdays(date(2026, 1, 5), 10)
    rows = _rows(days)
    target = days[2]  # 1/7 周三
    res = api.aggregate_pivot(rows, target, weekly=True)
    assert res["calc_date"].startswith(days[0].strftime("%m-%d"))  # 1/5
    assert res["calc_date"].endswith(days[4].strftime("%m-%d"))    # 1/9
    assert res["verify_mode"] == "next_week"
    assert res["verify_date"].startswith(days[5].strftime("%m-%d"))  # 1/12


def test_aggregate_weekly_next_week_missing_falls_to_latest():
    # 目标在最后一周内：下一自然周无数据 → 回退最新交易日
    days = _weekdays(date(2026, 1, 5), 5)   # 只有 1/5~1/9 一周
    rows = _rows(days)
    target = days[3]  # 1/8 周四
    res = api.aggregate_pivot(rows, target, weekly=True)
    assert res["verify_mode"] == "latest"
    assert res["verify_date"] == days[4].strftime("%Y-%m-%d")  # 1/9


# --------------------------------------------------------------------------
# 交易时段判断
# --------------------------------------------------------------------------

def test_is_trading_session():
    tz = timezone(timedelta(hours=8))
    # 周一 10:00 北京 → True
    assert api.is_trading_session(datetime(2026, 1, 5, 10, 0, tzinfo=tz)) is True
    # 周一 8:00 → False
    assert api.is_trading_session(datetime(2026, 1, 5, 8, 0, tzinfo=tz)) is False
    # 周一 15:30 → False（收盘后）
    assert api.is_trading_session(datetime(2026, 1, 5, 15, 30, tzinfo=tz)) is False
    # 周六 → False
    assert api.is_trading_session(datetime(2026, 1, 10, 10, 0, tzinfo=tz)) is False


# --------------------------------------------------------------------------
# 数据源链配置
# --------------------------------------------------------------------------

def test_source_chain_order():
    assert config.PIVOT_SOURCE_CHAIN == (config.SOURCE_TENCENT, config.SOURCE_SINA)
