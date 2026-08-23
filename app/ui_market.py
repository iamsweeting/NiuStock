# -*- coding: utf-8 -*-
"""牛票 · 大盘信息页（表格化）。

需求：
  一、本日实时（页面切换前自动刷新，TTL 冷却 + 请求节流，避免反爬）
  二、历史（近 5 个交易日）
布局全部使用固定行高的行式表格，避免自适应高度叠加错乱；
有数值就显示，查不到/没有数据时以"—"或"暂无数据"标识。
"""
import threading
import time

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.utils import get_color_from_hex

from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDRaisedButton
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel

from . import market

_RED = get_color_from_hex("#ef5350")
_GREEN = get_color_from_hex("#66bb6a")
_WHITE = (1, 1, 1, 1.0)
_GREY = (0.72, 0.74, 0.78, 1.0)
_HINT = (0.55, 0.60, 0.68, 1.0)
_CARD_RADIUS = [dp(12), dp(12), dp(12), dp(12)]
_ROW_H = 32


class MarketPage:
    """大盘信息功能页。"""

    def __init__(self, app):
        self.app = app
        self._busy = False
        self._last_refresh = 0.0

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------
    def build(self, box):
        head = MDBoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(44), spacing=dp(8),
        )
        self.ts_label = MDLabel(
            text="更新于：—", font_style="Caption",
            theme_text_color="Hint", adaptive_height=True, size_hint_x=1,
            valign="middle",
        )
        self.refresh_btn = MDRaisedButton(
            text="刷新", size_hint=(None, None), width=dp(72), height=dp(34),
        )
        self.refresh_btn.elevation = 0
        self.refresh_btn.bind(on_release=lambda x: self.refresh(force=True))
        head.add_widget(self.ts_label)
        head.add_widget(self.refresh_btn)
        box.add_widget(head)

        box.add_widget(MDLabel(
            text="切换页面时自动刷新（间隔 ≥%d 秒，低请求量防反爬）" % market.REFRESH_TTL,
            font_style="Caption", theme_text_color="Hint", adaptive_height=True,
        ))

        # 一、本日实时
        box.add_widget(self._title("一、本日实时"))
        self.turnover_card = self._make_card()
        self.turnover_label = MDLabel(
            text="两市成交额：—", markup=True, font_style="Body1",
            adaptive_height=True,
        )
        self.turnover_card.add_widget(self.turnover_label)
        box.add_widget(self.turnover_card)

        self.quotes_box = MDBoxLayout(
            orientation="vertical", spacing=dp(2), adaptive_height=True,
        )
        box.add_widget(self.quotes_box)

        self.median_card = self._make_card()
        self.median_label = MDLabel(
            text="沪深300中位数：—", font_style="Body1", adaptive_height=True,
        )
        self.median_card.add_widget(self.median_label)
        box.add_widget(self.median_card)

        # 二、历史
        box.add_widget(self._title("二、历史（近 5 个交易日）"))
        self.hist_box = MDBoxLayout(
            orientation="vertical", spacing=dp(2), adaptive_height=True,
        )
        box.add_widget(self.hist_box)

        self.error_label = MDLabel(
            text="", markup=True, font_style="Caption",
            theme_text_color="Custom", text_color=_HINT, adaptive_height=True,
        )
        box.add_widget(self.error_label)

    @staticmethod
    def _title(text):
        return MDLabel(
            text=text, font_style="Subtitle1", bold=True,
            adaptive_height=True, theme_text_color="Custom",
            text_color=_WHITE,
        )

    @staticmethod
    def _make_card():
        card = MDCard(
            orientation="vertical", padding=[dp(12), dp(8), dp(12), dp(8)],
            radius=_CARD_RADIUS, elevation=0, size_hint_y=None,
        )
        # 关键：卡片高度随内容自适应，避免与相邻表格/卡片重叠
        card.bind(minimum_height=card.setter("height"))
        return card

    @staticmethod
    def _row(cells, height=_ROW_H):
        """cells: [(text, color, size_hint_x)] → 固定行高的行。"""
        r = BoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(height),
            spacing=dp(4),
        )
        for text, color, sx in cells:
            r.add_widget(MDLabel(
                text=text, adaptive_height=True, size_hint_x=sx,
                theme_text_color="Custom", text_color=color,
                halign="left", valign="middle",
                font_style="Body2",
            ))
        return r

    def _head_row(self, cols):
        return self._row([(c, _HINT, sx) for c, sx in cols])

    # ------------------------------------------------------------------
    # 刷新
    # ------------------------------------------------------------------
    def refresh_if_stale(self):
        if time.monotonic() - self._last_refresh >= market.REFRESH_TTL:
            self.refresh(force=True)

    def refresh(self, force=False):
        if self._busy:
            return
        now = time.monotonic()
        if not force and hasattr(self, "_last_ts") and \
                now - self._last_refresh < market.REFRESH_TTL:
            self.ts_label.text = "更新于：%s（已是最新）" % self._last_ts
            return
        self._busy = True
        self.refresh_btn.disabled = True
        self._set_placeholder()

        def work():
            data = market.refresh_market()
            Clock.schedule_once(lambda dt: self._on_data(data), 0)

        threading.Thread(target=work, daemon=True).start()

    def _set_placeholder(self):
        self.turnover_label.text = "两市成交额：刷新中…"
        self.median_label.text = "沪深300中位数：刷新中…"
        self.quotes_box.clear_widgets()
        self.hist_box.clear_widgets()
        self.error_label.text = ""

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------
    def _on_data(self, data):
        self._busy = False
        self.refresh_btn.disabled = False
        self._last_refresh = time.monotonic()
        self._last_ts = data.get("ts", "—")
        self.ts_label.text = "更新于：%s" % self._last_ts

        live = data.get("live", {})
        # 两市成交额 + 本日预测额
        t = live.get("turnover_yi")
        p = live.get("turnover_pred_yi")
        parts = []
        if t:
            parts.append("两市成交额：[color=%s]%.0f[/color] 亿" % (_hex(_RED), t))
        else:
            parts.append("两市成交额：—")
        if p:
            parts.append("本日预测额：[color=%s]%.0f[/color] 亿" % (_hex(_GREEN), p))
            parts.append("（已交易 %d 分钟外推）" % int(market.elapsed_trade_minutes()))
        elif t:
            parts.append("本日预测额：—")
        self.turnover_label.text = "  ·  ".join(parts)

        # 指数/品种表格
        self.quotes_box.clear_widgets()
        self.quotes_box.add_widget(self._head_row([
            ("名称", 0.46), ("最新", 0.30), ("涨跌%", 0.24)]))
        quotes = live.get("quotes", [])
        if quotes:
            for q in quotes:
                color = _RED if q["pct"] >= 0 else _GREEN
                self.quotes_box.add_widget(self._row([
                    (q["name"], _GREY, 0.46),
                    ("%.2f" % q["price"] if q["price"] >= 10 else "%.3f" % q["price"],
                     _WHITE, 0.30),
                    ("%s%.2f%%" % ("+" if q["pct"] >= 0 else "", q["pct"]),
                     color, 0.24),
                ]))
        else:
            self.quotes_box.add_widget(self._row([("暂无行情数据", _HINT, 1.0)]))

        # 沪深300中位数（价格 + 乐咕乐股中位数PE）
        med = live.get("csi300_median")
        pe = live.get("hs300_median_pe")
        med_parts = ["沪深300中位数：%s 元" % ("%.2f" % med if med else "—")]
        if pe:
            med_parts.append("中位数PE(TTM)：%s（乐咕乐股）" % ("%.2f" % pe if pe else "—"))
        self.median_label.text = "  ·  ".join(med_parts)

        # 历史（表格化）
        hist = data.get("history", {})
        self.hist_box.clear_widgets()
        self._hist_section("两市成交额（亿元）", hist.get("turnover", []),
                           fmt=lambda v: "%.0f" % v)
        self._hist_section("美元兑人民币中间价", hist.get("ccpr", []),
                           fmt=lambda v: "%.4f" % v)
        self._hist_section("WTI原油（美元/桶）", hist.get("wti", []),
                           fmt=lambda v: "%.2f" % v)
        self._hist_section("伦敦金（美元/盎司）", hist.get("xau", []),
                           fmt=lambda v: "%.2f" % v)
        kr = hist.get("kr", {})
        self._hist_section("韩国半导体 · 三星电子（韩元）", kr.get("三星电子", []),
                           fmt=lambda v: "%.0f" % v)
        self._hist_section("韩国半导体 · SK海力士（韩元）", kr.get("SK海力士", []),
                           fmt=lambda v: "%.0f" % v)

        errs = list(live.get("errors", [])) + list(hist.get("errors", []))
        self.error_label.text = ("\n".join("· %s" % e for e in errs[:6])
                                 if errs else "")

    def _hist_section(self, title, rows, fmt):
        self.hist_box.add_widget(MDLabel(
            text=title, font_style="Caption", bold=True,
            theme_text_color="Custom", text_color=_GREY, adaptive_height=True,
        ))
        if not rows:
            self.hist_box.add_widget(self._row([("暂无数据", _HINT, 1.0)]))
            return
        self.hist_box.add_widget(self._head_row([("日期", 0.5), ("数值", 0.5)]))
        for d, v in rows:
            self.hist_box.add_widget(self._row([
                (d[5:] if len(d) > 5 else d, _GREY, 0.5),
                (fmt(v), _WHITE, 0.5),
            ]))


def _hex(col):
    return "#%02x%02x%02x" % (int(col[0] * 255), int(col[1] * 255), int(col[2] * 255))
