# -*- coding: utf-8 -*-
"""牛票 · 枢轴点页（单股，移植 StockPivot V1.5.6，KivyMD 重写）。

需求 4：数据源自动选择（新浪 → 腾讯），界面不显示切换按钮，
        仅以小字备注实际命中的数据源。
"""
import threading
from datetime import date, datetime

from kivy.clock import Clock
from kivy.graphics import Color as KColor, Rectangle
from kivy.metrics import dp
from kivy.utils import get_color_from_hex
from kivy.uix.label import Label
from kivy.uix.boxlayout import BoxLayout

from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDIconButton, MDRaisedButton
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel
from kivymd.uix.textfield import MDTextField
try:
    from kivymd.uix.pickers.datepicker import MDDatePicker
except ImportError:
    from kivymd.uix.picker import MDDatePicker

from . import api, config, pivot
from .clipboard import copy_text

# 验证标色（深色主题下的可读色）
_RED = get_color_from_hex("#ef5350")
_GREEN = get_color_from_hex("#66bb6a")
_BLUE = get_color_from_hex("#64b5f6")
_ORANGE = get_color_from_hex("#ffa726")
_YELLOW = get_color_from_hex("#ffd54f")
_GREY = (0.72, 0.74, 0.78, 1.0)
# 需求：最优/次优背景区分度加强——最优红底更亮、次优橙底更暗更偏棕
_BG_BEST = (0.55, 0.10, 0.10, 0.95)      # 红底（最优误差≤0.5%）
_BG_2ND = (0.42, 0.22, 0.02, 0.92)       # 橙底（次优误差≤1%）
_BG_GREEN = (0.08, 0.28, 0.14, 0.9)      # 绿底
_BG_YELLOW = (0.30, 0.26, 0.06, 0.9)     # 黄底
_BG_NONE = (0.0, 0.0, 0.0, 0.0)

MODE_DAILY = "daily"
MODE_WEEKLY = "weekly"

_VERIFY_LABEL = {
    "next_day": "下一交易日",
    "next_week": "下一周",
    "latest": "历史最新",
    "same_day": "腾讯当天",
    "unsupported": "—",
}


class _Cell(Label):
    """带背景色的单元格（纯 Kivy 绘制，规避 KivyMD 阴影着色器）。

    需求：批量表格长数值（如 2083.45）曾溢出覆盖相邻单元格。
    修复：按文本长度与单元格宽度自适应字号，并用 text_size 裁剪防溢出。
    """

    def __init__(self, text="", color=(1, 1, 1, 1), bg=_BG_NONE,
                 bold=False, size_hint_x=1, on_copy=None, wrap=False, **kw):
        # 自适应字号：优先按单元格宽度估算，未知宽度时按文本长度分级
        # （含换行文本按最长行计，避免 \n 计入长度导致字号过小）
        n = len(text)
        if "\n" in text:
            n = max(len(ln) for ln in text.split("\n"))
        w_dp = kw.get("width")
        if w_dp:
            w_dp = w_dp / dp(1)
            fs = min(11, max(7, int(w_dp / max(n * 0.62, 1))))
        elif n >= 9:
            fs = 9
        elif n >= 7:
            fs = 10
        else:
            fs = 11
        super().__init__(
            text=text, color=color, bold=bold,
            font_size=dp(fs), halign="center", valign="middle",
            size_hint=(size_hint_x, None), height=dp(28), **kw,
        )
        self.bg_color = bg
        self._bg = None
        self._wrap = wrap
        self.bind(size=self._apply_bg, pos=self._apply_bg)
        # text_size 跟随尺寸：防止长文本溢出到相邻单元格；wrap 时允许换行（不限高）
        self.bind(size=self._clip_text)
        self._clip_text()
        self._apply_bg()
        self._on_copy = on_copy

    def _clip_text(self, *a):
        try:
            if self._wrap:
                self.text_size = (self.width, None)
            else:
                self.text_size = (self.width, self.height)
        except Exception:  # noqa: BLE001
            pass

    def _apply_bg(self, *a):
        if self.canvas.before:
            self.canvas.before.clear()
        with self.canvas.before:
            KColor(*self.bg_color)
            self._bg = Rectangle(pos=self.pos, size=self.size)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos) and self._on_copy:
            self._on_copy(self.text)
            return True
        return super().on_touch_down(touch)


