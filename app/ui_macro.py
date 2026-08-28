# -*- coding: utf-8 -*-
"""牛票 · 宏观数据页（「宏观数据」tab）。

需求：
  1. 月度宏观数据本地缓存：当天已刷新则直接读缓存不联网；手动刷新强制联网
  2. 中美关键指标发布时间放在最前面（一、）
  3. 数据按倒序排列（最新在最前）
  4. 每项指标小字说明：代表含义 + 对经济/股市影响
  5. 派生指标块固定行高布局（数值行 + 公式/意义行），避免文字叠加
  6. 大宗商品：近 5 日金油比在行情页；本页提供近 12 个月月均金油比
布局沿用固定行高行式表格 + 自适应卡片；所有自适应文本绑定 text_size。
"""
import threading
import time

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.utils import get_color_from_hex

from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDRaisedButton
from kivymd.uix.card import MDCard, MDSeparator
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
            text="月度宏观数据（近12个月）· 当天首次读取后存本地，可手动刷新",
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
    # 刷新（缓存优先：当天已刷新则读本地；手动刷新强制联网）
    # ------------------------------------------------------------------
    def refresh_if_stale(self):
        if time.monotonic() - self._last_refresh >= market.REFRESH_TTL:
            self.refresh(force=False)

    def refresh(self, force=False):
        if self._busy:
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
            target=lambda: market.refresh_macro_cached(on_done, force=force),
            daemon=True).start()

    def _on_done(self, data):
        self._busy = False
        self.refresh_btn.disabled = False
        self._last_refresh = time.monotonic()
        self._data = data
        cached = data.get("from_cache")
        self.ts_label.text = "更新于：%s%s" % (
            data.get("ts", "—"), "（本地缓存）" if cached else "")
        errs = data.get("errors", [])
        self.error_label.text = ("\n".join("· %s" % e for e in errs[:6])
                                 if errs else "")
        self._render(data)

    # ------------------------------------------------------------------
    # 渲染（一、发布时间在最前；数据倒序，最新在前）
    # ------------------------------------------------------------------
    def _render(self, d):
        self.body.clear_widgets()
        box = self.body

        box.add_widget(self._title("一、中美关键指标发布"))
        self._render_us(d)

        box.add_widget(self._title("二、PMI及细分（近12个月）"))
        pmi = d.get("pmi", {})
        self._render_group(box, pmi.get("months", []), pmi.get("series", {}),
                           _PMI_META, market.derive_macro_pmi(pmi.get("series", {})))

        box.add_widget(self._title("三、通胀（近12个月）"))
        inf = d.get("inflation", {})
        months = inf.get("months", {})
        series = inf.get("series", {})
        self._render_series_card(box, "CPI同比", months.get("cpi", []),
                                 series.get("CPI同比", []), _INFL_META["CPI同比"])
        self._render_series_card(box, "PPI同比", months.get("ppi", []),
                                 series.get("PPI同比", []), _INFL_META["PPI同比"])
        self._render_series_card(box, "PPIRM同比", months.get("ppirm", []),
                                 series.get("PPIRM同比", []), _INFL_META["PPIRM同比"])
        self._render_derived(box, market.derive_macro_inflation(series),
                             _DERIVE_META.get("inflation"))

        box.add_widget(self._title("四、流动性（近12个月）"))
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

        box.add_widget(self._title("五、资产价格（近12个月，月末值）"))
        ast = d.get("assets", {})
        amonths = ast.get("months", {})
        aseries = ast.get("series", {})
        self._render_series_card(box, "伦敦金", amonths.get("gold", []),
                                 aseries.get("伦敦金", []), _AST_META["伦敦金"])
        self._render_series_card(box, "中国10年国债", amonths.get("cn10y", []),
                                 aseries.get("中国10年国债", []), _AST_META["中国10年国债"])
        self._render_series_card(box, "1年期LPR", amonths.get("lpr", []),
                                 aseries.get("1年期LPR", []), _AST_META["1年期LPR"])
        self._render_derived(box, market.derive_macro_assets(aseries, ast.get("extra", {})),
                             _DERIVE_META.get("assets"), extra_note=ast.get("extra", {}))

        box.add_widget(self._title("六、大宗商品与比特币（近12个月）"))
        self._render_commodity(d.get("commodity", {}), ast)

    def _render_group(self, box, months, series, meta, derived):
        """PMI 组：按 meta 顺序渲染指标块 + 派生块。"""
        for key, formula, meaning, fmt in meta:
            self._render_series_card(box, key, months, series.get(key, []),
                                     (formula, meaning, fmt))
        if derived:
            self._render_derived(box, derived, _DERIVE_META.get("pmi"))

    # ------------------------------------------------------------------
    # 指标块：名称行 + 公式行 + 意义行 + 近12月串（倒序）
    # ------------------------------------------------------------------
    def _render_series_card(self, box, name, months, values, meta):
        formula, meaning, fmt = meta
        card = MDCard(
            orientation="vertical", padding=[dp(10), dp(6), dp(10), dp(6)],
            radius=_CARD_RADIUS, elevation=0, size_hint_y=None,
            md_bg_color=_MAIN_BG,
        )
        card.bind(minimum_height=card.setter("height"))

        # 名称 + 最新值 + 环比（markup，单行文本）
        line, latest = self._latest_line(name, months, values, fmt)
        lb = MDLabel(
            text=line, markup=True, font_style="Body2", bold=True,
            theme_text_color="Custom", text_color=_WHITE, adaptive_height=True,
        )
        lb.bind(width=lambda o, *a: setattr(o, "text_size", (o.width, None)))
        card.add_widget(lb)

        # 公式（小字单行）
        card.add_widget(self._hint_line("公式：%s" % formula))
        # 定义/意义/作用（小字，自适应换行：代表含义 + 对经济/股市影响）
        card.add_widget(self._meaning_line(meaning))

        # 近 12 个月数值（倒序：最新在前，每行 3 个月，需求：删除"近12月："前缀）
        if months and values and latest is not None:
            cells = []
            for i in range(len(months) - 1, -1, -1):
                v = values[i]
                if v is None:
                    continue
                cells.append("%s %s" % (market._month_short(months[i]), fmt(v)))
            if cells:
                rows = ["   ".join(cells[j:j + 3]) for j in range(0, len(cells), 3)]
                ml = MDLabel(
                    text="\n".join(rows),
                    font_style="Caption", theme_text_color="Custom",
                    text_color=_GREY, adaptive_height=True,
                )
                ml.bind(width=lambda o, *a: setattr(o, "text_size", (o.width, None)))
                card.add_widget(ml)
        box.add_widget(card)

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
            # 中国股市风格：红涨绿降（需求）
            col = _RED if d >= 0 else _GREEN
            diff_txt = "  [color=%s]%s%+.2f[/color]" % (_hex(col), arrow, d)
        return ("[color=%s]%s[/color]  %s%s%s"
                % (_hex(_WHITE), name, fmt(v), mlabel, diff_txt), v)

    # ------------------------------------------------------------------
    # 派生块：固定行高（数值行 BoxLayout 无 markup + 公式/意义小字）
    #   修复：旧实现数值行 markup+adaptive 在 Adreno 上纹理高度异常，
    #   导致数值不显示、后续行文字叠加（用户实测经济势能/实际利率等块）。
    # ------------------------------------------------------------------
    def _render_derived(self, box, derived, meta, extra_note=None):
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
            formula = m.get("formula", "")
            # 数值行：横向 BoxLayout（label 固定 height，卡片高度正确累加，
            # 无 markup，杜绝叠加）
            row = BoxLayout(
                orientation="horizontal", size_hint_y=None, height=dp(26),
                spacing=dp(6),
            )
            row.add_widget(MDLabel(
                text=market._no_break_latin(key), font_style="Body2", bold=True,
                size_hint=(0.42, None), height=dp(26),
                theme_text_color="Custom", text_color=_WHITE,
                halign="left", valign="middle",
            ))
            row.add_widget(MDLabel(
                text=market._no_break_latin(fmt(v)), font_style="Body2", bold=True,
                size_hint=(0.33, None), height=dp(26),
                theme_text_color="Custom", text_color=_TITLE,
                halign="left", valign="middle",
            ))
            row.add_widget(MDLabel(
                text="（派生）", font_style="Caption",
                size_hint=(0.25, None), height=dp(26),
                theme_text_color="Custom", text_color=_HINT,
                halign="left", valign="middle",
            ))
            card.add_widget(row)
            if formula:
                card.add_widget(self._meaning_line("公式：%s" % formula))
            if meaning:
                card.add_widget(self._meaning_line(meaning))
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

    def _render_commodity(self, com, ast=None):
        """六、大宗商品：近 12 个月月末金油比 + 月均金油比。"""
        # 用资产价格里的伦敦金/WTI 月度序列计算月均金油比
        gold_m = (ast or {}).get("months", {}).get("gold", [])
        gold_v = (ast or {}).get("series", {}).get("伦敦金", [])
        wti_m = (ast or {}).get("months", {}).get("wti", [])
        wti_v = (ast or {}).get("series", {}).get("WTI", [])
        gmap = dict(zip(gold_m, gold_v))
        wmap = dict(zip(wti_m, wti_v))
        months = sorted(set(gmap) & set(wmap))[-12:][::-1]  # 倒序，最新在前
        if not months:
            self.body.add_widget(self._card_text("暂无数据"))
            return
        ratios = []
        for m in months:
            g, w = gmap[m], wmap[m]
            if g and w:
                ratios.append((m, round(g / w, 1)))
        if not ratios:
            self.body.add_widget(self._card_text("暂无数据"))
            return
        avg = sum(r for _m, r in ratios) / len(ratios)
        card = MDCard(
            orientation="vertical", padding=[dp(10), dp(6), dp(10), dp(6)],
            radius=_CARD_RADIUS, elevation=0, size_hint_y=None, md_bg_color=_MAIN_BG,
        )
        card.bind(minimum_height=card.setter("height"))
        card.add_widget(MDLabel(
            text="月均金油比（伦敦金÷WTI，近12个月）：[color=%s]%.1f[/color]"
                 % (_hex(_TITLE), avg),
            markup=True, font_style="Body2", bold=True,
            theme_text_color="Custom", text_color=_WHITE, adaptive_height=True,
        ))
        card.add_widget(self._meaning_line(
            "含义：一盎司黄金可换WTI桶数，反映贵金属/能源比价；走阔=避险升温，股市偏空。参考中枢15-20"))
        parts = []
        for m, r in ratios:
            parts.append("%s %s" % (market._month_short(m), "%.1f" % r))
        rows = ["   ".join(parts[j:j + 3]) for j in range(0, len(parts), 3)]
        ml = MDLabel(
            text="\n".join(rows),
            font_style="Caption", theme_text_color="Custom",
            text_color=_GREY, adaptive_height=True,
        )
        ml.bind(width=lambda o, *a: setattr(o, "text_size", (o.width, None)))
        card.add_widget(ml)
        self.body.add_widget(card)
        # ---- 比特币 + 金比特币（本页最后，金油比下面，需求恢复）----
        self._render_btc(ast)

    def _render_btc(self, ast):
        """比特币与比金比（比特币÷伦敦金）：页面最后。MEXC 不可达时显示暂无。"""
        ast = ast or {}
        btc_m = ast.get("months", {}).get("btc", [])
        btc_v = ast.get("series", {}).get("比特币", [])
        gold_m = ast.get("months", {}).get("gold", [])
        gold_v = ast.get("series", {}).get("伦敦金", [])
        if not btc_v or not any(btc_v):
            self.body.add_widget(self._card_text("比特币：暂无数据（数据源网络不可达）"))
            return
        card = MDCard(
            orientation="vertical", padding=[dp(10), dp(6), dp(10), dp(6)],
            radius=_CARD_RADIUS, elevation=0, size_hint_y=None, md_bg_color=_MAIN_BG,
        )
        card.bind(minimum_height=card.setter("height"))
        # 比特币最新值
        line, latest = self._latest_line("比特币", btc_m, btc_v, _FMT_BTC)
        lb = MDLabel(text=line, markup=True, font_style="Body2", bold=True,
                     theme_text_color="Custom", text_color=_WHITE, adaptive_height=True)
        lb.bind(width=lambda o, *a: setattr(o, "text_size", (o.width, None)))
        card.add_widget(lb)
        card.add_widget(self._meaning_line(
            "代表数字资产与风险偏好；上涨=资金风险偏好提升，利好科技成长股"))
        cells = []
        for i in range(len(btc_m) - 1, -1, -1):
            v = btc_v[i]
            if v is None:
                continue
            cells.append("%s %s" % (market._month_short(btc_m[i]), "%.0f" % v))
        if cells:
            rows = ["   ".join(cells[j:j + 3]) for j in range(0, len(cells), 3)]
            ml = MDLabel(text="\n".join(rows), font_style="Caption",
                         theme_text_color="Custom", text_color=_GREY, adaptive_height=True)
            ml.bind(width=lambda o, *a: setattr(o, "text_size", (o.width, None)))
            card.add_widget(ml)
        # 比金比 = 比特币 ÷ 伦敦金（最新 + 近12月 + 中枢参考）
        if gold_v and gold_m:
            gmap = dict(zip(gold_m, gold_v))
            bmap = dict(zip(btc_m, btc_v))
            months = sorted(set(gmap) & set(bmap))[-12:][::-1]
            ratios = []
            for m in months:
                g, b = gmap[m], bmap[m]
                if g and b:
                    ratios.append((m, b / g))
            if ratios:
                card.add_widget(MDSeparator())
                cur = ratios[0][1]
                card.add_widget(MDLabel(
                    text="[color=%s]比金比[/color]  %.2f（%s）"
                         % (_hex(_WHITE), cur, market._month_short(ratios[0][0])),
                    markup=True, font_style="Body2", bold=True,
                    theme_text_color="Custom", text_color=_WHITE, adaptive_height=True,
                ))
                card.add_widget(self._meaning_line(
                    "=比特币÷伦敦金，代表风险偏好/避险比值；走高=风险偏好占优利好股市。参考中枢15-25"))
                rcells = ["%s %.2f" % (market._month_short(m), r) for m, r in ratios]
                rrows = ["   ".join(rcells[j:j + 3]) for j in range(0, len(rcells), 3)]
                rl = MDLabel(text="\n".join(rrows), font_style="Caption",
                             theme_text_color="Custom", text_color=_GREY, adaptive_height=True)
                rl.bind(width=lambda o, *a: setattr(o, "text_size", (o.width, None)))
                card.add_widget(rl)
        self.body.add_widget(card)

    def _render_us(self, d):
        """一、中美关键指标发布：中美分开；每指标显示本周期/上周期值；
        未公布显示"待发布"提醒（避免发布对股市影响）。"""
        us = d.get("us", [])
        cn_sched = d.get("cn_schedule", [])

        # ---- 中国部分：从月度数据取最近两期 + 下次发布提醒 ----
        cns = self._china_rows(d)
        card = MDCard(
            orientation="vertical", padding=[dp(10), dp(8), dp(10), dp(8)],
            spacing=dp(6),
            radius=_CARD_RADIUS, elevation=0, size_hint_y=None, md_bg_color=_MAIN_BG,
        )
        card.bind(minimum_height=card.setter("height"))
        card.add_widget(self._row([("中国", _TITLE, 1.0)], height=26, font_style="Body2"))
        card.add_widget(self._head_row(
            [("指标", 0.34), ("本周期", 0.22), ("上周期", 0.22), ("下次发布", 0.22)]))
        sched_map = {s[0]: s[1] for s in cn_sched}   # 名称 -> "MM-DD"
        for name, cur, prev, month in cns:
            nx = sched_map.get(name, "")
            card.add_widget(self._row([
                (name, _WHITE, 0.34),
                (cur, _TITLE, 0.22),
                (prev, _GREY, 0.22),
                (nx, _GREEN, 0.22),
            ], height=30, font_style="Body2"))
        if not cns:
            card.add_widget(self._meaning_line("中国指标数据加载中…"))
        self.body.add_widget(card)

        # ---- 美国部分：与中国一致（指标|本期|上期|下次发布；未公布=待发布）----
        if us:
            card2 = MDCard(
                orientation="vertical", padding=[dp(10), dp(8), dp(10), dp(8)],
                spacing=dp(12),
                radius=_CARD_RADIUS, elevation=0, size_hint_y=None, md_bg_color=_MAIN_BG,
            )
            card2.bind(minimum_height=card2.setter("height"))
            card2.add_widget(self._row([("美国", _TITLE, 1.0)], height=26, font_style="Body2"))
            card2.add_widget(self._head_row(
                [("指标", 0.34), ("本期", 0.22), ("上期", 0.22), ("下次发布", 0.22)]))
            for it in us:
                val = it.get("value")
                prev = it.get("prev")
                vtxt = "待发布" if val is None else ("%.2f" % float(val))
                ptxt = ("%.2f" % float(prev)) if prev not in (None, "") else "—"
                card2.add_widget(self._row([
                    (it.get("name", ""), _WHITE, 0.34),
                    (vtxt, _TITLE if val is None else _WHITE, 0.22),
                    (ptxt, _HINT, 0.22),
                    (str(it.get("date", ""))[5:], _GREEN, 0.22),
                ], height=36, font_style="Body2"))
            card2.add_widget(self._meaning_line(
                "未公布（待发布）为即将到来的发布提醒；已公布显示最新值。"))
            self.body.add_widget(card2)
        else:
            self.body.add_widget(self._card_text("暂无美国发布日历数据"))

    def _china_rows(self, d):
        """中国指标最近两期：(名称, 本周期, 上周期, 数据期)。"""
        out = []

        def two(series, months, fmt):
            if not series or not months:
                return None
            n = min(len(series), len(months))
            if n == 0:
                return None
            cur = series[-1]
            prev = series[-2] if n > 1 else None
            if cur is None:
                cur = prev
                prev = None
            return (("%s" % fmt(cur)) if cur is not None else "—",
                    ("%s" % fmt(prev)) if prev is not None else "—",
                    market._month_short(months[-1]))

        inf = d.get("inflation", {})
        im = inf.get("months", {})
        iv = inf.get("series", {})
        liq = d.get("liquidity", {})
        lm = liq.get("months", {})
        lv = liq.get("series", {})
        ast = d.get("assets", {})
        am = ast.get("months", {})
        av = ast.get("series", {})
        pmi = d.get("pmi", {})

        def push(name, r):
            if r and r[0] != "—":
                out.append((name, r[0], r[1], r[2]))

        push("PMI", two(pmi.get("series", {}).get("PMI", []),
                        pmi.get("months", []), _FMT_PCT1))
        push("CPI同比", two(iv.get("CPI同比", []), im.get("cpi", []), _FMT_PCT1))
        push("PPI同比", two(iv.get("PPI同比", []), im.get("ppi", []), _FMT_PCT1))
        push("M1同比", two(lv.get("M1同比", []), lm.get("m", []), _FMT_PCT1))
        push("M2同比", two(lv.get("M2同比", []), lm.get("m", []), _FMT_PCT1))
        push("社融增量", two(lv.get("社融增量", []), lm.get("shrzgm", []), _FMT_YI))
        push("新增人民币贷款", two(lv.get("新增人民币贷款", []), lm.get("loan", []), _FMT_YI))
        push("1年期LPR", two(av.get("1年期LPR", []), am.get("lpr", []), _FMT_PCT2))
        return out

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

    def _hint_line(self, text):
        """小字说明行：单行（超出省略号省略显示）+ 数字/字母后不换行。"""
        lb = MDLabel(
            text=market._no_break_latin(text), font_style="Caption",
            theme_text_color="Custom",
            text_color=_HINT, size_hint_y=None, height=dp(18),
            valign="middle",
        )
        # 单行裁剪：size→text_size 单向绑定（不做动态字号，避免 Adreno 回调递归）
        lb.bind(size=lambda o, *a: setattr(o, "text_size", (o.width, o.height)))
        return lb

    def _meaning_line(self, text):
        """小字说明行：自适应换行（代表含义/对经济股市影响可较长）+ 数字后不换行。"""
        lb = MDLabel(
            text=market._no_break_latin(text), font_style="Caption",
            theme_text_color="Custom",
            text_color=_HINT, adaptive_height=True,
        )
        lb.bind(width=lambda o, *a: setattr(o, "text_size", (o.width, None)))
        return lb

    @staticmethod
    def _row(cells, height=_ROW_H, single_line=True, font_style="Body2"):
        """固定行高的行。

        每个 label 用 size_hint=(sx,None)+固定 height：这样 BoxLayout 的
        minimum_height 会累加行高（size_hint_y=1 会被忽略导致卡片高度不足、
        行与行重叠——用户实测发布表叠加），同时 text_size 绑定单行裁剪。
        """
        r = BoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(height),
            spacing=dp(4),
        )
        for text, color, sx in cells:
            lb = MDLabel(
                text=market._no_break_latin(text), size_hint=(sx, None),
                height=dp(height),
                theme_text_color="Custom", text_color=color,
                halign="left", valign="middle", font_style=font_style,
            )
            if single_line:
                # 单行裁剪：size→text_size 单向绑定
                lb.bind(size=lambda o, *a: setattr(o, "text_size", (o.width, o.height)))
            r.add_widget(lb)
        return r

    def _head_row(self, cols):
        return self._row([(c, _HINT, sx) for c, sx in cols], height=26)


