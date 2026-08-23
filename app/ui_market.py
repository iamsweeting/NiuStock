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
        self._hist_rows = {k: [] for k in _HIST_FIELDS}

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
    # 刷新（渐进式：先出骨架，各小节并行抓取完成后逐块填充）
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
        self._build_skeleton()

        def on_section(key, data):
            # 工作线程回调 → 切回 UI 线程填充对应小节
            Clock.schedule_once(lambda dt, k=key, d=data: self._on_section(k, d), 0)

        def on_done(data):
            Clock.schedule_once(lambda dt: self._on_done(data), 0)

        threading.Thread(
            target=lambda: market.refresh_market_progressive(on_section, on_done),
            daemon=True).start()

    def _build_skeleton(self):
        """先渲染固定表格骨架 + 「查询中…」占位，保证首屏立刻可见。"""
        self.ts_label.text = "更新于：刷新中…"
        self.turnover_label.text = "两市成交额：查询中…"
        self.median_label.text = "沪深300中位数：查询中…"

        # 指数/品种表格：表头 + 占位行
        self.quotes_box.clear_widgets()
        self.quotes_box.add_widget(self._head_row([
            ("名称", 0.46), ("最新", 0.30), ("涨跌%", 0.24)]))
        self.quotes_box.add_widget(self._row([("查询中…", _HINT, 1.0)]))

        # 历史：六个小节各自「标题 + 占位行」
        self.hist_box.clear_widgets()
        for title in _HIST_TITLES:
            self.hist_box.add_widget(MDLabel(
                text=title, font_style="Caption", bold=True,
                theme_text_color="Custom", text_color=_GREY, adaptive_height=True,
            ))
            self.hist_box.add_widget(self._row([("查询中…", _HINT, 1.0)]))
        self.error_label.text = ""

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------
    def _on_section(self, key, data):
        """按小节增量填充。"""
        try:
            if key == "live_sina":
                self._render_turnover(data)
                self._render_quotes(data.get("quotes", []))
            elif key == "live_yahoo":
                self._render_quotes(data.get("quotes", []))
            elif key == "live_median":
                self._render_median(data)
            elif key == "hist_kr":
                kr = data.get("kr", {})
                if kr.get("三星电子"):
                    self._render_hist_field("kr_三星电子", kr["三星电子"])
                if kr.get("SK海力士"):
                    self._render_hist_field("kr_SK海力士", kr["SK海力士"])
            elif key in _SECTION_TO_FIELD:
                field = _SECTION_TO_FIELD[key]
                self._render_hist_field(field, data.get(field, []))
        except Exception:  # noqa: BLE001
            pass

    def _on_done(self, data):
        self._busy = False
        self.refresh_btn.disabled = False
        self._last_refresh = time.monotonic()
        self._last_ts = data.get("ts", "—")
        self.ts_label.text = "更新于：%s" % self._last_ts
        live = data.get("live", {})
        hist = data.get("history", {})
        errs = list(live.get("errors", [])) + list(hist.get("errors", []))
        self.error_label.text = ("\n".join("· %s" % e for e in errs[:6])
                                 if errs else "")

    def _render_turnover(self, live):
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

    def _render_quotes(self, quotes):
        # 指数/品种表格：与骨架表头对齐，逐行填充
        if not quotes:
            return
        self.quotes_box.clear_widgets()
        self.quotes_box.add_widget(self._head_row([
            ("名称", 0.46), ("最新", 0.30), ("涨跌%", 0.24)]))
        for q in quotes:
            color = _RED if q["pct"] >= 0 else _GREEN
            self.quotes_box.add_widget(self._row([
                (q["name"], _GREY, 0.46),
                ("%.2f" % q["price"] if q["price"] >= 10 else "%.3f" % q["price"],
                 _WHITE, 0.30),
                ("%s%.2f%%" % ("+" if q["pct"] >= 0 else "", q["pct"]),
                 color, 0.24),
            ]))

    def _render_median(self, live):
        # 沪深300中位数（价格 + 乐咕乐股中位数PE）
        med = live.get("csi300_median")
        pe = live.get("hs300_median_pe")
        med_parts = ["沪深300中位数：%s 元" % ("%.2f" % med if med else "—")]
        if pe:
            med_parts.append("中位数PE(TTM)：%s（乐咕乐股）" % ("%.2f" % pe if pe else "—"))
        self.median_label.text = "  ·  ".join(med_parts)

    def _render_hist_field(self, key, rows):
        """把单个历史小节替换为实际数据（标题 + 表头 + 数值行）。"""
        # 重建整个历史区（小节少、行数少，重建代价可忽略）
        fields = {k: self._hist_rows.get(k, []) for k in _HIST_FIELDS}
        fields[key] = rows
        self._hist_rows = fields
        self.hist_box.clear_widgets()
        for fk in _HIST_FIELDS:
            self._hist_section(_HIST_TITLES[fk], fields[fk],
                               fmt=_HIST_FMT[fk])

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


_HIST_TITLES = {
    "turnover": "两市成交额（亿元）",
    "ccpr": "美元兑人民币中间价",
    "wti": "WTI原油（美元/桶）",
    "xau": "伦敦金（美元/盎司）",
    "kr_三星电子": "韩国半导体 · 三星电子（韩元）",
    "kr_SK海力士": "韩国半导体 · SK海力士（韩元）",
}
_HIST_FIELDS = {
    "turnover": "turnover",
    "ccpr": "ccpr",
    "wti": "wti",
    "xau": "xau",
    "kr_三星电子": "三星电子",
    "kr_SK海力士": "SK海力士",
}
_SECTION_TO_FIELD = {
    "hist_turnover": "turnover",
    "hist_ccpr": "ccpr",
    "hist_wti": "wti",
    "hist_xau": "xau",
}
_HIST_FMT = {
    "turnover": lambda v: "%.0f" % v,
    "ccpr": lambda v: "%.4f" % v,
    "wti": lambda v: "%.2f" % v,
    "xau": lambda v: "%.2f" % v,
    "kr_三星电子": lambda v: "%.0f" % v,
    "kr_SK海力士": lambda v: "%.0f" % v,
}
