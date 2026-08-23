# -*- coding: utf-8 -*-
"""牛票图表组件：Canvas 绘制的 10 日 K 线 + 指标线 + 成交额副图。

坐标方向：价格越高绘制位置越靠上（Y(p) 随价格增大而减小，高值在图上方面）。
左侧为价格数值坐标（4 档），底部为近 10 日成交额（万元）副图。
注意：真机（Adreno 825）上 widget 的 canvas 自动变换是生效的，
不要再用 PushMatrix+Translate 手工补偿——实测手工补偿会二次叠加变换、
且 Line 带宽度渲染错乱，导致五条线位置失真、部分线被覆盖。
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

_AXIS_COLOR = (0.68, 0.70, 0.76, 1.0)
_PANEL_H = dp(56)          # 成交额副图高度
_AXIS_W = dp(64)           # 左侧价格轴预留宽度


class NMLChart(Widget):
    """K线（红涨绿跌）+ NML/QRL/SMX(+CBX20/CBX60) 指标线 + 成交额副图。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (1.0, None)
        self.height = dp(340)
        self._bars = []       # 待绘制的K线（DISPLAY_POINTS 根）
        self._lines = []      # [(标签, 颜色, [DISPLAY_POINTS 个数值])]
        self._last_idx = 0    # 选中日（窗口内下标）
        self.bind(pos=self._redraw, size=self._redraw)
        # 左侧价格轴标签（普通 Label 控件）
        self._axis_labels = []
        for _ in range(4):
            lb = Label(
                text="", font_size=dp(9), color=_AXIS_COLOR,
                size_hint=(None, None), size=(dp(60), dp(14)),
                halign="right", valign="middle",
            )
            self.add_widget(lb)
            self._axis_labels.append(lb)
        # 成交额副图标题
        self.panel_label = Label(
            text="成交额(万元)", font_size=dp(8), color=_AXIS_COLOR,
            size_hint=(None, None), size=(dp(80), dp(12)),
            halign="left", valign="middle",
        )
        self.add_widget(self.panel_label)

    def set_data(self, bars, lines, last_idx):
        self._bars = list(bars)
        self._lines = list(lines)
        self._last_idx = last_idx
        self._redraw()

    def _redraw(self, *args):
        self.canvas.clear()
        if not self._bars or self.width < 10 or self.height < 10:
            return
        w, h = self.width, self.height
        pad_l = dp(10) + _AXIS_W
        pad_r, pad_t, pad_b = dp(10), dp(14), dp(6)
        plot_w = w - pad_l - pad_r
        plot_h = h - pad_t - pad_b - _PANEL_H - dp(6)
        if plot_w <= 0 or plot_h <= 0:
            return

        # 价格区间
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

        def Y(p):
            return map_y(p, lo, hi, pad_t, plot_h)

        n = len(self._bars)
        step = plot_w / n
        cw = min(step * 0.55, dp(20))

        with self.canvas:
            # Adreno 真机 canvas 自动变换失效（实测去掉后内容画到窗口原点），
            # 必须手动应用 widget 位置；线条用 1px 细线（width>1 会渲染成厚涂抹）
            PushMatrix()
            Translate(self.pos[0], self.pos[1])
            # 网格 + 价格坐标
            for i in range(1, 6):
                p = lo + (hi - lo) * i / 6.0
                Color(1, 1, 1, 0.06)
                Line(points=[pad_l, Y(p), w - pad_r, Y(p)], width=1)
            # K线蜡烛
            for i, b in enumerate(self._bars):
                x = pad_l + step * i + step / 2.0
                up = b["close"] >= b["open"]
                col = config.COLOR_UP if up else config.COLOR_DOWN
                Color(*col)
                Line(points=[x, Y(b["high"]), x, Y(b["low"])], width=1)
                y1 = Y(max(b["open"], b["close"]))
                y2 = Y(min(b["open"], b["close"]))
                bh = max(y2 - y1, dp(1))
                Rectangle(pos=(x - cw / 2.0, y1), size=(cw, bh))
            # 指标线（1px 无宽度，避免 Adreno 上线宽渲染失真）
            for _, col, lv in self._lines:
                pts = []
                for i, v in enumerate(lv):
                    if v is None:
                        continue
                    pts += [pad_l + step * i + step / 2.0, Y(v)]
                if len(pts) >= 4:
                    Color(*col)
                    Line(points=pts, width=1)
            PopMatrix()

        # 左侧价格轴标签（4 档：高 / 2/3 / 1/3 / 低）
        for idx, frac in enumerate((0.0, 1 / 3, 2 / 3, 1.0)):
            p = lo + (hi - lo) * frac
            lb = self._axis_labels[idx]
            lb.text = "%.2f" % p
            lb.pos = (self.x + dp(6), self.y + Y(p) - dp(7))

        # 成交额副图
        panel_top = pad_t + plot_h + dp(6)
        panel_bot = h - pad_b
        panel_hh = panel_bot - panel_top
        amts = []
        for b in self._bars:
            a = b.get("amount")
            if not a or a <= 0:
                # 无成交额时用 收盘×成交量 估算（万元）
                a = b["close"] * b["volume"]
            amts.append(a / 1e4)   # 元 → 万元
        amax = max(amts) if amts else 1.0
        with self.canvas:
            PushMatrix()
            Translate(self.pos[0], self.pos[1])
            Color(1, 1, 1, 0.05)
            Line(points=[pad_l, panel_top, w - pad_r, panel_top], width=1)
            for i, b in enumerate(self._bars):
                x = pad_l + step * i + step / 2.0
                up = b["close"] >= b["open"]
                col = config.COLOR_UP if up else config.COLOR_DOWN
                bh = max(panel_hh * amts[i] / amax, dp(1))
                Color(*col)
                Rectangle(pos=(x - cw / 2.0, panel_top), size=(cw, bh))
            PopMatrix()
        self.panel_label.pos = (
            self.x + pad_l - dp(8),
            self.y + panel_top - dp(12),
        )


class DateAxis(BoxLayout):
    """DISPLAY_POINTS 个交易日的日期标签（MM-DD）。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint_y = None
        self.height = dp(18)
        self._labels = []
        for _ in range(config.DISPLAY_POINTS):
            lb = Label(
                text="", font_size=dp(9),
                color=(0.68, 0.70, 0.76, 1), halign="center",
            )
            lb.bind(size=lambda obj, *a: setattr(obj, "text_size", (obj.width, None)))
            self.add_widget(lb)
            self._labels.append(lb)

    def set_dates(self, dates):
        for i, lb in enumerate(self._labels):
            lb.text = dates[i][5:] if i < len(dates) else ""
