# -*- coding: utf-8 -*-
"""牛票 · 批量枢轴点页（移植 BatchStock V1.x，KivyMD 重写）。

多行代码批量计算：逐代码抓取 → 单选算法 → 结果表格 + 一键复制全部。
数据源自动选择（新浪 → 腾讯），不显示切换。
"""
import threading
import time
from datetime import date

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.utils import get_color_from_hex

from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDIconButton, MDRaisedButton
from kivymd.uix.label import MDLabel
from kivymd.uix.textfield import MDTextField
try:
    from kivymd.uix.pickers.datepicker import MDDatePicker
except ImportError:
    from kivymd.uix.picker import MDDatePicker

from . import api, batch, config, pivot
from .clipboard import copy_text
from .ui_pivot import _Cell, MODE_DAILY, MODE_WEEKLY

_RED = get_color_from_hex("#ef5350")
_GREEN = get_color_from_hex("#66bb6a")
_BLUE = get_color_from_hex("#64b5f6")
_GREY = (0.72, 0.74, 0.78, 1.0)


class BatchPage:
    """批量枢轴点功能页。"""

    def __init__(self, app):
        self.app = app
        self.mode = MODE_DAILY
        self.target_date = date.today()
        self.algo_idx = 0
        self._busy = False
        self._rows = []

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------
    def build(self, box):
        self.code_input = MDTextField(
            hint_text="每行一个代码，如：\n159516\n562800\n159845",
            multiline=True, size_hint_y=None, height=dp(110),
        )
        box.add_widget(self.code_input)

        # 模式 + 算法 + 日期
        row1 = MDBoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(44), spacing=dp(8),
        )
        self.mode_daily = MDRaisedButton(
            text="按日", size_hint=(None, None), width=dp(56), height=dp(34),
        )
        self.mode_weekly = MDRaisedButton(
            text="按周", size_hint=(None, None), width=dp(56), height=dp(34),
        )
        self.mode_daily.elevation = 0
        self.mode_weekly.elevation = 0
        self.mode_daily.bind(on_release=lambda x: self._set_mode(MODE_DAILY))
        self.mode_weekly.bind(on_release=lambda x: self._set_mode(MODE_WEEKLY))
        self.algo_btn = MDRaisedButton(
            text="", size_hint=(None, None), width=dp(110), height=dp(34),
        )
        self.algo_btn.elevation = 0
        self.algo_btn.bind(on_release=lambda x: self._cycle_algo())
        row1.add_widget(self.mode_daily)
        row1.add_widget(self.mode_weekly)
        row1.add_widget(self.algo_btn)
        box.add_widget(row1)
        self._set_mode(self.mode)
        self._cycle_algo()

        row2 = MDBoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(44), spacing=dp(8),
        )
        self.date_label = MDLabel(
            text="指定日期：%s" % self.target_date.strftime("%Y-%m-%d"),
            adaptive_height=True, size_hint_x=1, valign="middle",
        )
        date_btn = MDIconButton(
            icon="calendar", theme_icon_color="Custom",
            icon_color=get_color_from_hex("#8ab4f8"),
        )
        date_btn.bind(on_release=lambda x: self._open_date_picker())
        self.calc_btn = MDRaisedButton(
            text="批量计算", size_hint=(None, None), width=dp(100), height=dp(36),
        )
        self.calc_btn.elevation = 0
        self.calc_btn.bind(on_release=lambda x: self.on_calc())
        row2.add_widget(self.date_label)
        row2.add_widget(date_btn)
        row2.add_widget(self.calc_btn)
        box.add_widget(row2)

        self.status_label = MDLabel(
            text="就绪", font_style="Caption", theme_text_color="Hint",
            adaptive_height=True,
        )
        box.add_widget(self.status_label)

        self.results_box = MDBoxLayout(
            orientation="vertical", spacing=dp(2), adaptive_height=True,
        )
        box.add_widget(self.results_box)

        box.add_widget(MDLabel(
            text="代码支持：600519 / sz159516 / HSTECH 等（每行一个，可用逗号/空格分隔）\n"
                 "统一数据源：腾讯财经（默认）→ 新浪财经（备用）\n"
                 "点击单元格复制，底部可一键复制全部结果\n"
                 "指标仅供技术分析参考，不构成投资建议",
            font_style="Caption", theme_text_color="Hint",
            adaptive_height=True, halign="center",
        ))

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------
    def _set_mode(self, mode):
        self.mode = mode
        active = get_color_from_hex("#1565c0")
        idle = get_color_from_hex("#263238")
        self.mode_daily.md_bg_color = active if mode == MODE_DAILY else idle
        self.mode_weekly.md_bg_color = active if mode == MODE_WEEKLY else idle
        self.mode_daily.text_color = (1, 1, 1, 1)
        self.mode_weekly.text_color = (1, 1, 1, 1)

    def _cycle_algo(self):
        self.algo_idx = (self.algo_idx + 1) % len(config.PIVOT_ALGORITHMS)
        self.algo_btn.text = "算法：%s ▾" % config.PIVOT_ALGORITHMS[self.algo_idx]

    def _open_date_picker(self):
        dlg = MDDatePicker(
            year=self.target_date.year, month=self.target_date.month,
            day=self.target_date.day, max_date=date.today(),
        )
        try:
            dlg.elevation = 0
        except Exception:  # noqa: BLE001
            pass
        dlg.bind(on_save=lambda inst, value, dr: self._on_date(value))
        dlg.open()

    def _on_date(self, value):
        self.target_date = value
        self.date_label.text = "指定日期：%s" % value.strftime("%Y-%m-%d")

    def on_calc(self):
        if self._busy:
            return
        raw = (self.code_input.text or "").strip()
        codes = pivot.parse_batch_codes(raw)
        if not codes:
            self.app._toast("未解析到有效股票代码")
            return
        self._busy = True
        self.calc_btn.disabled = True
        self.results_box.clear_widgets()
        algorithm = config.PIVOT_ALGORITHMS[self.algo_idx]
        weekly = self.mode == MODE_WEEKLY
        total = len(codes)

        def work():
            rows = []
            for i, code in enumerate(codes, 1):
                Clock.schedule_once(lambda dt, i=i, code=code: self._set_status(
                    "处理中 %d/%d：%s" % (i, total, code)), 0)
                row = {"idx": i, "code": code, "status": "error",
                       "name": "获取失败", "pp": "-", "r1": "-", "s1": "-",
                       "r2": "-", "s2": "-", "r3": "-", "s3": "-",
                       "r4": "-", "s4": "-"}
                try:
                    res = api.fetch_pivot_quote(code, self.target_date, weekly=weekly)
                    if res.get("ok"):
                        piv = pivot.calculate_single_pivot(
                            res["high"], res["low"], res["close"], res["open"], algorithm)
                        row.update({
                            "name": res["name"],
                            "pp": piv["pp"], "r1": piv["r1"], "s1": piv["s1"],
                            "r2": piv["r2"], "s2": piv["s2"], "r3": piv["r3"],
                            "s3": piv["s3"], "r4": piv["r4"], "s4": piv["s4"],
                            "status": "ok",
                        })
                    else:
                        row["name"] = res.get("msg", "获取失败")[:12]
                except Exception as e:  # noqa: BLE001
                    row["name"] = ("异常：" + str(e))[:12]
                rows.append(row)
                time.sleep(0.3)
            Clock.schedule_once(lambda dt: self._on_done(rows, algorithm, weekly), 0)

        threading.Thread(target=work, daemon=True).start()

    def _set_status(self, text):
        self.status_label.text = text

    def _on_done(self, rows, algorithm, weekly):
        self._busy = False
        self.calc_btn.disabled = False
        self._rows = rows
        ok, err = batch.batch_summary(rows)
        self.status_label.text = ("就绪 | 共 %d 条 | 成功 %d 失败 %d | 算法：%s | %s"
                                  % (len(rows), ok, err, algorithm,
                                     "按周" if weekly else "按日"))
        self._build_table(rows)

    def _build_table(self, rows):
        self.results_box.clear_widgets()
        summary = MDLabel(
            text="计算完成：成功 %d 条，失败 %d 条" % batch.batch_summary(rows),
            font_style="Subtitle1", adaptive_height=True,
        )
        self.results_box.add_widget(summary)

        def copy_cb(text):
            if copy_text(text):
                self.app._toast("已复制：%s" % text)
            else:
                self.app._toast("复制失败")

        # 表头
        headers = [("代码", 46), ("名称", 54), ("PP", 32), ("R1", 32), ("S1", 32),
                   ("R2", 32), ("S2", 32), ("R3", 32), ("S3", 32), ("R4", 32), ("S4", 32)]
        hrow = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(30))
        for title, w in headers:
            hrow.add_widget(_Cell(title, color=_GREY, bold=True,
                                  size_hint_x=None, width=dp(w), on_copy=None))
        self.results_box.add_widget(hrow)

        for r in rows:
            row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(28))
            name = batch.truncate_name(r["name"], 6)
            cells = [
                (r["code"], _GREY, 46),
                (name, _GREY if r["status"] == "error" else (1, 1, 1, 1), 54),
                (r["pp"], _BLUE, 32),
                (r["r1"], _RED, 32), (r["s1"], _GREEN, 32),
                (r["r2"], _RED, 32), (r["s2"], _GREEN, 32),
                (r["r3"], _RED, 32), (r["s3"], _GREEN, 32),
                (r["r4"], _RED, 32), (r["s4"], _GREEN, 32),
            ]
            for text, color, w in cells:
                row.add_widget(_Cell(str(text), color=color,
                                     size_hint_x=None, width=dp(w), on_copy=copy_cb))
            self.results_box.add_widget(row)

        # 一键复制全部
        copy_btn = MDRaisedButton(
            text="复制全部结果", size_hint=(None, None),
            width=dp(160), height=dp(38),
        )
        copy_btn.elevation = 0
        copy_btn.bind(on_release=lambda x: self._copy_all())
        btn_row = MDBoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(44),
            padding=[dp(0), dp(4), dp(0), dp(4)],
        )
        btn_row.add_widget(copy_btn)
        self.results_box.add_widget(btn_row)

    def _copy_all(self):
        if not self._rows:
            self.app._toast("暂无结果")
            return
        text = batch.all_rows_text(self._rows)
        if copy_text(text):
            self.app._toast("已复制全部结果")
        else:
            self.app._toast("复制失败")