def _hex(col):
    return "#%02x%02x%02x" % (int(col[0] * 255), int(col[1] * 255), int(col[2] * 255))


# 指标元数据：(公式, 意义：代表含义+对经济/股市影响, 格式化)
_PMI_META = [
    ("PMI", "官方制造业采购经理指数",
     "代表制造业整体景气度，>50扩张、<50收缩；是经济领先指标，回升利好周期股与大盘。", _FMT_PCT1),
    ("生产", "制造业生产指数",
     "代表企业生产活动强弱；走高利好制造业盈利预期与顺周期板块。", _FMT_PCT1),
    ("新订单", "制造业新订单指数",
     "代表需求端强弱，领先经济约1-3个月；上升利好成长与消费股。", _FMT_PCT1),
    ("产成品库存", "制造业产成品库存指数",
     "代表库存积压程度；过高预示去库存压力，对工业品价格与周期股偏空。", _FMT_PCT1),
    ("采购量", "制造业采购量指数",
     "代表企业原材料采购意愿；上升预示生产扩张，利好上游资源股。", _FMT_PCT1),
    ("原材料库存", "制造业原材料库存指数",
     "代表原材料备货水平；主动补库利好上游，被动累库偏空。", _FMT_PCT1),
]

_INFL_META = {
    "CPI同比": ("全国居民消费价格当月同比",
               "代表居民消费物价涨幅，通胀核心指标；温和通胀利好消费股，高通胀压制估值。", _FMT_PCT1),
    "PPI同比": ("工业品出厂价格当月同比",
               "代表生产端出厂价格，企业盈利风向标；回升利好周期/工业股，回落利好下游成本。", _FMT_PCT1),
    "PPIRM同比": ("工业生产者购进价格同比（上年同月=100换算）",
                 "代表上游原材料成本压力；上行压缩中游毛利，利好资源股，利空加工制造。", _FMT_PCT1),
}

