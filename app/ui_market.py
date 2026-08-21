# -*- coding: utf-8 -*-
"""牛票 · 大盘信息页。

需求：
  一、本日实时（页面切换前自动刷新，TTL 冷却 + 请求节流，避免反爬）
  二、历史（近 5 个交易日）
"""
import threading
import time

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.utils import get_color_from_hex

from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDRaisedButton
from kivymd.uix.card import MDCard
from kivymd.uix.gridlayout import MDGridLayout
from kivymd.uix.label import MDLabel

from . import market

_RED = get_color_from_hex("#ef5350")
_GREEN = get_color_from_hex("#66bb6a")
_GREY = (0.72, 0.74, 0.78, 1.0)
_HINT = (0.55, 0.60, 0.68, 1.0)
_CARD_RADIUS = [dp(12), dp(12), dp(12), dp(12)]


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
        # 头部：更新时间 + 手动刷新
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
        box.add_widget(MDLabel(
            text="一、本日实时", font_style="Subtitle1", bold=True,
            adaptive_height=True, theme_text_color="Custom",
            text_color=(1, 1, 1, 1),
        ))
        self.turnover_card = self._make_card()
        self.turnover_label = MDLabel(
            text="两市成交额：—", markup=True, font_style="Body1", adaptive_height=True,
        )
        self.turnover_card.add_widget(self.turnover_label)
        box.add_widget(self.turnover_card)

        self.quotes_grid = MDGridLayout(
            cols=2, spacing=dp(8), adaptive_height=True, padding=[0, 0, 0, dp(4)],
        )
        box.add_widget(self.quotes_grid)

        self.median_card = self._make_card()
        self.median_label = MDLabel(
            text="沪深300中位数：—", font_style="Body1", adaptive_height=True,
        )
        self.median_card.add_widget(self.median_label)
        box.add_widget(self.median_card)

        # 二、历史
        box.add_widget(MDLabel(
            text="二、历史（近 5 个交易日）", font_style="Subtitle1", bold=True,
            adaptive_height=True, theme_text_color="Custom",
            text_color=(1, 1, 1, 1),
        ))
        self.hist_card = self._make_card()
        self.hist_label = MDLabel(
            text="—", markup=True, font_style="Body2",
            theme_text_color="Secondary", adaptive_height=True,
        )
        self.hist_card.add_widget(self.hist_label)
        box.add_widget(self.hist_card)

        self.error_label = MDLabel(
            text="", markup=True, font_style="Caption",
            theme_text_color="Custom", text_color=_HINT, adaptive_height=True,
        )
        box.add_widget(self.error_label)

        # 首次进入页面时由外壳 on_switch_tabs 触发刷新（不在启动时抢网络）

    @staticmethod
    def _make_card():
        return MDCard(
            orientation="vertical", padding=[dp(12), dp(8), dp(12), dp(8)],
            radius=_CARD_RADIUS, elevation=0, size_hint_y=None,
        )

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
        self._set_placeholder("刷新中…")

        def work():
            data = market.refresh_market()
            Clock.schedule_once(lambda dt: self._on_data(data), 0)

        threading.Thread(target=work, daemon=True).start()

    def _set_placeholder(self, text):
        self.turnover_label.text = text
        self.median_label.text = text
        self.hist_label.text = text
        self.quotes_grid.clear_widgets()
        self.error_label.text = ""

    def _on_data(self, data):
        self._busy = False
        self.refresh_btn.disabled = False
        self._last_refresh = time.monotonic()
        self._last_ts = data.get("ts", "—")
        self.ts_label.text = "更新于：%s" % self._last_ts

        live = data.get("live", {})
        # 成交额 + 预测
        t = live.get("turnover_yi")
        p = live.get("turnover_pred_yi")
        parts = []
        if t:
            parts.append("两市成交额：[color=%s]%.0f[/color] 亿" % (_hex(_RED), t))
        else:
            parts.append("两市成交额：—")
        if p:
            parts.append("本日预测额：[color=%s]%.0f[/color] 亿" % (_hex(_GREEN), p))
            el = market.elapsed_trade_minutes()
            parts.append("（已交易 %d 分钟，线性外推）" % int(el))
        elif t:
            parts.append("本日预测额：—（非交易时段）")
        self.turnover_label.text = "  ".join(parts)

        # 指数/品种网格
        self.quotes_grid.clear_widgets()
        for q in live.get("quotes", []):
            color = _RED if q["pct"] >= 0 else _GREEN
            cell = self._make_card()
            cell.add_widget(MDLabel(
                text=q["name"], font_style="Body2", adaptive_height=True,
                theme_text_color="Secondary",
            ))
            cell.add_widget(MDLabel(
                text="%.2f" % q["price"] if q["price"] >= 10 else "%.3f" % q["price"],
                font_style="H6", adaptive_height=True,
                theme_text_color="Custom", text_color=(1, 1, 1, 1),
            ))
            cell.add_widget(MDLabel(
                text="%s%.2f%%" % ("+" if q["pct"] >= 0 else "", q["pct"]),
                font_style="Caption", adaptive_height=True,
                theme_text_color="Custom", text_color=color,
            ))
            self.quotes_grid.add_widget(cell)
        if not live.get("quotes"):
            self.quotes_grid.add_widget(MDLabel(
                text="（实时行情获取失败）", adaptive_height=True,
                theme_text_color="Hint",
            ))

        # 沪深300中位数（价格中位数 + 乐咕乐股中位数PE）
        med = live.get("csi300_median")
        pe = live.get("hs300_median_pe")
        med_parts = ["沪深300中位数：%s 元" % ("%.2f" % med if med else "—")]
        if pe:
            med_parts.append("中位数PE(TTM)：%s（乐咕乐股）" % ("%.2f" % pe if pe else "—"))
        self.median_label.text = "  ·  ".join(med_parts)

        # 历史
        hist = data.get("history", {})
        lines = []
        lines.append("【两市成交额】" + self._rows_text(
            hist.get("turnover", []), fmt=lambda v: "%.0f亿" % v))
        lines.append("【美元兑人民币中间价】" + self._rows_text(
            hist.get("ccpr", []), fmt=lambda v: "%.4f" % v))
        lines.append("【WTI原油(美元/桶)】" + self._rows_text(
            hist.get("wti", []), fmt=lambda v: "%.2f" % v))
        lines.append("【伦敦金(美元/盎司)】" + self._rows_text(
            hist.get("xau", []), fmt=lambda v: "%.2f" % v))
        kr = hist.get("kr", {})
        for label, rows in (("三星电子", kr.get("三星电子", [])),
                            ("SK海力士", kr.get("SK海力士", []))):
            lines.append("【韩国半导体 · %s】(韩元)" % label + self._rows_text(
                rows, fmt=lambda v: "%.0f" % v))
        self.hist_label.text = "\n".join(lines)

        errs = list(live.get("errors", [])) + list(hist.get("errors", []))
        self.error_label.text = ("\n".join("· %s" % e for e in errs[:6])
                                 if errs else "")

    @staticmethod
    def _rows_text(rows, fmt):
        if not rows:
            return " 无数据"
        return "  " + "  ".join("%s %s" % (d[5:] if len(d) > 5 else d, fmt(v))
                                for d, v in rows)


def _hex(col):
    return "#%02x%02x%02x" % (int(col[0] * 255), int(col[1] * 255), int(col[2] * 255))
