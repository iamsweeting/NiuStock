# -*- coding: utf-8 -*-
"""批量枢轴点辅助（纯函数，移植自 BatchStock/main.py）。

批量计算主流程（逐代码抓取 + 状态更新）属于界面层，这里只保留可测试的纯逻辑：
  - 名称截断与字号自适应
  - 结果行转文本（复制用）
  - 结果统计
"""
import re

from .pivot import parse_batch_codes  # noqa: F401  （批量代码解析入口，统一导出）

_LATIN_WORD = re.compile(r"[A-Za-z0-9]+")


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


def _name_units(name):
    """把名称拆成显示单位：单个汉字=1 单位，连续 Latin/数字词（如 ETF）=1 单位。

    需求：名称列硬截断会把「ETF」拆成 E/TF 两行（用户实测
    「恒生互联网ETF华夏」「半导体设备ETF」），改为按词边界断行。
    """
    units = []
    i = 0
    for m in _LATIN_WORD.finditer(name):
        if m.start() > i:
            units.extend(list(name[i:m.start()]))   # 汉字逐字
        units.append(m.group())                      # 连续字母/数字作为整体
        i = m.end()
    if i < len(name):
        units.extend(list(name[i:]))
    return units


def _display_width(text):
    """显示宽度（字符）：1 汉字=2 字符，1 半角字母/数字=1 字符（ETF=3 字符）。"""
    return sum(2.0 if ord(c) > 0x2E80 else 1.0 for c in text)


def _word_blocks(units):
    """把单位序列合并成词块：连续汉字=1 块，Latin 词=1 块。

    断行优先在块边界（词完整），块内才按宽度切（避免「精选」被拆成「精/选」）。
    """
    blocks = []
    cur = []
    for u in units:
        is_latin = bool(_LATIN_WORD.fullmatch(u))
        if cur and (is_latin != bool(_LATIN_WORD.fullmatch(cur[-1]))):
            blocks.append("".join(cur))
            cur = []
        cur.append(u)
    if cur:
        blocks.append("".join(cur))
    return blocks


def name_display(name, chars_per_line=8, max_lines=2):
    """返回 (显示文本, 所需行数)。规则（需求，字符宽度）：
      - 汉字=1 字符，半角字母/数字=0.5 字符（ETF 三字母=1.5 字符）
      - 单行 ≤ chars_per_line 字符；两行合计 ≤ chars_per_line * max_lines
      - 超出截断不显示；断行优先在词边界（汉字串/Latin 词不拆开）
    批量页：chars_per_line=8（每行≤8 字符、两行≤16 字符）；趋势页：max_lines=1。
    """
    name = str(name)
    units = _name_units(name)
    if _display_width(name) <= chars_per_line:
        return name, 1
    lines, cur, cur_w = [], [], 0.0
    for block in _word_blocks(units):
        bw = _display_width(block)
        # 块本身超一行宽：先在块内按宽度切分（仅长汉字串才会）
        if bw > chars_per_line:
            if cur:
                lines.append("".join(cur))
                cur, cur_w = [], 0.0
            seg = ""
            sw = 0.0
            for ch in block:
                cw = 2.0 if ord(ch) > 0x2E80 else 1.0
                if seg and sw + cw > chars_per_line:
                    lines.append(seg)
                    seg, sw = "", 0.0
                seg += ch
                sw += cw
            if seg:
                cur, cur_w = [seg], sw
            continue
        if cur and cur_w + bw > chars_per_line:
            lines.append("".join(cur))
            cur, cur_w = [], 0.0
        cur.append(block)
        cur_w += bw
    if cur:
        lines.append("".join(cur))
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    return "\n".join(lines), len(lines)


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