_LIQ_META = {
    "M1同比": ("狭义货币(M1)供应量同比",
              "代表企业活期资金活跃度，领先经济与股市约3-6个月；回升利好风险资产。", _FMT_PCT1),
    "M2同比": ("广义货币(M2)供应量同比",
              "代表货币供应总量，宽松信号；高增利好资产价格，收紧则承压。", _FMT_PCT1),
    "社融增量": ("社会融资规模增量（亿元，商务部）",
                "代表实体经济融资总量，信用扩张信号；放量利好股市与经济周期。", _FMT_YI),
    "新增人民币贷款": ("金融机构新增人民币贷款（亿元）",
                     "代表银行信贷投放，信用脉冲；高增预示流动性宽松，利好成长股。", _FMT_YI),
}

_AST_META = {
    "伦敦金": ("伦敦金现货（美元/盎司，月末）",
              "避险资产；金价上涨反映避险/抗通胀情绪，股市风险偏好下降时同涨。", _FMT_GOLD),
    "中国10年国债": ("中债10年期国债收益率（%）",
                   "无风险利率基准，资产定价锚；上行压制股市估值，下行利好成长。", _FMT_PCT3),
    "1年期LPR": ("贷款市场报价利率 1 年期（%）",
                "贷款基准利率，政策利率传导；下调利好地产/成长，上调则承压。", _FMT_PCT2),
}

