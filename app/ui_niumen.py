# -*- coding: utf-8 -*-
"""牛票 · 牛门线页（原牛门线分析界面改造）。

变化点（对照需求）：
  - 图表窗口 5 → 10 个交易日（config.DISPLAY_POINTS）；
  - 快捷按钮 = 查询名单前 3 个（watchlist.top(3)），长按删除，底部名单管理卡（删除/清空）；
  - 仅深色主题（深浅切换按钮移除）；
  - 顶栏与加载蒙层由 app/ui.py 外壳提供。
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

from . import api, config, indicator, interpreter
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
    """牛门线功能页（挂在底部导航第一页的 ScrollView 内）。"""

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
        self._build_values_card(box)
        self._build_judgment_card(box)

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

        # 快捷按钮：查询名单前 3 个
        self.chips_row = MDBoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(40), spacing=dp(8),
        )
        box.add_widget(self.chips_row)
        self._refresh_chips()

    def _refresh_chips(self):
        """按查询名单前 3 个重建快捷按钮；长按从名单移除。

        名称 ≤4 字用大号字；更长则缩字号并允许两行显示（需求 3）。
        """
        self.chips_row.clear_widgets()
        for item in self.app.watchlist.top(3):
            name = item["name"]
            n = len(name)
            if n > 4:
                height, font = dp(46), 11
            else:
                height, font = dp(36), 14
            b = MDRaisedButton(
                text=name, size_hint_x=1, size_hint_y=None, height=height,
                md_bg_color=CHIP_BG, text_color=(1, 1, 1, 1),
                font_size=dp(font), halign="center", valign="center",
            )
            b.elevation = 0
            if n > 4:
                # 长名称允许换行（两行）
                b.bind(width=lambda w, *a: setattr(
                    w, "text_size", (w.width - dp(8), None)))
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
        self.name_label = MDLabel(text="—", font_style="H6", adaptive_height=True)
        self.meta_label = MDLabel(
            text="—", font_style="Caption",
            theme_text_color="Secondary", adaptive_height=True,
        )
        self.info_card.add_widget(self.name_label)
        self.info_card.add_widget(self.meta_label)

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
        self.values_label = MDLabel(
            text="", markup=True, font_style="Body1", adaptive_height=True,
        )
        self.values_card.add_widget(self.close_label)
        self.values_card.add_widget(self.values_label)
        box.add_widget(self.values_card)

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
        self.advice_label = MDLabel(
            text="操作建议：—", font_style="H6", adaptive_height=True,
            theme_text_color="Custom", text_color=config.COLOR_UP,
        )
        self.stage_label = MDLabel(text="阶段：—", font_style="Subtitle1", adaptive_height=True)
        self.summary_label = MDLabel(
            text="", markup=True, font_style="Body1",
            theme_text_color="Secondary", adaptive_height=True,
        )
        self.levels_label = MDLabel(
            text="", markup=True, font_style="Body2", adaptive_height=True,
        )
        self.judgment_card.add_widget(self.verdict_label)
        self.judgment_card.add_widget(self.advice_label)
        self.judgment_card.add_widget(self.stage_label)
        self.judgment_card.add_widget(MDSeparator())
        self.judgment_card.add_widget(self.summary_label)
        self.judgment_card.add_widget(self.levels_label)
        box.add_widget(self.judgment_card)

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
        self.meta_label.text = str(err)
        self.verdict_label.text = "结构判断：—"
        self.stage_label.text = "阶段：—"
        self.summary_label.text = ""
        self.levels_label.text = ""
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
        ver_name = config.VERSION_NAMES.get(self.version, self.version)
        cost_note = ""
        if self.version != config.VERSION_BASIC:
            basis = b.get("cost_basis", "estimate")
            cost_note = "（成交额口径）" if basis == "amount" else "（估算口径）"
        self.name_label.text = "%s  %s" % (self.stock_name or self.code, self.code)
        self.meta_label.text = "数据源：%s · 版本：%s%s" % (self.source or "—", ver_name, cost_note)
        self.date_label.text = "截至交易日：%s" % b["date"]

    def _update_chart(self):
        start = max(0, self.sel_idx - (config.DISPLAY_POINTS - 1))
        end = self.sel_idx
        keys = [
            ("NML", config.COLOR_NML, "nml"),
            ("QRL", config.COLOR_QRL, "qrl"),
            ("SMX", config.COLOR_SMX, "smx"),
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
            ("nml", "NML 牛门线", config.COLOR_NML),
            ("qrl", "QRL 强阻力线", config.COLOR_QRL),
            ("smx", "SMX 生命线", config.COLOR_SMX),
        ]
        if self.version != config.VERSION_BASIC:
            keys += [
                ("cbx20", "CBX20 短期成本", config.COLOR_CBX20),
                ("cbx60", "CBX60 中期成本", config.COLOR_CBX60),
            ]
        # 按数值从大到小排列（需求 1：上面数值大于下面数值）
        rows_data = []
        for key, label, col in keys:
            v = b.get(key)
            if v is None:
                continue
            # 需求：状态文字（未突破/逼近/上方…）改为 数值 + 距收盘百分比
            pct = (close - v) / v * 100.0 if v else 0.0
            rows_data.append((v, key, label, col, pct))
        rows_data.sort(key=lambda x: x[0], reverse=True)
        rows_html = []
        for v, key, label, col, pct in rows_data:
            dot_col = _hex(config.COLOR_UP) if pct >= 0 else _hex(config.COLOR_DOWN)
            rows_html.append(
                "[color=%s]%s[/color]  %s   [color=%s]●[/color] %+.1f%%"
                % (_hex(col), label, _fmt(v), dot_col, pct)
            )
        self.values_label.text = "\n".join(rows_html)

    def _update_judgment(self):
        b = self.bars[self.sel_idx]
        res = interpreter.interpret(b, self.version)
        self.verdict_label.text = "结构判断：%s" % res["verdict"]
        self.verdict_label.text_color = res["verdict_color"]
        self.advice_label.text = "操作建议：%s" % res["advice"]
        self.advice_label.text_color = res["advice_color"]
        self.stage_label.text = "阶段：%s" % res["stage"]
        self.summary_label.text = res["summary"]
        # 关键位不再重复数值（数值已在图下方"分析"卡的明细中列出；需求 2）
        lines = []
        for kind, label, value, note in res["levels"]:
            col = LEVEL_KIND_COLORS.get(kind, "#ffffff")
            lines.append(
                "[color=%s]●[/color] %s %s %s" % (col, kind, label, note)
            )
        self.levels_label.text = "\n".join(lines)
