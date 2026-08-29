# -*- coding: utf-8 -*-
"""牛票 · 趋势页（原牛门线分析界面改造）。

变化点（对照需求）：
  - 图表窗口 5 → 10 个交易日（config.DISPLAY_POINTS）；
  - 快捷按钮 = 查询名单前 3 个（watchlist.top(3)），长按删除；
  - 版本按钮可选（基础/标的/指数），自动默认 + 用户可切换；
  - 指标命名：YL 压力线、QL 止盈线、ZS 止损线；
  - 仅深色主题；顶栏与加载蒙层由 app/ui.py 外壳提供。
"""
import threading
import traceback
from datetime import date, datetime

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.utils import get_color_from_hex

from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDIconButton, MDRaisedButton
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel
try:  # KivyMD 1.1.x/1.2.x：MDSeparator 位于 kivymd.uix.card
    from kivymd.uix.card import MDSeparator
except ImportError:  # KivyMD 2.x：分隔线改名 MDDivider（kivymd.uix.divider）
    from kivymd.uix.divider import MDDivider as MDSeparator
from kivymd.uix.textfield import MDTextField
try:
    from kivymd.uix.pickers.datepicker import MDDatePicker
except ImportError:  # KivyMD 1.1.x 的旧路径
    from kivymd.uix.picker import MDDatePicker

from . import api, config, indicator, interpreter, market
from .chart import DateAxis, NMLChart, VolumePanel

CARD_RADIUS = [dp(14), dp(14), dp(14), dp(14)]
CARD_PADDING = [dp(14), dp(12), dp(14), dp(12)]
LEVEL_KIND_COLORS = {
    "压力": "#ffa726",
    "支撑": "#4dd0e1",
    "突破": "#ef5350",
    "提示": "#ffd166",
}
CHIP_BG = get_color_from_hex("#1c3a5e")


def _hex(col):
    return "#%02x%02x%02x" % (int(col[0] * 255), int(col[1] * 255), int(col[2] * 255))


def _fmt(v):
    return interpreter.fmt_price(v)