_DERIVE_META = {
    "pmi": {
        "经济势能": {"formula": "新订单−产成品库存",
                     "meaning": "代表需求与库存背离度，越正越旺；走高预示补库与生产扩张，利好周期股。",
                     "fmt": _FMT_PCT1},
        "供需差": {"formula": "生产−新订单",
                   "meaning": "代表产出与需求之差，为负=供过于求；走弱预示价格与盈利承压。",
                   "fmt": _FMT_PCT1},
        "备料差": {"formula": "采购量−原材料库存",
                   "meaning": "代表主动补库意愿，为负=主动备料；预示生产扩张，利好上游。",
                   "fmt": _FMT_PCT1},
        "TEC": {"formula": "Δ新订单−Δ产成品库存",
                "meaning": "代表近两期经济动能变化；转正=动能增强，对股市偏多。",
                "fmt": _FMT_PCT1},
    },
    "inflation": {
        "通胀预期指数": {"formula": "CPI同比−PPI同比",
                         "meaning": "代表消费与生产价格剪刀差；走阔=下游利润改善，利好消费股。",
                         "fmt": _FMT_PCT1},
    },
    "liquidity": {
        "M1-M2剪刀差": {"formula": "M1同比−M2同比",
                         "meaning": "代表资金活化度；走阔=企业活钱增加、利于股市，收窄=资金沉淀偏空。",
                         "fmt": _FMT_PCT1},
    },
    "assets": {
        "中国实际利率": {"formula": "1年期LPR−一线新房同比",
                         "meaning": "代表融资真实成本（房价涨幅近似通胀）；偏高压制投资与估值。",
                         "fmt": _FMT_PCT1},
        "GDP平减指数": {"formula": "现价GDP同比−不变价同比",
                         "meaning": "代表全社会价格水平变化，全面通胀指标；转正=经济回暖价格回升。",
                         "fmt": _FMT_PCT1},
    },
}
