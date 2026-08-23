# -*- coding: utf-8 -*-
"""图表几何纯函数（不依赖 Kivy，便于单元测试）。"""


def map_y(price, lo, hi, pad_t, plot_h):
    """价格 → 画布 y 坐标（Kivy 原点在左下、y 向上）。

    价格越高 y 越大（绘制在越上方）：map_y(hi) == pad_t + plot_h（顶部），
    map_y(lo) == pad_t（底部）。保证线位相对位置正确：
    例如 QRL=0.9 / NML=0.8 / 60日成本=0.7 时，0.9 在最上方、0.7 在最下方。
    """
    return pad_t + (price - lo) / (hi - lo) * plot_h
