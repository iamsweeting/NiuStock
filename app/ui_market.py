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
_HIST_TITLE_COLOR = get_color_from_hex("#8ab4f8")   # 历史小节标题：浅蓝区分
_CARD_RADIUS = [dp(12), dp(12), dp(12), dp(12)]
_ROW_H = 32


class MarketPage:
    """大盘信息功能页。"""

    def __init__(self, app):
        self.app = app
        self._busy = False
        self._last_refresh = 0.0
        self._hist_rows = {k: [] for k in _HIST_FIELDS}
        self._quotes = []

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

        # 二、历史
        box.add_widget(self._title("二、历史（近 5 个交易日）"))
        self.hist_box = MDBoxLayout(
            orientation="vertical", spacing=dp(2), adaptive_height=True,
        )
        box.add_widget(self.hist_box)

        # 三、沪深300中位数
        box.add_widget(self._title("三、沪深300中位数"))
        self.median_card = self._make_card()
        self.median_label = MDLabel(
            text="沪深300中位数：—", font_style="Body1", adaptive_height=True,
        )
        self.median_card.add_widget(self.median_label)
        box.add_widget(self.median_card)

        # 四、财经消息（重大：半导体/金融/千亿级，序号【01】蓝色链接+标题，需求）
        box.add_widget(self._title("四、财经消息"))
        self.news_card = self._make_card()
        self.news_label = MDLabel(
            text="查询中…", markup=True, font_style="Body2",
            adaptive_height=True, theme_text_color="Custom", text_color=_GREY,
        )
        self.news_label.bind(on_ref_press=self._open_news_link)
        self.news_card.add_widget(self.news_label)
        box.add_widget(self.news_card)

        self.error_label = MDLabel(
            text="", markup=True, font_style="Caption",
            theme_text_color="Custom", text_color=_HINT, adaptive_height=True,
        )
        box.add_widget(self.error_label)

    @staticmethod
    def _open_news_link(instance, ref):
        """点击新闻标题 → 打开详情链接（隐式链接，不显示网址）。"""
        try:
            import webbrowser
            url = ref
            if url and url.startswith("http"):
                webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass

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
        self._quotes = []
        self.ts_label.text = "更新于：刷新中…"
        self.turnover_label.text = "两市成交额：查询中…"
        self.median_label.text = "沪深300中位数：查询中…"
        self.news_card.clear_widgets()
        self.news_card.spacing = 0
        self.news_card.add_widget(MDLabel(
            text="查询中…", font_style="Body2",
            theme_text_color="Custom", text_color=_GREY, adaptive_height=True,
        ))

        # 指数/品种表格：表头 + 占位行
        self.quotes_box.clear_widgets()
        self.quotes_box.add_widget(self._head_row([
            ("名称", 0.46), ("最新", 0.30), ("涨跌%", 0.24)]))
        self.quotes_box.add_widget(self._row([("查询中…", _HINT, 1.0)]))

        # 历史：各小节「标题 + 占位行」（大宗商品合并为一张表）
        self.hist_box.clear_widgets()
        for fk, title in _HIST_TITLES.items():
            if fk in ("wti", "xau", "btc"):
                continue
            self.hist_box.add_widget(self._hist_title(title))
            self.hist_box.add_widget(self._row([("查询中…", _HINT, 1.0)]))
        self.hist_box.add_widget(self._hist_title("大宗商品：伦敦金 / WTI / 比特币（近5日）"))
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
                self._quotes.extend(data.get("quotes", []))
                self._render_quotes()
            elif key == "live_yahoo":
                self._quotes.extend(data.get("quotes", []))
                self._render_quotes()
            elif key == "live_median":
                self._render_median(data)
            elif key == "week_news":
                self._render_news(data.get("news", []))
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
        # 两市成交额（首行）+ 本日预测额（另起一行，需求）+ 较上日变化
        t = live.get("turnover_yi")
        p = live.get("turnover_pred_yi")
        vp = live.get("turnover_vs_prev")
        lines = []
        if t:
            lines.append("两市成交额：[color=%s]%.0f[/color] 亿" % (_hex(_RED), t))
        else:
            lines.append("两市成交额：—")
        if p:
            lines.append("本日预测额：[color=%s]%.0f[/color] 亿（开市%d分钟）"
                         % (_hex(_GREEN), p, int(market.elapsed_trade_minutes())))
        elif t:
            lines.append("本日预测额：—")
        if vp is not None and t:
            # 中国股市风格：红涨绿降（较上日增加=红、减少=绿，需求）
            vc = _RED if vp >= 0 else _GREEN
            lines.append("较上日变化：[color=%s]%+.0f[/color] 亿"
                         % (_hex(vc), vp))
        else:
            lines.append("较上日变化：—")
        self.turnover_label.text = "\n".join(lines)

    def _render_quotes(self, quotes=None):
        # 指数/品种表格：与骨架表头对齐，逐行填充（两小节合并渲染）
        if quotes is None:
            quotes = self._quotes
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

    def _render_news(self, news):
        """财经消息：去掉序号；每条 = 标题行【标题】(蓝色链接) + 正文行(另起一行)。

        正文 ≤100 字、纯文本 label（\u00A0 可靠生效 → 不在字母/数字后断行，
        仅因宽度自然换行）；无标题的新闻忽略。news: [(时间, rich_text, url)]。
        """
        if not news:
            self.news_card.clear_widgets()
            self.news_card.spacing = 0
            self.news_card.add_widget(MDLabel(
                text="暂无财经消息", font_style="Body2",
                theme_text_color="Custom", text_color=_GREY, adaptive_height=True,
            ))
            return
        self.news_card.clear_widgets()
        self.news_card.spacing = dp(8)
        shown = 0
        for _ct, text, url in news[:10]:
            title, body = market.split_news_title(text)
            if not title:
                continue   # 无标题 → 忽略该新闻
            item = MDBoxLayout(
                orientation="vertical", size_hint_y=None, spacing=dp(1),
            )
            item.bind(minimum_height=item.setter("height"))
            if url and url.startswith("http"):
                title_lb = MDLabel(
                    text="[ref=%s][color=%s]【%s】[/color][/ref]"
                         % (url, _hex(_HIST_TITLE_COLOR), title),
                    markup=True, font_style="Body2",
                    theme_text_color="Custom", text_color=_HIST_TITLE_COLOR,
                    size_hint=(1, None), adaptive_height=True,
                    halign="left", valign="top",
                )
                title_lb.bind(on_ref_press=self._open_news_link)
            else:
                title_lb = MDLabel(
                    text="[color=%s]【%s】[/color]"
                         % (_hex(_HIST_TITLE_COLOR), title),
                    markup=True, font_style="Body2",
                    theme_text_color="Custom", text_color=_HIST_TITLE_COLOR,
                    size_hint=(1, None), adaptive_height=True,
                    halign="left", valign="top",
                )
            item.add_widget(title_lb)
            if body:
                # 正文另起一行，纯文本 → 字母/数字后不换行（仅宽度自然换行）
                body_lb = MDLabel(
                    text=market._no_break_latin(body), font_style="Body2",
                    theme_text_color="Custom", text_color=_GREY,
                    size_hint=(1, None), adaptive_height=True,
                    halign="left", valign="top",
                )
                body_lb.bind(width=lambda o, *a: setattr(o, "text_size", (o.width, None)))
                item.add_widget(body_lb)
            self.news_card.add_widget(item)
            shown += 1
            if shown >= 10:
                break
        if shown == 0:
            self.news_card.add_widget(MDLabel(
                text="暂无财经消息", font_style="Body2",
                theme_text_color="Custom", text_color=_GREY, adaptive_height=True,
            ))

    def _render_hist_field(self, key, rows):
        """把单个历史小节替换为实际数据（标题 + 表头 + 数值行）。

        伦敦金/WTI/比特币 合并为"大宗商品"表：日期|伦敦金|WTI|金油比|比特币|金比特币。
        """
        # 重建整个历史区（小节少、行数少，重建代价可忽略）
        fields = {k: self._hist_rows.get(k, []) for k in _HIST_FIELDS}
        fields[key] = rows
        self._hist_rows = fields
        self.hist_box.clear_widgets()
        for fk in _HIST_FIELDS:
            if fk in ("wti", "xau", "btc"):
                continue
            self._hist_section(_HIST_TITLES[fk], fields[fk],
                               fmt=_HIST_FMT[fk])
        self._render_commodity_table(fields["xau"], fields["wti"], fields["btc"])

    def _render_commodity_table(self, xau_rows, wti_rows, btc_rows):
        """大宗商品表：比特币可达 → 6列（日期|伦敦金|WTI|金油比|比特币|金比特币）；
        比特币整体不可达 → 顶部一行说明 + 4列（避免每行重复文字，需求）。
        """
        self.hist_box.add_widget(self._hist_title(
            "大宗商品：伦敦金 / WTI / 比特币（近5日）"))
        xmap = dict(xau_rows)
        wmap = dict(wti_rows)
        bmap = dict(btc_rows)
        dates = sorted(set(xmap) & set(wmap))[-5:][::-1]   # 倒序：最新在前（需求）
        if not dates:
            self.hist_box.add_widget(self._row([("暂无数据", _HINT, 1.0)]))
            return
        if not bmap:
            # 比特币整体不可达：不显示说明文字（避免覆盖标题），6列表格中
            # 比特币列标 404（网络不通）、比金比列标 —（需求）
            self.hist_box.add_widget(self._head_row([
                ("日期", 0.16), ("伦敦金", 0.17), ("WTI", 0.17), ("金油比", 0.17),
                ("比特币", 0.17), ("比金比", 0.16)]))
            for d in dates:
                g, w = xmap[d], wmap[d]
                ratio = g / w if w else None
                self.hist_box.add_widget(self._row([
                    (d[5:] if len(d) > 5 else d, _GREY, 0.16),
                    ("%.1f" % g, _WHITE, 0.17),
                    ("%.2f" % w, _WHITE, 0.17),
                    ("%.1f" % ratio if ratio else "—", _HIST_TITLE_COLOR, 0.17),
                    ("404", _HINT, 0.17),
                    ("—", _HINT, 0.16),
                ]))
            return
        self.hist_box.add_widget(self._head_row([
            ("日期", 0.16), ("伦敦金", 0.17), ("WTI", 0.17), ("金油比", 0.17),
            ("比特币", 0.17), ("比金比", 0.16)]))
        for d in dates:
            g, w = xmap[d], wmap[d]
            ratio = g / w if w else None
            b = bmap.get(d)
            if b:
                bgr = b / g
                self.hist_box.add_widget(self._row([
                    (d[5:] if len(d) > 5 else d, _GREY, 0.16),
                    ("%.1f" % g, _WHITE, 0.17),
                    ("%.2f" % w, _WHITE, 0.17),
                    ("%.1f" % ratio if ratio else "—", _HIST_TITLE_COLOR, 0.17),
                    ("%.0f" % b, _WHITE, 0.17),
                    ("%.2f" % bgr, _HIST_TITLE_COLOR, 0.16),
                ]))
            else:
                # 个别日期缺失：比特币=404（网络不通），比金比=—
                self.hist_box.add_widget(self._row([
                    (d[5:] if len(d) > 5 else d, _GREY, 0.16),
                    ("%.1f" % g, _WHITE, 0.17),
                    ("%.2f" % w, _WHITE, 0.17),
                    ("%.1f" % ratio if ratio else "—", _HIST_TITLE_COLOR, 0.17),
                    ("404", _HINT, 0.17),
                    ("—", _HINT, 0.16),
                ]))

    def _hist_title(self, text):
        # 历史小节标题：不小于数值行字号（Body2），浅蓝区分（需求）
        return MDLabel(
            text=text, font_style="Body2", bold=True,
            theme_text_color="Custom", text_color=_HIST_TITLE_COLOR,
            adaptive_height=True,
        )

    def _hist_section(self, title, rows, fmt):
        self.hist_box.add_widget(self._hist_title(title))
        if not rows:
            self.hist_box.add_widget(self._row([("暂无数据", _HINT, 1.0)]))
            return
        self.hist_box.add_widget(self._head_row([("日期", 0.5), ("数值", 0.5)]))
        for d, v in reversed(rows):   # 倒序：最新在前（需求）
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
    "btc": "比特币（美元）",
}
_HIST_FIELDS = {
    "turnover": "turnover",
    "ccpr": "ccpr",
    "wti": "wti",
    "xau": "xau",
    "btc": "btc",
}
_SECTION_TO_FIELD = {
    "hist_turnover": "turnover",
    "hist_ccpr": "ccpr",
    "hist_wti": "wti",
    "hist_xau": "xau",
    "hist_btc": "btc",
}
_HIST_FMT = {
    "turnover": lambda v: "%.0f" % v,
    "ccpr": lambda v: "%.4f" % v,
    "wti": lambda v: "%.2f" % v,
    "xau": lambda v: "%.2f" % v,
    "btc": lambda v: "%.0f" % v,
}
