# -*- coding: utf-8 -*-
"""批量枢轴点辅助（纯函数，移植自 BatchStock/main.py）。

批量计算主流程（逐代码抓取 + 状态更新）属于界面层，这里只保留可测试的纯逻辑：
  - 名称截断与字号自适应
  - 结果行转文本（复制用）
  - 结果统计
"""
from .pivot import parse_batch_codes  # noqa: F401  （批量代码解析入口，统一导出）


def truncate_name(name, max_chars=6):
    """按显示宽度截断：优先保留完整名称（最多 2 行可放下）。

    需求：名称若 1 行能放下则直接完整显示（必要时以一个点省略）；
    超过 1 行但 2 行可放下时写全名换行；2 行仍放不下才用"…"。
    max_chars 为单行可容纳字符数（估算），此处仅用于单行省略场景。
    """
    name = str(name)
    if len(name) <= max_chars:
        return name
    return name


def name_display(name, chars_per_line=5, max_lines=2):
    """返回 (显示文本, 所需行数)。规则（需求）：
      - ≤ chars_per_line：1 行完整显示
      - ≤ chars_per_line * max_lines：写全名换行（2 行）
      - 超过：能放几个字放几个字，直接截断（不用省略号，2 行仍可读）
    """
    name = str(name)
    n = len(name)
    if n <= chars_per_line:
        return name, 1
    if n <= chars_per_line * max_lines:
        return name, 2
    return name[:chars_per_line * max_lines], 2


def get_name_font_size(name):
    """按名称长度返回字号（越大越短则越大）。"""
    ln = len(str(name))
    if ln >= 6:
        return 9
    elif ln >= 5:
        return 10
    elif ln >= 4:
        return 11
    else:
        return 12


def row_to_text(row):
    """批量结果行转制表符分隔文本（用于一键复制）。"""
    return "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s" % (
        row.get("code", ""), row.get("name", ""),
        row.get("pp", "-"), row.get("r1", "-"), row.get("s1", "-"),
        row.get("r2", "-"), row.get("s2", "-"), row.get("r3", "-"),
        row.get("s3", "-"), row.get("r4", "-"), row.get("s4", "-"),
    )


def all_rows_text(rows):
    """全部结果行合并为一份制表符文本（表头 + 数据行）。"""
    header = "代码\t名称\tPP\tR1\tS1\tR2\tS2\tR3\tS3\tR4\tS4"
    lines = [header] + [row_to_text(r) for r in rows]
    return "\n".join(lines)


def batch_summary(rows):
    """统计成功/失败条数。"""
    ok = sum(1 for r in rows if r.get("status") == "ok")
    return ok, len(rows) - ok
