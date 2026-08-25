# -*- coding: utf-8 -*-
"""牛票图表组件：主图（K线+指标线+纵坐标）+ 成交额副图（独立控件，位于主图下方）。

坐标方向：价格越高绘制位置越靠上。
注意：Adreno 825 真机上 canvas 自动变换失效（内容画到窗口原点），所有 canvas
绘制用 PushMatrix+Translate(self.pos) 手动补偿；折线 Line 在该设备不可靠
（width>1 涂抹、width=1 不渲染），一律用 Rectangle 绘制。
纵坐标与副图用"独立控件+布局定位"，不依赖 canvas 坐标缩放。
"""
from kivy.graphics import (
    Color, Line, Rectangle,
    PushMatrix, PopMatrix, Translate,
)
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.widget import Widget

from . import config
from .geometry import map_y

_AXIS_COLOR = (0.78, 0.80, 0.86, 1.0)   # 纵坐标颜色（亮一些，保证可见）


class NMLChart(Widget):
    """主图：K线蜡烛 + 五条指标线 + 网格。纵坐标标签为 canvas 纹理。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (1.0, None)
        self.height = dp(220)
        self._bars = []
        self._lines = []
        self._last_idx = 0
        self.pad_l = dp(8) + dp(56)   # 默认；_redraw 时按标签实际宽度收紧
        self.bind(pos=self._redraw, size=self._redraw)
        # 纵坐标标签：用 Label 纹理绘制在 canvas 上（与蜡烛同一变换，
        # Adreno 上子控件定位不可靠，改为纹理绘制保证对齐与可见）
        self._axis_labels = []
        for _ in range(4):
            lb = Label(
                text="", font_size=dp(11), color=_AXIS_COLOR,
                size_hint=(None, None), size=(dp(56), dp(16)),
                halign="right", valign="middle",
            )
            lb.bind(size=lambda o, *a: setattr(o, "text_size", (o.width, o.height)))
            self._axis_labels.append(lb)

    def set_data(self, bars, lines, last_idx):
        self._bars = list(bars)
        self._lines = list(lines)
        self._last_idx = last_idx
        self._redraw()

    def _render_axis_labels(self, lo, hi):
        """生成 4 档纵坐标标签纹理，返回最大纹理宽度（用于收紧左侧预留）。"""
        maxw = 0
        for idx, frac in enumerate((0.0, 1 / 3, 2 / 3, 1.0)):
            p = lo + (hi - lo) * frac
            lb = self._axis_labels[idx]
            lb.text = "%.2f" % p
            lb.texture_update()
            tex = lb.texture
            if tex is not None:
                maxw = max(maxw, tex.width)
        return maxw

    def _redraw(self, *args):
        self.canvas.clear()
        if not self._bars or self.width < 10 or self.height < 10:
            return
        w, h = self.width, self.height

        vals = []
        for b in self._bars:
            vals.append(b["high"])
            vals.append(b["low"])
        for _, _, lv in self._lines:
            for v in lv:
                if v is not None:
                    vals.append(v)
        lo, hi = min(vals), max(vals)
        if hi - lo < 1e-9:
            hi = lo + 1.0
        pad = (hi - lo) * 0.08
        lo -= pad
        hi += pad

        # 先渲染标签并测量宽度：左侧预留只留标签实际宽度 + 少量边距（需求：不要大片空白）
        maxw = self._render_axis_labels(lo, hi)
        self.pad_l = dp(6) + maxw + dp(6)
        if self.pad_l < dp(34):
            self.pad_l = dp(34)

        pad_r, pad_t, pad_b = dp(8), dp(6), dp(4)
        plot_w = w - self.pad_l - pad_r
        plot_h = h - pad_t - pad_b
        if plot_w <= 0 or plot_h <= 0:
            return

        def Y(p):
            return map_y(p, lo, hi, pad_t, plot_h)

        n = len(self._bars)
        step = plot_w / n
        cw = min(step * 0.55, dp(20))

        with self.canvas:
            PushMatrix()
            Translate(self.pos[0], self.pos[1])
            # 网格
            for i in range(1, 6):
                p = lo + (hi - lo) * i / 6.0
                Color(1, 1, 1, 0.06)
                Line(points=[self.pad_l, Y(p), w - pad_r, Y(p)], width=1)
            # 纵坐标刻度（Rectangle 在 Adreno 上可靠；Line 会涂抹/不渲染）
            for i in range(6):
                p = lo + (hi - lo) * i / 6.0
                y = Y(p)
                Color(*_AXIS_COLOR)
                Rectangle(pos=(self.pad_l - dp(7), y - 1), size=(dp(7), 2))
            # 蜡烛（Kivy y 向上：高价在上、低价在下）
            for i, b in enumerate(self._bars):
                x = self.pad_l + step * i + step / 2.0
                up = b["close"] >= b["open"]
                col = config.COLOR_UP if up else config.COLOR_DOWN
                Color(*col)
                Line(points=[x, Y(b["high"]), x, Y(b["low"])], width=1)
                y_top = Y(max(b["open"], b["close"]))
                y_bot = Y(min(b["open"], b["close"]))
                Rectangle(pos=(x - cw / 2.0, y_bot), size=(cw, max(y_top - y_bot, 1)))
            # 指标线：沿线细分小矩形（Line 在 Adreno 不渲染；整段大矩形会成块状）
            for _, col, lv in self._lines:
                pts = []
                for i, v in enumerate(lv):
                    if v is None:
                        continue
                    pts.append((self.pad_l + step * i + step / 2.0, Y(v)))
                if len(pts) < 2:
                    continue
                Color(*col)
                for i in range(len(pts) - 1):
                    x1, y1 = pts[i]
                    x2, y2 = pts[i + 1]
                    # 沿线细分 2px 小矩形，构成连续细线（整段大矩形会成块状）
                    dx, dy = x2 - x1, y2 - y1
                    dist = max(abs(dx), abs(dy))
                    steps = max(int(dist / 2.0), 1)
                    for s in range(steps + 1):
                        t = s / steps
                        xx = x1 + dx * t
                        yy = y1 + dy * t
                        Rectangle(pos=(xx - 1, yy - 1), size=(2, 2))
            PopMatrix()

        # 纵坐标标签（4 档）：以 Label 纹理绘制在 canvas 内，
        # 与蜡烛共用 PushMatrix+Translate 变换，保证对齐且可见。
        for idx, frac in enumerate((0.0, 1 / 3, 2 / 3, 1.0)):
            p = lo + (hi - lo) * frac
            lb = self._axis_labels[idx]
            tex = lb.texture
            if tex is None:
                continue
            with self.canvas:
                PushMatrix()
                Translate(self.pos[0], self.pos[1])
                Color(*_AXIS_COLOR)
                Rectangle(texture=tex,
                          pos=(self.pad_l - tex.width - dp(4), Y(p) - tex.height / 2.0),
                          size=tex.size)
                PopMatrix()


class VolumePanel(Widget):
    """成交额副图：位于主图下方（由外层布局保证），10 根红绿柱。

    pad_l 由外层从主图（NMLChart.pad_l）同步，保证柱与蜡烛对齐。
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (1.0, None)
        self.height = dp(56)
        self.pad_l = dp(8) + dp(56)
        self._bars = []
        self._label = Label(
            text="成交额(万元)", font_size=dp(8), color=_AXIS_COLOR,
            size_hint=(None, None), size=(dp(84), dp(12)),
            halign="left", valign="middle",
        )
        self.add_widget(self._label)
        self.bind(pos=self._redraw, size=self._redraw)

    def set_data(self, bars):
        self._bars = list(bars)
        self._redraw()

    def set_pad_l(self, pad_l):
        """与主图纵坐标宽度同步，使柱与蜡烛 x 对齐。"""
        self.pad_l = pad_l
        self._redraw()

    def _redraw(self, *args):
        self.canvas.clear()
        # 子控件 pos 相对父级，不能再叠加 self.x/self.y（双重偏移）
        self._label.pos = (dp(2), self.height - dp(12))
        if not self._bars or self.width < 10 or self.height < 10:
            return
        w, h = self.width, self.height
        pad_l = self.pad_l
        pad_r, pad_t, pad_b = dp(8), dp(14), dp(2)
        plot_w = w - pad_l - pad_r
        plot_h = h - pad_t - pad_b
        if plot_w <= 0 or plot_h <= 0:
            return
        n = len(self._bars)
        step = plot_w / n
        cw = min(step * 0.55, dp(20))
        amts = []
        for b in self._bars:
            a = b.get("amount")
            if not a or a <= 0:
                a = b["close"] * b["volume"]
            amts.append(a / 1e4)
        amax = max(amts) if amts else 1.0
        with self.canvas:
            PushMatrix()
            Translate(self.pos[0], self.pos[1])
            Color(1, 1, 1, 0.05)
            Line(points=[pad_l, pad_t, w - pad_r, pad_t], width=1)
            for i, b in enumerate(self._bars):
                x = pad_l + step * i + step / 2.0
                up = b["close"] >= b["open"]
                col = config.COLOR_UP if up else config.COLOR_DOWN
                bh = max(plot_h * amts[i] / amax, 1)
                Color(*col)
                Rectangle(pos=(x - cw / 2.0, pad_t), size=(cw, bh))
            PopMatrix()


