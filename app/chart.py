# -*- coding: utf-8 -*-
"""牛票图表组件：Canvas 绘制的 10 日 K 线 + 指标线（窗口长度由 config.DISPLAY_POINTS 决定）。

注意：Adreno 825 真机上，纯 Widget 的 canvas 指令自动变换矩阵失效
（指令画在窗口原点），因此所有绘制指令手动包一层
PushMatrix + Translate(self.pos)，强制应用 widget 位置后再画。
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


class NMLChart(Widget):
    """K线（红涨绿跌）+ NML/QRL/SMX(+CBX20/CBX60) 指标线。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (1.0, None)
        self.height = dp(300)
        self._bars = []       # 待绘制的K线（DISPLAY_POINTS 根）
        self._lines = []      # [(标签, 颜色, [DISPLAY_POINTS 个数值])]
        self._last_idx = 0    # 选中日（窗口内下标）
        self.bind(pos=self._redraw, size=self._redraw)

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
        pad_l, pad_r, pad_t, pad_b = dp(10), dp(10), dp(18), dp(10)
        plot_w = w - pad_l - pad_r
        plot_h = h - pad_t - pad_b
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
            return pad_t + (hi - p) / (hi - lo) * plot_h

        n = len(self._bars)
        step = plot_w / n
        # 10 根蜡烛时收窄单根宽度上限，避免过宽
        cw = min(step * 0.55, dp(20))

        with self.canvas:
            # Adreno 真机 canvas 自动变换失效，手动应用 widget 位置
            PushMatrix()
            Translate(self.pos[0], self.pos[1])

            # 网格
            Color(1, 1, 1, 0.06)
            for i in range(1, 6):
                p = lo + (hi - lo) * i / 6.0
                Line(points=[pad_l, Y(p), w - pad_r, Y(p)], width=1)

            # K线蜡烛
            for i, b in enumerate(self._bars):
                x = pad_l + step * i + step / 2.0
                up = b["close"] >= b["open"]
                col = config.COLOR_UP if up else config.COLOR_DOWN
                Color(*col)
                Line(points=[x, Y(b["high"]), x, Y(b["low"])], width=dp(1.2))
                y1 = Y(max(b["open"], b["close"]))
                y2 = Y(min(b["open"], b["close"]))
                bh = max(y2 - y1, dp(1))
                Rectangle(pos=(x - cw / 2.0, y1), size=(cw, bh))

            # 指标线
            for _, col, lv in self._lines:
                pts = []
                for i, v in enumerate(lv):
                    if v is None:
                        continue
                    pts += [pad_l + step * i + step / 2.0, Y(v)]
                if len(pts) >= 4:
                    Color(*col)
                    Line(points=pts, width=dp(1.6))

            PopMatrix()


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
