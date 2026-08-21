# -*- coding: utf-8 -*-
"""跨平台剪贴板复制（牛票 Nstock）。

Android：优先 jnius ClipboardManager（不依赖 Kivy 提供者），失败回退
        kivy.core.clipboard.Clipboard；
桌面开发：tkinter / Win32（仅调试用）。
"""
import sys


def _android_jnius(text):
    try:
        from android import mActivity
        from jnius import autoclass
        ClipboardManager = autoclass("android.content.ClipboardManager")
        ClipData = autoclass("android.content.ClipData")
        cm = mActivity.getSystemService("clipboard")
        if cm is not None:
            cm.setPrimaryClip(ClipData.newPlainText("nstock", text))
            return True
    except Exception:
        pass
    try:
        from kivy.core.clipboard import Clipboard
        Clipboard.copy(text)
        return True
    except Exception:
        pass
    return False


def _tkinter_copy(text):
    try:
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
        r.clipboard_clear()
        r.clipboard_append(text)
        r.update()
        r.destroy()
        return True
    except Exception:
        return False


def copy_text(text):
    """复制文本到剪贴板，返回是否成功。"""
    try:
        if sys.platform == "win32":
            if _tkinter_copy(text):
                return True
            return _android_jnius(text)  # Windows 上 jnius 不存在，自动失败
        return _android_jnius(text) or _tkinter_copy(text)
    except Exception:
        return False