class PivotPage:
    """枢轴点功能页（五种算法，按日/按周，自动数据源）。"""

    def __init__(self, app):
        self.app = app
        self.mode = MODE_DAILY
        self.target_date = date.today()
        self._busy = False
        self._synced_code = None   # 已同步过的默认代码（需求 5）

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------
    def build(self, box):
        # 输入行：代码 + 计算按钮（同行内容垂直居中）
        row = MDBoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(58), spacing=dp(8),
        )
        self.code_field = MDTextField(
            hint_text="股票代码 如 159516 / 600519",
            size_hint=(1, None), height=dp(56), pos_hint={"center_y": 0.5},
        )
        row.add_widget(self.code_field)
        self.calc_btn = MDRaisedButton(
            text="计算", size_hint=(None, None), width=dp(80), height=dp(48),
            pos_hint={"center_y": 0.5},
        )
        self.calc_btn.elevation = 0
        self.calc_btn.bind(on_release=lambda x: self.on_calc())
        row.add_widget(self.calc_btn)
        box.add_widget(row)

        # 模式 + 日期行（日期与日历图标紧挨着；同行动态垂直居中）
        mode_row = MDBoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(44), spacing=dp(8),
        )
        self.mode_daily = MDRaisedButton(
            text="按日", size_hint=(None, None), width=dp(64), height=dp(36),
            pos_hint={"center_y": 0.5},
        )
        self.mode_weekly = MDRaisedButton(
            text="按周", size_hint=(None, None), width=dp(64), height=dp(36),
            pos_hint={"center_y": 0.5},
        )
        self.mode_daily.elevation = 0
        self.mode_weekly.elevation = 0
        self.mode_daily.bind(on_release=lambda x: self._set_mode(MODE_DAILY))
        self.mode_weekly.bind(on_release=lambda x: self._set_mode(MODE_WEEKLY))
        mode_row.add_widget(self.mode_daily)
        mode_row.add_widget(self.mode_weekly)

        # 弹性占位把日期组推到右侧
        mode_row.add_widget(MDLabel(size_hint_x=1))

        # 日期数字与日历图标紧挨（需求：控件靠拢），整组垂直居中
        date_group = MDBoxLayout(
            orientation="horizontal", size_hint=(None, None),
            size=(dp(170), dp(36)), spacing=dp(2),
            pos_hint={"center_y": 0.5},
        )
        # 固定宽度 + text_size 绑定，保证 halign/valign 生效（否则数字偏下）
        self.date_label = MDLabel(
            text=self.target_date.strftime("%Y-%m-%d"),
            size_hint=(None, None), size=(dp(126), dp(36)),
            text_size=(dp(126), dp(36)),
            halign="right", valign="middle",
            pos_hint={"center_y": 0.5},
        )
        date_btn = MDIconButton(
            icon="calendar", theme_icon_color="Custom",
            icon_color=get_color_from_hex("#8ab4f8"),
            size_hint=(None, None), size=(dp(36), dp(36)),
            pos_hint={"center_y": 0.5},
        )
        date_btn.bind(on_release=lambda x: self._open_date_picker())
        date_group.add_widget(self.date_label)
        date_group.add_widget(date_btn)
        mode_row.add_widget(date_group)
        box.add_widget(mode_row)
        self._set_mode(self.mode)

        # 名称
        self.name_label = MDLabel(
            text="名称：—", font_style="Subtitle1",
            adaptive_height=True, theme_text_color="Custom",
            text_color=_GREY,
        )
        box.add_widget(self.name_label)

        # 计算/验证信息卡
        info_card = MDCard(
            orientation="vertical", padding=[dp(12), dp(8), dp(12), dp(8)],
            radius=[dp(10), dp(10), dp(10), dp(10)], elevation=0, size_hint_y=None,
        )
        info_card.bind(minimum_height=info_card.setter("height"))
        self.calc_info = MDLabel(
            text="计算日：—", font_style="Caption",
            theme_text_color="Secondary", adaptive_height=True,
        )
        self.verify_info = MDLabel(
            text="验证：—", font_style="Caption",
            theme_text_color="Secondary", adaptive_height=True,
        )
        info_card.add_widget(self.calc_info)
        info_card.add_widget(self.verify_info)

        vrow = MDBoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(30), spacing=dp(8),
        )
        # 需求：字体不宜过大，数字大时保持单行（恒生/茅台等大数值不换行，
        # 避免覆盖上方"验证："文字）。固定行高 + 单元格填满 + 单次 text_size 限宽，
        # 不做动态字号绑定（Adreno 上回调链易触发切换崩溃）。
        self.v_high = MDLabel(text="最高 —", size_hint_x=1, size_hint_y=1,
                              theme_text_color="Custom", text_color=_RED,
                              halign="left", valign="middle", font_size=dp(11))
        self.v_low = MDLabel(text="最低 —", size_hint_x=1, size_hint_y=1,
                             theme_text_color="Custom", text_color=_GREEN,
                             halign="left", valign="middle", font_size=dp(11))
        self.v_close = MDLabel(text="收盘 —", size_hint_x=1, size_hint_y=1,
                               theme_text_color="Custom", text_color=(1, 1, 1, 1),
                               halign="left", valign="middle", font_size=dp(11))
        # 单行限宽：text_size 双向固定 → 超长自动截断不换行（同 _Cell 稳定模式）
        for _lb in (self.v_high, self.v_low, self.v_close):
            _lb.bind(size=lambda o, *a: setattr(o, "text_size", (o.width, o.height)))
        vrow.add_widget(self.v_high)
        vrow.add_widget(self.v_low)
        vrow.add_widget(self.v_close)
        info_card.add_widget(vrow)
        box.add_widget(info_card)

        # 数据源备注（小字，不提供切换）
        self.source_note = MDLabel(
            text="", font_style="Caption", theme_text_color="Hint",
            adaptive_height=True,
        )
        box.add_widget(self.source_note)

        # 结果区
        self.results_box = MDBoxLayout(
            orientation="vertical", spacing=dp(2), adaptive_height=True,
        )
        box.add_widget(self.results_box)

        box.add_widget(MDLabel(
            text="五种算法：经典 / 斐波那契 / 卡玛利亚 / 伍迪 / 迪马克\n"
                 "红/绿底色=验证误差≤0.5%（最优），橙/黄=≤1%（次优）\n"
                 "统一数据源：腾讯财经（默认）→ 新浪财经（备用）\n"
                 "点击单元格复制 · 指标仅供技术分析参考，不构成投资建议",
            font_style="Caption", theme_text_color="Hint",
            adaptive_height=True, halign="center",
        ))

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------
    def _set_mode(self, mode):
        self.mode = mode
        self.mode_daily.md_bg_color = get_color_from_hex("#1565c0") if mode == MODE_DAILY else get_color_from_hex("#263238")
        self.mode_weekly.md_bg_color = get_color_from_hex("#1565c0") if mode == MODE_WEEKLY else get_color_from_hex("#263238")
        self.mode_daily.text_color = (1, 1, 1, 1)
        self.mode_weekly.text_color = (1, 1, 1, 1)

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
        # 需求 6：不显示"指定日期"文字，日期体现在计算日里；
        # 同步刷新日期数字显示（否则选完日期数字不更新）
        try:
            self.date_label.text = value.strftime("%Y-%m-%d")
        except Exception:  # noqa: BLE001
            pass

    def sync_default_code(self, code):
        """需求 5：切到枢轴点时，默认输入 = 牛门线最新查询的代码。

        仅当代码发生变化时更新，避免覆盖用户手动输入的内容。
        """
        try:
            if code and code != self._synced_code:
                self.code_field.text = code
                self._synced_code = code
        except Exception:  # noqa: BLE001
            pass

    def on_calc(self):
        if self._busy:
            return
        raw = (self.code_field.text or "").strip()
        if not raw:
            self.app._toast("请输入股票代码")
            return
        try:
            # 需求 7：统一规范化（159516→sz159516，带前缀也识别），显示一致
            code = api.normalize_code(raw)
        except ValueError as e:
            self.app._toast(str(e))
            return
        self.code_field.text = code
        self.app.last_code = code   # 回写给牛门线共享（需求 4）
        self._synced_code = code
        self._busy = True
        self.calc_btn.disabled = True
        self.results_box.clear_widgets()
        self.results_box.add_widget(MDLabel(
            text="计算中…", adaptive_height=True,
            theme_text_color="Secondary",
        ))
        self.source_note.text = ""
        weekly = self.mode == MODE_WEEKLY

        def work():
            try:
                res = api.fetch_pivot_quote(code, self.target_date, weekly=weekly)
            except Exception as e:  # noqa: BLE001（兜底：任何异常都转成可展示的失败结果）
                res = {"ok": False, "msg": "计算失败：%s" % e}
            Clock.schedule_once(lambda dt: self._on_result(code, res), 0)

        threading.Thread(target=work, daemon=True).start()

    def _fit_price_fonts(self):
        """按数值长度自动缩小字号（恒生/茅台等大数值保持单行，需求）。

        只在此处一次性设置 font_size（不做持续绑定，避免 Adreno 回调链崩溃）；
        text_size 双向限宽保证不换行。
        """
        for lb in (self.v_high, self.v_low, self.v_close):
            try:
                n = len(lb.text)
                # 每字符估算：中文/全角≈1.0em，数字/半角≈0.55em；em=字号
                est = 0.0
                for ch in lb.text:
                    est += 1.0 if ord(ch) > 0x2E7F else 0.55
                if est <= 0:
                    continue
                w = lb.width
                if w <= 0:
                    w = dp(110)   # 未布局时按每列约 110dp 估算
                fs = max(7, min(11, int(w / (est * dp(1)) * 0.94)))
                lb.font_size = dp(fs)
            except Exception:  # noqa: BLE001
                pass

    def _on_result(self, raw, res):
        self._busy = False
        self.calc_btn.disabled = False
        self.results_box.clear_widgets()
        if not res.get("ok"):
            self.results_box.add_widget(MDLabel(
                text="❌ %s" % res.get("msg", "获取失败"),
                adaptive_height=True, theme_text_color="Custom",
                text_color=_RED,
            ))
            self.name_label.text = "名称：获取失败"
            self.calc_info.text = "计算日：—"
            self.verify_info.text = "验证：—"
            self.v_high.text = "最高 —"
            self.v_low.text = "最低 —"
            self.v_close.text = "收盘 —"
            self._fit_price_fonts()
            self.source_note.text = ""
            return

        name = res["name"]
        self.name_label.text = "名称：%s（%s）" % (name, res["source"])
        # 本地记录成功查询（供批量页「近期查询」使用，重启保留）
        try:
            self.app.watchlist.touch(code, name)
        except Exception:  # noqa: BLE001
            pass
        note = res.get("note", "")
        self.calc_info.text = "计算日：%s  ·  开盘 %.3f（迪马克用）%s" % (
            res["calc_date"], res["open"], ("  " + note) if note else "")
        self.verify_info.text = "验证：%s（%s）" % (
            res["verify_date"], _VERIFY_LABEL.get(res["verify_mode"], res["verify_mode"]))
        self.v_high.text = "最高 %.3f" % res["verify_high"]
        self.v_low.text = "最低 %.3f" % res["verify_low"]
        self.v_close.text = "收盘 %.3f" % res["verify_close"]
        self._fit_price_fonts()
        # 需求 4：仅小字备注实际命中的数据源，不显示切换
        self.source_note.text = "数据源：%s（自动）" % res["source"]

        blocks = pivot.compute_pivot_blocks(res["high"], res["low"], res["close"], res["open"])
        if res["verify_mode"] in ("latest", "same_day", "unsupported"):
            best_r, best_s = {"red": set(), "orange": set()}, {"green": set(), "yellow": set()}
        else:
            best_r, best_s = pivot.mark_verify_levels(
                blocks, res["verify_high"], res["verify_low"])
        self._build_table(blocks, best_r, best_s)

    def _build_table(self, blocks, best_r, best_s):
        block_map = {b["title"]: b for b in blocks}

        def copy_cb(text):
            if copy_text(text):
                self.app._toast("已复制：%s" % text)
            else:
                self.app._toast("复制失败")

        header = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(30))
        header.add_widget(_Cell("档位", color=_GREY, bold=True, on_copy=None))
        for show, _key in pivot.ALGO_SHOW_KEYS:
            header.add_widget(_Cell(show, color=_GREY, bold=True, on_copy=None))
        self.results_box.add_widget(header)

        for lvl in pivot.LEVELS:
            row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(28))
            lcol = _RED if lvl.startswith("R") else _GREEN if lvl.startswith("S") else _BLUE
            row.add_widget(_Cell(lvl, color=lcol, bold=True, on_copy=copy_cb))
            for _show, key in pivot.ALGO_SHOW_KEYS:
                data = block_map.get(key)
                val = "-"
                bg = _BG_NONE
                if data:
                    if lvl == "PP":
                        val = data["pp"]
                    elif lvl.startswith("R"):
                        val = data["r"].get(lvl, "-")
                        if (key, lvl) in best_r["red"]:
                            bg = _BG_BEST
                        elif (key, lvl) in best_r["orange"]:
                            bg = _BG_2ND
                    else:
                        val = data["s"].get(lvl, "-")
                        if (key, lvl) in best_s["green"]:
                            bg = _BG_GREEN
                        elif (key, lvl) in best_s["yellow"]:
                            bg = _BG_YELLOW
                color = (1, 1, 1, 1) if lvl == "PP" else (_RED if lvl.startswith("R") else _GREEN)
                row.add_widget(_Cell(str(val), color=color, bg=bg, on_copy=copy_cb))
            self.results_box.add_widget(row)
