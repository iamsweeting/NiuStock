# -*- coding: utf-8 -*-
"""牛票 · 宏观数据页（「宏观数据」tab）。

需求：
  1. 查询周期近 12 个月（原 3 个月调整为 12 个月）
  2. 指标分组：一、PMI及细分  二、通胀  三、流动性  四、资产价格
     五、大宗商品（近 5 日 伦敦金/WTI/金油比）  六、中美关键指标发布
  3. 表格含「公式」列；每项指标在数据下方以小字（不超过一行）标明
     定义/意义/作用（需求补充）
  4. 派生指标单独底色块展示（经济势能/供需差/备料差/TEC/通胀预期/剪刀差/
     金比特币/中国实际利率/GDP平减指数）
布局沿用行情页的固定行高行式表格 + 自适应卡片，避免 Adreno 叠加错乱。
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
_TITLE = get_color_from_hex("#8ab4f8")     # 小节标题：浅蓝
_DERIVE_BG = (0.10, 0.16, 0.28, 0.95)      # 派生指标卡片底色（深蓝）
_MAIN_BG = (0.09, 0.11, 0.16, 0.95)        # 普通指标卡片底色
_CARD_RADIUS = [dp(10), dp(10), dp(10), dp(10)]
_ROW_H = 30

# 格式化器
_FMT_PCT1 = lambda v: "%.1f%%" % v
_FMT_PCT2 = lambda v: "%.2f%%" % v
_FMT_PCT3 = lambda v: "%.3f%%" % v
_FMT_YI = lambda v: "%.0f亿" % v
_FMT_GOLD = lambda v: "%.0f" % v
_FMT_BTC = lambda v: "%.0f" % v
_FMT_RATIO = lambda v: "%.4f" % v


class MacroPage:
    """宏观数据功能页。"""

    def __init__(self, app):
        self.app = app
        self._busy = False
        self._last_refresh = 0.0
        self._data = None

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
            text="月度宏观指标（近12个月）· 切换页面时自动刷新",
            font_style="Caption", theme_text_color="Hint", adaptive_height=True,
        ))

        self.body = MDBoxLayout(
            orientation="vertical", spacing=dp(10), adaptive_height=True,
        )
        box.add_widget(self.body)

        self.error_label = MDLabel(
            text="", markup=True, font_style="Caption",
            theme_text_color="Custom", text_color=_HINT, adaptive_height=True,
        )
        box.add_widget(self.error_label)

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
        if not force and self._data is not None and \
                now - self._last_refresh < market.REFRESH_TTL:
            self.ts_label.text = "更新于：%s（已是最新）" % self._data.get("ts", "—")
            return
        self._busy = True
        self.refresh_btn.disabled = True
        self.ts_label.text = "更新于：刷新中…"
        self.body.clear_widgets()
        self.body.add_widget(self._placeholder("宏观数据查询中…"))
        self.error_label.text = ""

        def on_done(data):
            Clock.schedule_once(lambda dt: self._on_done(data), 0)

        threading.Thread(
            target=lambda: market.refresh_macro(on_done), daemon=True).start()

    def _on_done(self, data):
        self._busy = False
        self.refresh_btn.disabled = False
        self._last_refresh = time.monotonic()
        self._data = data
        self.ts_label.text = "更新于：%s" % data.get("ts", "—")
        errs = data.get("errors", [])
        self.error_label.text = ("\n".join("· %s" % e for e in errs[:6])
                                 if errs else "")
        self._render(data)

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------
    def _render(self, d):
        self.body.clear_widgets()
        box = self.body

        box.add_widget(self._title("一、PMI及细分（近12个月）"))
        pmi = d.get("pmi", {})
        self._render_group(box, pmi.get("months", []), pmi.get("series", {}),
                           _PMI_META, market.derive_macro_pmi(pmi.get("series", {})))

        box.add_widget(self._title("二、通胀（近12个月）"))
        inf = d.get("inflation", {})
        months = inf.get("months", {})
        series = inf.get("series", {})
        self._render_series_card(box, "CPI同比", months.get("cpi", []),
                                 series.get("CPI同比", []), _INFL_META["CPI同比"])
        self._render_series_card(box, "PPI同比", months.get("ppi", []),
                                 series.get("PPI同比", []), _INFL_META["PPI同比"])
        self._render_series_card(box, "PPIRM同比", months.get("ppirm", []),
                                 series.get("PPIRM同比", []), _INFL_META["PPIRM同比"])
        pce_note = "（更新至%s）" % months["us_pce"][-1] if months.get("us_pce") else ""
        self._render_series_card(box, "美国核心PCE", months.get("us_pce", []),
                                 series.get("美国核心PCE", []),
                                 (_INFL_META["美国核心PCE"][0],
                                  _INFL_META["美国核心PCE"][1] + pce_note,
                                  _INFL_META["美国核心PCE"][2]))
        self._render_derived(box, market.derive_macro_inflation(series),
                             _DERIVE_META.get("inflation"))

        box.add_widget(self._title("三、流动性（近12个月）"))
        liq = d.get("liquidity", {})
        lmonths = liq.get("months", {})
        lseries = liq.get("series", {})
        self._render_series_card(box, "M1同比", lmonths.get("m", []),
                                 lseries.get("M1同比", []), _LIQ_META["M1同比"])
        self._render_series_card(box, "M2同比", lmonths.get("m", []),
                                 lseries.get("M2同比", []), _LIQ_META["M2同比"])
        self._render_series_card(box, "社融增量", lmonths.get("shrzgm", []),
                                 lseries.get("社融增量", []), _LIQ_META["社融增量"])
        self._render_series_card(box, "新增人民币贷款", lmonths.get("loan", []),
                                 lseries.get("新增人民币贷款", []), _LIQ_META["新增人民币贷款"])
        self._render_derived(box, market.derive_macro_liquidity(lseries),
                             _DERIVE_META.get("liquidity"))

        box.add_widget(self._title("四、资产价格（近12个月，月末值）"))
        ast = d.get("assets", {})
        amonths = ast.get("months", {})
        aseries = ast.get("series", {})
        self._render_series_card(box, "伦敦金", amonths.get("gold", []),
                                 aseries.get("伦敦金", []), _AST_META["伦敦金"])
        self._render_series_card(box, "比特币", amonths.get("btc", []),
                                 aseries.get("比特币", []), _AST_META["比特币"])
        self._render_series_card(box, "中国10年国债", amonths.get("cn10y", []),
                                 aseries.get("中国10年国债", []), _AST_META["中国10年国债"])
        self._render_series_card(box, "1年期LPR", amonths.get("lpr", []),
                                 aseries.get("1年期LPR", []), _AST_META["1年期LPR"])
        self._render_derived(box, market.derive_macro_assets(aseries, ast.get("extra", {})),
                             _DERIVE_META.get("assets"), extra_note=ast.get("extra", {}))

        box.add_widget(self._title("五、大宗商品（近5日）"))
        self._render_commodity(d.get("commodity", {}))

        box.add_widget(self._title("六、中美关键指标发布"))
        self._render_us(d.get("us", []))

    def _render_group(self, box, months, series, meta, derived):
        """PMI 组：按 meta 顺序渲染指标块 + 派生块。"""
        for key, formula, meaning, fmt in meta:
            self._render_series_card(box, key, months, series.get(key, []),
                                     (formula, meaning, fmt))
        if derived:
            self._render_derived(box, derived, _DERIVE_META.get("pmi"))

    # ------------------------------------------------------------------
    # 指标块：名称行 + 公式行 + 意义行（小字单行） + 近12月串
    # ------------------------------------------------------------------
    def _render_series_card(self, box, name, months, values, meta):
        formula, meaning, fmt = meta
        card = MDCard(
            orientation="vertical", padding=[dp(10), dp(6), dp(10), dp(6)],
            radius=_CARD_RADIUS, elevation=0, size_hint_y=None,
            md_bg_color=_MAIN_BG,
        )
        card.bind(minimum_height=card.setter("height"))

        # 名称 + 最新值 + 环比
        line, latest = self._latest_line(name, months, values, fmt)
        card.add_widget(MDLabel(
            text=line, markup=True, font_style="Body2", bold=True,
            theme_text_color="Custom", text_color=_WHITE, adaptive_height=True,
        ))

        # 公式（小字单行）
        card.add_widget(self._hint_line("公式：%s" % formula))

        # 定义/意义/作用（小字单行，需求补充）
        card.add_widget(self._hint_line("意义：%s" % meaning))

        # 近 12 月数值串（自动换行）
        if months and values and latest is not None:
            parts = []
            for m, v in zip(months, values):
                if v is None:
                    continue
                parts.append("%s %s" % (market._month_short(m), fmt(v)))
            if parts:
                ml = MDLabel(
                    text="近12月：%s" % " · ".join(parts),
                    font_style="Caption", theme_text_color="Custom",
                    text_color=_GREY, adaptive_height=True,
                )
                ml.bind(width=lambda o, *a: setattr(o, "text_size", (o.width, None)))
                card.add_widget(ml)
        box.add_widget(card)

    def _hint_line(self, text):
        """小字说明行：单行（超出省略号省略显示）。"""
        lb = MDLabel(
            text=text, font_style="Caption", theme_text_color="Custom",
            text_color=_HINT, size_hint_y=None, height=dp(18),
            valign="middle",
        )
        # 单行裁剪：size→text_size 单向绑定（不做动态字号，避免 Adreno 回调递归）
        lb.bind(size=lambda o, *a: setattr(o, "text_size", (o.width, o.height)))
        return lb

    def _latest_line(self, name, months, values, fmt):
        """「名称  最新值  ▲/▼环比」；返回 (markup文本, 最新值)。"""
        v = None
        idx = -1
        for i in range(len(values) - 1, -1, -1):
            if values[i] is not None:
                v = values[i]
                idx = i
                break
        if v is None:
            return ("[color=%s]%s[/color]  —" % (_hex(_GREY), name), None)
        mlabel = ""
        if 0 <= idx < len(months):
            mlabel = "（%s）" % market._month_short(months[idx])
        prev = values[idx - 1] if idx > 0 else None
        diff_txt = ""
        if prev is not None:
            d = v - prev
            arrow = "▲" if d >= 0 else "▼"
            col = _GREEN if d >= 0 else _RED
            diff_txt = "  [color=%s]%s%+.2f[/color]" % (_hex(col), arrow, d)
        return ("[color=%s]%s[/color]  %s%s%s"
                % (_hex(_WHITE), name, fmt(v), mlabel, diff_txt), v)

    def _render_derived(self, box, derived, meta, extra_note=None):
        """派生指标块：深蓝底色 + 「派生」前缀 + 意义小字。"""
        if not derived:
            return
        card = MDCard(
            orientation="vertical", padding=[dp(10), dp(6), dp(10), dp(6)],
            radius=_CARD_RADIUS, elevation=0, size_hint_y=None,
            md_bg_color=_DERIVE_BG,
        )
        card.bind(minimum_height=card.setter("height"))
        for key, v in derived.items():
            if v is None:
                continue
            m = (meta or {}).get(key, {})
            fmt = m.get("fmt", _FMT_PCT2)
            meaning = m.get("meaning", "")
            card.add_widget(MDLabel(
                text="[color=%s]%s[/color]  %s  [color=%s]（派生）[/color]"
                     % (_hex(_WHITE), key, fmt(v), _hex(_TITLE)),
                markup=True, font_style="Body2", bold=True,
                theme_text_color="Custom", text_color=_WHITE, adaptive_height=True,
            ))
            if meaning:
                card.add_widget(self._hint_line("公式：%s  ｜  意义：%s"
                                                % (m.get("formula", ""), meaning)))
        if extra_note:
            note = []
            if extra_note.get("house_yoy") is not None:
                note.append("房价涨幅≈一线新房同比%+.1f%%（%s）"
                            % (extra_note["house_yoy"], extra_note.get("house_month", "")))
            if extra_note.get("gdp_nominal_yoy") is not None:
                note.append("现价GDP同比%.1f%%（%s）" % (
                    extra_note["gdp_nominal_yoy"], extra_note.get("gdp_month", "")))
            if extra_note.get("gdp_real_yoy") is not None:
                note.append("不变价GDP同比%.1f%%（%s）" % (
                    extra_note["gdp_real_yoy"], extra_note.get("gdp_real_month", "")))
            if note:
                nl = MDLabel(
                    text="来源：%s" % " · ".join(note),
                    font_style="Caption", theme_text_color="Custom",
                    text_color=_HINT, adaptive_height=True,
                )
                nl.bind(width=lambda o, *a: setattr(o, "text_size", (o.width, None)))
                card.add_widget(nl)
        box.add_widget(card)

    def _render_commodity(self, com):
        dates = com.get("dates", [])
        gold = com.get("gold", [])
        wti = com.get("wti", [])
        ratio = com.get("ratio", [])
        if not dates:
            self.body.add_widget(self._card_text("暂无数据"))
            return
        card = MDCard(
            orientation="vertical", padding=[dp(10), dp(6), dp(10), dp(6)],
            radius=_CARD_RADIUS, elevation=0, size_hint_y=None, md_bg_color=_MAIN_BG,
        )
        card.bind(minimum_height=card.setter("height"))
        card.add_widget(self._head_row([("日期", 0.26), ("伦敦金", 0.24), ("WTI", 0.24), ("金油比", 0.26)]))
        for i, d in enumerate(dates):
            r = ratio[i] if i < len(ratio) else None
            card.add_widget(self._row([
                (d[5:] if len(d) > 5 else d, _GREY, 0.26),
                ("%.1f" % gold[i] if i < len(gold) else "—", _WHITE, 0.24),
                ("%.2f" % wti[i] if i < len(wti) else "—", _WHITE, 0.24),
                ("%.1f" % r if r else "—", _TITLE, 0.26),
            ]))
        self.body.add_widget(card)

    def _render_us(self, us):
        if not us:
            self.body.add_widget(self._card_text("暂无发布日历数据"))
            return
        card = MDCard(
            orientation="vertical", padding=[dp(10), dp(6), dp(10), dp(6)],
            radius=_CARD_RADIUS, elevation=0, size_hint_y=None, md_bg_color=_MAIN_BG,
        )
        card.bind(minimum_height=card.setter("height"))
        card.add_widget(self._head_row([("发布日期", 0.30), ("指标", 0.42), ("今值/前值", 0.28)]))
        for it in us:
            val = it.get("value")
            prev = it.get("prev")
            vtxt = "待发布" if val is None else ("%.2f" % float(val))
            ptxt = ("前值 %.2f" % float(prev)) if prev not in (None, "") else "—"
            card.add_widget(self._row([
                (str(it.get("date", ""))[5:], _GREY, 0.30),
                ("%s" % it.get("name", ""), _WHITE, 0.42),
                ("%s\n%s" % (vtxt, ptxt), _TITLE if val is None else _WHITE, 0.28),
            ]))
        card.add_widget(MDLabel(
            text="中国：最近数据期 CPI/PPI/PMI/M1/M2 见上方月度表（发布结果）。",
            font_style="Caption", theme_text_color="Custom", text_color=_HINT,
            adaptive_height=True,
        ))
        self.body.add_widget(card)

    # ------------------------------------------------------------------
    # 通用控件
    # ------------------------------------------------------------------
    @staticmethod
    def _title(text):
        return MDLabel(
            text=text, font_style="Subtitle1", bold=True,
            adaptive_height=True, theme_text_color="Custom", text_color=_TITLE,
        )

    def _card_text(self, text):
        c = MDCard(
            orientation="vertical", padding=[dp(10), dp(6), dp(10), dp(6)],
            radius=_CARD_RADIUS, elevation=0, size_hint_y=None, md_bg_color=_MAIN_BG,
        )
        c.bind(minimum_height=c.setter("height"))
        c.add_widget(MDLabel(
            text=text, font_style="Body2", theme_text_color="Custom",
            text_color=_GREY, adaptive_height=True,
        ))
        return c

    @staticmethod
    def _placeholder(text):
        return MDLabel(
            text=text, font_style="Body1", theme_text_color="Custom",
            text_color=_HINT, adaptive_height=True,
        )

    @staticmethod
    def _row(cells, height=_ROW_H):
        r = BoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(height),
            spacing=dp(4),
        )
        for text, color, sx in cells:
            r.add_widget(MDLabel(
                text=text, adaptive_height=True, size_hint_x=sx,
                theme_text_color="Custom", text_color=color,
                halign="left", valign="middle", font_style="Body2",
            ))
        return r

    def _head_row(self, cols):
        return self._row([(c, _HINT, sx) for c, sx in cols])


def _hex(col):
    return "#%02x%02x%02x" % (int(col[0] * 255), int(col[1] * 255), int(col[2] * 255))


# 指标元数据：(公式, 意义/定义/作用, 格式化)
_PMI_META = [
    ("PMI", "官方制造业采购经理指数", "综合制造业景气度，>50扩张 <50收缩", _FMT_PCT1),
    ("生产", "制造业生产指数", "生产活动扩张/收缩，同步指标", _FMT_PCT1),
    ("新订单", "制造业新订单指数", "市场需求强弱，领先指标", _FMT_PCT1),
    ("产成品库存", "制造业产成品库存指数", "库存积压/去化程度", _FMT_PCT1),
    ("采购量", "制造业采购量指数", "企业原材料采购意愿", _FMT_PCT1),
    ("原材料库存", "制造业原材料库存指数", "原材料备货水平，补库信号", _FMT_PCT1),
]

_INFL_META = {
    "CPI同比": ("全国居民消费价格当月同比", "居民消费价格月度同比，通胀核心指标", _FMT_PCT1),
    "PPI同比": ("工业品出厂价格当月同比", "生产端出厂价格，企业盈利风向标", _FMT_PCT1),
    "PPIRM同比": ("工业生产者购进价格同比（上年同月=100换算）", "上游原材料成本压力", _FMT_PCT1),
    "美国核心PCE": ("美国核心PCE物价指数年率（金十）", "美联储目标通胀，剔除食品能源", _FMT_PCT1),
}

_LIQ_META = {
    "M1同比": ("狭义货币(M1)供应量同比", "企业活期资金活跃度，领先经济", _FMT_PCT1),
    "M2同比": ("广义货币(M2)供应量同比", "货币供应总闸门，总量宽松信号", _FMT_PCT1),
    "社融增量": ("社会融资规模增量（亿元，商务部）", "实体经济融资总量，信用扩张信号", _FMT_YI),
    "新增人民币贷款": ("金融机构新增人民币贷款（亿元）", "银行信贷投放，信用脉冲", _FMT_YI),
}

_AST_META = {
    "伦敦金": ("伦敦金现货（美元/盎司，月末）", "避险资产，美元计价", _FMT_GOLD),
    "比特币": ("BTC/USDT 收盘（美元，月末，MEXC）", "数字资产，风险偏好指标", _FMT_BTC),
    "中国10年国债": ("中债10年期国债收益率（%）", "无风险利率基准，资产定价锚", _FMT_PCT3),
    "1年期LPR": ("贷款市场报价利率 1 年期（%）", "贷款基准利率，政策利率传导", _FMT_PCT2),
}

_DERIVE_META = {
    "pmi": {
        "经济势能": {"formula": "新订单−产成品库存", "meaning": "需求与库存背离度，越正越旺", "fmt": _FMT_PCT1},
        "供需差": {"formula": "生产−新订单", "meaning": "供过于求为负，产出与需求差", "fmt": _FMT_PCT1},
        "备料差": {"formula": "采购量−原材料库存", "meaning": "主动补库为负，备料意愿", "fmt": _FMT_PCT1},
        "TEC": {"formula": "Δ新订单−Δ产成品库存", "meaning": "近两期差，经济动能变化", "fmt": _FMT_PCT1},
    },
    "inflation": {
        "通胀预期指数": {"formula": "CPI同比−PPI同比", "meaning": "消费与生产价格差，剪刀差", "fmt": _FMT_PCT1},
    },
    "liquidity": {
        "M1-M2剪刀差": {"formula": "M1同比−M2同比", "meaning": "走阔=资金活化，利好股市", "fmt": _FMT_PCT1},
    },
    "assets": {
        "金比特币": {"formula": "伦敦金÷比特币", "meaning": "避险 vs 风险偏好比值", "fmt": _FMT_RATIO},
        "中国实际利率": {"formula": "1年期LPR−一线新房同比", "meaning": "融资真实成本（房价近通胀）", "fmt": _FMT_PCT1},
        "GDP平减指数": {"formula": "现价GDP同比−不变价同比", "meaning": "全面价格水平变化", "fmt": _FMT_PCT1},
    },
}