class NiumenPage:
    """趋势功能页（挂在底部导航第一页的 ScrollView 内）。"""

    def __init__(self, app):
        self.app = app
        self.rows = []                 # 原始K线（升序）
        self.bars = []                 # 指标结果（与 rows 等长）
        self.version = config.VERSION_BASIC
        self.code = config.DEFAULT_CODE
        self.source = ""
        self.stock_name = ""
        self.sel_idx = -1              # 选中日在 bars 中的下标
        self._last_code = config.DEFAULT_CODE

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------
    def build(self, box):
        """box：外壳传入的纵向 MDBoxLayout（位于 ScrollView 内）。"""
        self._build_search(box)
        self._build_info_card(box)
        self._build_chart_card(box)
        # 版本按钮放到图表下方（需求：离图更近，搜索区只留查询+快捷按钮）
        box.add_widget(self.version_row)
        self._build_values_card(box)
        self._build_judgment_card(box)
        # 本页最下方：操作规则标注 + 免责声明（需求）
        self._build_rules_card(box)

    def _build_search(self, box):
        row = MDBoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(58), spacing=dp(8),
        )
        self.input_field = MDTextField(
            hint_text="输入代码 如 159516 / 600519 / sh000001 / HSTECH",
            size_hint=(1, None), height=dp(56),
        )
        row.add_widget(self.input_field)
        btn = MDRaisedButton(
            text="查询", size_hint=(None, None), width=dp(80), height=dp(48),
            pos_hint={"center_y": 0.5},
        )
        btn.elevation = 0  # 阴影在 Adreno 崩溃
        btn.bind(on_release=lambda x: self.on_query(self.input_field.text))
        row.add_widget(btn)
        box.add_widget(row)

        # 版本选择：基础主图版 / 标的版 / 指数版（需求：自动默认 + 用户可切换）。
        # 按钮构建在这里，但挂到图表下方（见 build()）。
        self.version_row = MDBoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(40), spacing=dp(8),
        )
        self.version_btns = {}
        for key in (config.VERSION_BASIC, config.VERSION_STOCK, config.VERSION_INDEX):
            b = MDRaisedButton(
                text=config.VERSION_NAMES[key], size_hint_x=1,
                size_hint_y=None, height=dp(34), md_bg_color=CHIP_BG,
                text_color=(1, 1, 1, 1), font_size=dp(11),
            )
            b.elevation = 0
            b._version = key
            b.bind(on_release=lambda x: self._set_version(x._version))
            self.version_row.add_widget(b)
            self.version_btns[key] = b

        # 快捷按钮：查询名单前 3 个
        self.chips_row = MDBoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(40), spacing=dp(8),
        )
        box.add_widget(self.chips_row)
        self._refresh_chips()

    def _set_version(self, version):
        """用户手动切换版本：重算当前代码的指标并刷新。"""
        if not self.code:
            self.app._toast("请先查询代码")
            return
        self.version = version
        self._highlight_version()
        try:
            self.bars = indicator.compute(self.rows, self.version)
            self.sel_idx = len(self.bars) - 1
            self._update_all()
        except Exception:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            self.app._toast("切换版本失败")

    def _highlight_version(self):
        for key, b in self.version_btns.items():
            b.md_bg_color = get_color_from_hex("#1565c0") if key == self.version else CHIP_BG

    def _refresh_chips(self):
        """按查询名单前 3 个重建快捷按钮；长按从名单移除。

        需求：名称强制单行（chars_per_line=8 字符宽，超长截断），
        避免 ETF 名称两行与单行名称（如澜起科技）混排高度不齐。
        """
        from .batch import name_display
        self.chips_row.clear_widgets()
        for item in self.app.watchlist.top(3):
            name = item["name"]
            text, _lines = name_display(name, chars_per_line=8, max_lines=1)
            b = MDRaisedButton(
                text=text, size_hint_x=1, size_hint_y=None, height=dp(36),
                md_bg_color=CHIP_BG, text_color=(1, 1, 1, 1),
                font_size=dp(14), halign="center", valign="center",
            )
            b.elevation = 0
            b._code = item["code"]
            b.bind(on_release=lambda x: self._chip_release(x))
            self._bind_long_press(b, lambda w: self._chip_remove(w))
            self.chips_row.add_widget(b)

    def _chip_release(self, w):
        if getattr(w, "_lp_fired", False):
            return
        self.on_query(w._code)

    def _chip_remove(self, w):
        code = w._code
        self.app.watchlist.remove(code)
        self.app._toast("已从名单移除：%s" % code)
        self._refresh_chips()

    @staticmethod
    def _bind_long_press(widget, cb):
        """给按钮绑定长按回调（0.6s），触发后抑制随后的 on_release 查询。"""
        def td(w, touch):
            if w.collide_point(*touch.pos):
                w._lp_armed = True
                w._lp_fired = False
                w._lp_ev = Clock.schedule_once(lambda dt: _fire(w), 0.6)
            return w._orig_td(touch)

        def tu(w, touch):
            if getattr(w, "_lp_armed", False):
                w._lp_armed = False
                if getattr(w, "_lp_ev", None):
                    w._lp_ev.cancel()
            return w._orig_tu(touch)

        def _fire(w):
            if getattr(w, "_lp_armed", False):
                w._lp_armed = False
                w._lp_fired = True
                try:
                    cb(w)
                except Exception:  # noqa: BLE001
                    pass

        widget._orig_td = widget.on_touch_down
        widget._orig_tu = widget.on_touch_up
        widget.on_touch_down = lambda touch: td(widget, touch)
        widget.on_touch_up = lambda touch: tu(widget, touch)

    def _build_info_card(self, box):
        self.info_card = MDCard(
            orientation="vertical",
            padding=CARD_PADDING, spacing=dp(2),
            radius=CARD_RADIUS, elevation=0, size_hint_y=None,  # 阴影在 Adreno 崩溃
        )
        self.info_card.bind(minimum_height=self.info_card.setter("height"))
        # 名称行：小号字（与下方日期数字一致），不突出（需求）
        self.name_label = MDLabel(
            text="—", font_style="Subtitle2", adaptive_height=True,
            theme_text_color="Secondary",
        )
        self.info_card.add_widget(self.name_label)

        date_row = MDBoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(44), spacing=dp(4),
        )
        self.date_label = MDLabel(
            text="—", adaptive_height=True, size_hint_x=1, valign="middle",
            pos_hint={"center_y": 0.5},
        )
        date_btn = MDIconButton(
            icon="calendar", theme_icon_color="Custom",
            icon_color=get_color_from_hex("#8ab4f8"),
            size_hint=(None, None), size=(dp(36), dp(36)),
            pos_hint={"center_y": 0.5},
        )
        date_btn.bind(on_release=self.open_date_picker)
        date_row.add_widget(self.date_label)
        date_row.add_widget(date_btn)
        self.info_card.add_widget(date_row)
        box.add_widget(self.info_card)

    def _build_chart_card(self, box):
        # 图表卡片：主图 + 成交额副图（位于主图下方）+ 日期轴。
        # 各线名称/颜色/数值/状态统一在下方"分析"卡列出，避免重复介绍。
        self.chart_card = MDCard(
            orientation="vertical",
            padding=[dp(6), dp(10), dp(6), dp(6)], spacing=dp(2),
            radius=CARD_RADIUS, elevation=0, size_hint_y=None,
        )
        self.chart_card.bind(minimum_height=self.chart_card.setter("height"))
        self.chart = NMLChart()
        self.volume = VolumePanel()
        self.date_axis = DateAxis()
        self.chart_card.add_widget(self.chart)
        self.chart_card.add_widget(self.volume)
        self.chart_card.add_widget(self.date_axis)
        box.add_widget(self.chart_card)

    def _build_values_card(self, box):
        self.values_card = MDCard(
            orientation="vertical",
            padding=CARD_PADDING, spacing=dp(2),
            radius=CARD_RADIUS, elevation=0, size_hint_y=None,
        )
        self.values_card.bind(minimum_height=self.values_card.setter("height"))
        self.close_label = MDLabel(
            text="—", font_style="H5", adaptive_height=True,
            theme_text_color="Custom", text_color=config.COLOR_UP,
        )
        # 数值明细行：用逐行 BoxLayout（名称/数值/●/百分比 固定列宽），
        # 保证 ● 纵向对齐（需求：⚪ 上下对齐美观）
        self.values_box = MDBoxLayout(
            orientation="vertical", spacing=dp(2), adaptive_height=True,
        )
        self.values_card.add_widget(self.close_label)
        self.values_card.add_widget(self.values_box)
        box.add_widget(self.values_card)

    @staticmethod
    def _values_row(label, col, value, pct):
        """一行明细：名称(自适应) + 数值(固定右对齐) + ●(固定) + 百分比(固定右对齐)。

        单行保证方案：按文本长度与列宽自适应字号（不用 shorten/text_size 递归绑定，
        避免 Kivy 上 size→text_size 无限循环崩溃），所有单元格固定行高填满。
        """
        dot_col = config.COLOR_UP if pct >= 0 else config.COLOR_DOWN
        row = MDBoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(26), spacing=dp(2),
        )

        def _fit_font(text, width, base=12):
            """估算字号：全角≈1.0em、半角≈0.55em，目标在 width 内单行放下。"""
            est = 0.0
            for ch in text:
                est += 1.0 if ord(ch) > 0x2E7F else 0.55
            if est <= 0:
                return base
            return max(8, min(base, int(width / (est * dp(1)) * 0.94)))

        def _cell(text, width, tc, align):
            lb = MDLabel(
                text=text, size_hint=(None, 1), width=dp(width),
                theme_text_color="Custom", text_color=tc,
                halign=align, valign="middle", font_style="Body2",
                font_size=dp(_fit_font(text, width)),
            )
            return lb

        name_lb = MDLabel(
            text=label, size_hint_x=1, size_hint_y=1,
            theme_text_color="Custom", text_color=col,
            halign="left", valign="middle", font_style="Body2",
        )
        # 名称列宽自适应：行总宽减去固定列后剩余；字号随名称长度收缩
        name_lb.bind(width=lambda o, *a: setattr(
            o, "font_size", dp(_fit_font(o.text, o.width))))
        row.add_widget(name_lb)
        row.add_widget(_cell(value, 88, (1, 1, 1, 1), "right"))
        row.add_widget(_cell("●", 18, dot_col, "center"))
        row.add_widget(_cell("%+.1f%%" % pct, 74, dot_col, "right"))
        return row

    def _build_judgment_card(self, box):
        self.judgment_card = MDCard(
            orientation="vertical",
            padding=CARD_PADDING, spacing=dp(4),
            radius=CARD_RADIUS, elevation=0, size_hint_y=None,
        )
        self.judgment_card.bind(minimum_height=self.judgment_card.setter("height"))
        self.verdict_label = MDLabel(
            text="结构判断：—", font_style="H6", adaptive_height=True,
            theme_text_color="Custom", text_color=config.COLOR_UP,
        )
        # 需求：操作建议字体缩小（与规则段落呼应）
        self.advice_label = MDLabel(
            text="操作建议：—", font_style="Subtitle1", adaptive_height=True,
            theme_text_color="Custom", text_color=config.COLOR_UP,
        )
        self.stage_label = MDLabel(text="阶段：—", font_style="Subtitle1", adaptive_height=True)
        # 需求：图表/阶段下方的判读明细与价位明细四行无价值，删除
        self.judgment_card.add_widget(self.verdict_label)
        self.judgment_card.add_widget(self.advice_label)
        self.judgment_card.add_widget(self.stage_label)
        box.add_widget(self.judgment_card)

    def _build_rules_card(self, box):
        """本页最下方：操作规则标注（每个规则一个自然段落，小字）+ 免责声明（需求）。

        段落内用 text_size 绑宽自然换行；关键短语（15%总额试仓、20日/60日成本线等）
        内部用不换行空格(\u00A0)，避免在数字与单位之间断行。
        """
        self.rules_card = MDCard(
            orientation="vertical",
            padding=CARD_PADDING, spacing=dp(3),
            radius=CARD_RADIUS, elevation=0, size_hint_y=None,
        )
        self.rules_card.bind(minimum_height=self.rules_card.setter("height"))
        self.rules_card.add_widget(MDLabel(
            text="操作规则", font_style="Subtitle2", bold=True,
            theme_text_color="Custom", text_color=get_color_from_hex("#8ab4f8"),
            adaptive_height=True,
        ))
        rules = [
            "规则1\u00A0追上涨：柱状线实体与YLX产生分离后，首次接触YLX可考虑进入"
            "15%\u00A0总额试仓；但出现红三兵、下锤线、个股与板块/大盘/行业趋势相背离时不要追。",
            "规则2\u00A0拿成本：大幅跌破20日/60日\u00A0成本线可考虑收集成本，每次最多增加"
            "25%\u00A0总额。",
            "规则3\u00A0快卖出：突破止盈线卖出，并结合其它趋势判断卖出额度。",
        ]
        # 数字/字母后不换行兜底（YLX/15%等边界）
        rules = [market._no_break_latin(r) for r in rules]
        for r in rules:
            lb = MDLabel(
                text=r, font_style="Caption",
                theme_text_color="Secondary", adaptive_height=True,
            )
            # 自然换行：text_size 限宽（高度不限），Kivy 按词断行
            lb.bind(width=lambda o, *a: setattr(o, "text_size", (o.width, None)))
            self.rules_card.add_widget(lb)
        self.rules_card.add_widget(MDSeparator())
        self.rules_card.add_widget(MDLabel(
            text="免责声明：本页指标与规则仅供技术分析参考，不构成任何投资建议；"
                 "股市有风险，入市需谨慎，据此操作盈亏自负。",
            font_style="Caption", theme_text_color="Hint", adaptive_height=True,
        ))
        box.add_widget(self.rules_card)

    # 注：原"自选名单"历史卡已按需求删除；查询记录仍会写入 watchlist
    # （供快捷按钮前3个与批量页"近期查询"按钮使用），长按快捷按钮可移除单条。

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------
    def on_query(self, code=None, *args):
        raw = (code or self.input_field.text or "").strip()
        if not raw:
            self.app._toast("请输入代码")
            return
        try:
            code = api.normalize_code(raw)
        except ValueError as e:
            self.app._toast(str(e))
            return
        self._last_code = code
        self.app.last_code = code   # 供枢轴点页共享默认股票（需求 4）
        self.input_field.text = code
        self.app.show_loading(True)
        # 请求序号：快速连点时丢弃过期线程的返回
        self._req_seq = getattr(self, "_req_seq", 0) + 1
        seq = self._req_seq

        def work():
            try:
                res = api.fetch_klines(code)
                Clock.schedule_once(lambda dt: self._on_fetch_ok(code, res, seq), 0)
            except Exception as e:  # noqa: BLE001
                Clock.schedule_once(lambda dt, err=e: self._on_fetch_err(code, err, seq), 0)

        threading.Thread(target=work, daemon=True).start()

    def _on_fetch_ok(self, code, res, seq):
        if seq != getattr(self, "_req_seq", -1):
            return
        try:
            self.app.show_loading(False)
            self.code = code
            self.rows = res["rows"]
            self.source = res["source"]
            self.stock_name = res["name"] or code
            self.version = api.detect_version(code)
            self._highlight_version()
            self.bars = indicator.compute(self.rows, self.version)
            self.sel_idx = len(self.bars) - 1
            self._update_all()
            # 记录查询名单（最新在前；供快捷按钮与批量"近期查询"使用）
            self.app.watchlist.touch(code, self.stock_name)
            self._refresh_chips()
            self.app.notify_first_load_done()
        except Exception:  # noqa: BLE001
            self.app.show_loading(False)
            msg = "数据处理失败（%s）：\n%s" % (code, traceback.format_exc())
            print("[牛票] %s" % msg)
            self.app._show_crash(msg)

    def _on_fetch_err(self, code, err, seq):
        if seq != getattr(self, "_req_seq", -1):
            return
        self.app.show_loading(False)
        self.app._toast(str(err))
        self.name_label.text = "查询失败：%s" % code
        self.name_label.text_color = config.COLOR_DOWN
        self.verdict_label.text = "结构判断：—"
        self.stage_label.text = "阶段：—"
        self.app.notify_first_load_done()

    def open_date_picker(self, *args):
        if not self.bars:
            self.app._toast("请先查询代码")
            return
        sel = self.bars[self.sel_idx]
        dt = datetime.strptime(sel["date"], "%Y-%m-%d").date()
        first = datetime.strptime(self.bars[0]["date"], "%Y-%m-%d").date()
        dlg = MDDatePicker(
            year=dt.year, month=dt.month, day=dt.day,
            min_date=first, max_date=date.today(),
        )
        try:
            dlg.elevation = 0
        except Exception:  # noqa: BLE001
            pass
        dlg.bind(on_save=self.on_date_save)
        dlg.open()

    def on_date_save(self, instance, value, date_range):
        target = value.strftime("%Y-%m-%d")
        idx = -1
        for i, b in enumerate(self.bars):
            if b["date"] <= target:
                idx = i
            else:
                break
        if idx < 0:
            self.app._toast("所选日期无数据")
            return
        self.sel_idx = idx
        self._update_all()

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------
    def _update_all(self):
        if self.sel_idx < 0 or not self.bars:
            return
        self._update_info()
        self._update_chart()
        self._update_values()
        self._update_judgment()

    def _update_info(self):
        b = self.bars[self.sel_idx]
        self.name_label.text = "%s  %s" % (self.stock_name or self.code, self.code)
        self.date_label.text = "截至交易日：%s" % b["date"]

    def _update_chart(self):
        start = max(0, self.sel_idx - (config.DISPLAY_POINTS - 1))
        end = self.sel_idx
        keys = [
            (config.IND_YL, config.COLOR_NML, "nml"),
            (config.IND_QL, config.COLOR_QRL, "qrl"),
            (config.IND_ZS, config.COLOR_SMX, "smx"),
        ]
        if self.version != config.VERSION_BASIC:
            keys += [
                ("CBX20", config.COLOR_CBX20, "cbx20"),
                ("CBX60", config.COLOR_CBX60, "cbx60"),
            ]
        lines = []
        for label, col, key in keys:
            lines.append((label, col, [self.bars[i][key] for i in range(start, end + 1)]))
        window = self.bars[start:end + 1]
        self.chart.set_data(window, lines, end - start)
        # 主图按纵坐标标签实际宽度收紧左侧预留；副图/日期轴同步对齐（需求）
        pad_l = self.chart.pad_l
        self.volume.set_pad_l(pad_l)
        self.date_axis.set_pad_l(pad_l)
        self.volume.set_data(window)
        self.date_axis.set_dates([b["date"] for b in window])

    def _update_values(self):
        b = self.bars[self.sel_idx]
        close = b["close"]
        chg = None
        if self.sel_idx > 0:
            prev = self.rows[self.sel_idx - 1]["close"]
            if prev:
                chg = (close - prev) / prev * 100.0
        txt = "收盘 %s" % _fmt(close)
        if chg is not None:
            txt += "    %s%.2f%%" % ("+" if chg >= 0 else "", chg)
        self.close_label.text = txt
        self.close_label.text_color = config.COLOR_UP if (chg or 0) >= 0 else config.COLOR_DOWN

        res = interpreter.interpret(b, self.version)
        keys = [
            ("nml", config.IND_NAMES["yl"], config.COLOR_NML),
            ("qrl", config.IND_NAMES["ql"], config.COLOR_QRL),
            ("smx", config.IND_NAMES["zs"], config.COLOR_SMX),
        ]
        if self.version != config.VERSION_BASIC:
            keys += [
                ("cbx20", config.IND_NAMES["cbx20"], config.COLOR_CBX20),
                ("cbx60", config.IND_NAMES["cbx60"], config.COLOR_CBX60),
            ]
        # 按数值从大到小排列（需求 1：上面数值大于下面数值）
        rows_data = []
        for key, label, col in keys:
            v = b.get(key)
            if v is None:
                continue
            # 需求：状态文字（未突破/逼近/上方…）改为 数值 + 距收盘百分比
            pct = (close - v) / v * 100.0 if v else 0.0
            rows_data.append((v, label, col, pct))
        rows_data.sort(key=lambda x: x[0], reverse=True)
        self.values_box.clear_widgets()
        for v, label, col, pct in rows_data:
            self.values_box.add_widget(self._values_row(label, col, _fmt(v), pct))

    def _update_judgment(self):
        b = self.bars[self.sel_idx]
        res = interpreter.interpret(b, self.version)
        self.verdict_label.text = "结构判断：%s" % res["verdict"]
        self.verdict_label.text_color = res["verdict_color"]
        self.advice_label.text = "操作建议：%s" % res["advice"]
        self.advice_label.text_color = res["advice_color"]
        self.stage_label.text = "阶段：%s" % res["stage"]
