# -*- coding: utf-8 -*-
"""图表坐标映射单元测试：保证「数值大画在上、数值小画在下」。

Kivy 画布原点在左下、y 向上，因此数值越大 y 越大（越靠上）。
示例：QRL=0.9、NML=0.8、60日成本=0.7 → 0.9 在最上方、0.7 在最下方。
"""
from app.geometry import map_y


def test_high_value_maps_to_top():
    lo, hi = 0.7, 0.9
    pad_t, plot_h = 18.0, 250.0
    y_qrl = map_y(0.9, lo, hi, pad_t, plot_h)   # QRL 0.9
    y_nml = map_y(0.8, lo, hi, pad_t, plot_h)   # NML 0.8
    y_cbx60 = map_y(0.7, lo, hi, pad_t, plot_h)  # 60日成本 0.7
    assert y_qrl > y_nml > y_cbx60            # 数值越大 y 越大 = 越靠上
    # 相对顺序：QRL(0.9) 在 NML(0.8) 之上，NML 在 60日成本(0.7) 之上
    assert y_qrl == pad_t + plot_h            # 最高价贴顶部
    assert y_cbx60 == pad_t                   # 最低价贴底部


def test_map_y_monotonic():
    lo, hi = 10.0, 20.0
    ys = [map_y(p, lo, hi, 5.0, 100.0) for p in (20.0, 15.0, 10.0)]
    assert ys[0] > ys[1] > ys[2]


def test_map_y_order_any_range():
    # 任意价格区间都满足单调性
    for lo, hi in ((0.1, 0.9), (5, 50), (100, 5000)):
        y1 = map_y(hi, lo, hi, 0, 100)
        y2 = map_y(lo, lo, hi, 0, 100)
        assert y1 > y2