class DateAxis(BoxLayout):
    """DISPLAY_POINTS 个交易日的日期标签（MM-DD）。

    左内边距与主图/成交额柱的 pad_l 一致（由外层从 NMLChart.pad_l 同步），
    使日期标签对齐在成交额柱正下方（需求：日期放到成交额柱下面，不偏左）。
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint_y = None
        self.height = dp(18)
        self.pad_l = dp(8) + dp(56)
        self.padding = [self.pad_l, 0, dp(8), 0]   # [左, 上, 右, 下]
        self._labels = []
        for _ in range(config.DISPLAY_POINTS):
            lb = Label(
                text="", font_size=dp(9),
                color=(0.68, 0.70, 0.76, 1), halign="center",
            )
            lb.bind(size=lambda obj, *a: setattr(obj, "text_size", (obj.width, None)))
            self.add_widget(lb)
            self._labels.append(lb)

    def set_pad_l(self, pad_l):
        """与主图纵坐标宽度同步，使日期与成交额柱对齐。"""
        self.pad_l = pad_l
        self.padding = [self.pad_l, 0, dp(8), 0]

    def set_dates(self, dates):
        """日期标签：第一个带月（07-27），中间只显示日（28 29 30 31），
        跨月那天带月（08-03），随后只显示日（04 05 06 07）。"""
        prev_month = None
        for i, lb in enumerate(self._labels):
            if i >= len(dates):
                lb.text = ""
                continue
            d = dates[i]
            mm, dd = d[5:7], d[8:10]
            if i == 0 or mm != prev_month:
                lb.text = "%s-%s" % (mm, dd)
            else:
                lb.text = dd
            prev_month = mm
