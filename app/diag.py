# -*- coding: utf-8 -*-
"""启动诊断工具（牛票 Nstock）：里程碑记录与品牌启动页进度。

- 里程碑记录：logcat 打印 + 落盘 startup.log（排查黑屏/闪退）。
- 品牌启动页进度：status() 每次调用都会更新已注册的进度回调（见 set_progress_cb），
  由 ui.py 的启动蒙层展示「牛票启动中…」及里程碑文字（需求 2：背景中清晰可见）。
"""
import os
import time

_START = time.time()
_status_label = None
_log_paths = []
_progress_cb = None


def set_progress_cb(cb):
    """注册启动进度回调 cb(text)；传 None 取消。"""
    global _progress_cb
    _progress_cb = cb


def _log_files():
    """候选日志文件：外部应用目录（手机文件管理器可读）+ 应用私有目录。"""
    if not _log_paths:
        try:
            from android.storage import app_external_storage_path
            d = app_external_storage_path()
            if d:
                _log_paths.append(os.path.join(d, "startup.log"))
        except Exception:
            pass
        try:
            from kivy.app import App
            app = App.get_running_app()
            if app is not None:
                _log_paths.append(os.path.join(app.user_data_dir, "startup.log"))
        except Exception:
            pass
    return _log_paths


def status(msg, show_toast=True):
    """记录一条里程碑：打印（Android 上进入 logcat）、落盘、更新屏幕标签与启动页进度。"""
    line = "[牛票][%6.1fs] %s" % (time.time() - _START, msg)
    print(line, flush=True)
    for p in _log_files():
        try:
            d = os.path.dirname(p)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass
    try:
        if _status_label is not None:
            _status_label.text = "%s\n%s" % (msg, time.strftime("%H:%M:%S"))
    except Exception:
        pass
    if _progress_cb is not None:
        try:
            _progress_cb(msg)
        except Exception:
            pass
    if show_toast:
        _toast(msg)


def _toast(text):
    """Android Toast 悬浮提示：不依赖 Kivy 渲染，黑屏时也能看到进度。"""
    try:
        from android import mActivity
        from jnius import autoclass
        Toast = autoclass("android.widget.Toast")
        Toast.makeText(mActivity, "牛票: " + text, Toast.LENGTH_LONG).show()
    except Exception:
        pass


def make_status_label():
    """创建屏幕状态标签（启动早期即可见；UI 构建完成后由应用重新置顶）。"""
    try:
        from kivy.core.window import Window
        from kivy.uix.label import Label
        from kivy.graphics import Color, Rectangle
        lb = Label(
            text="牛票启动中…",
            font_size="18sp",
            color=(1, 1, 1, 1),
            halign="center",
            valign="middle",
        )
        with lb.canvas.before:
            Color(0, 0, 0, 0.75)
            lb._bg = Rectangle(pos=lb.pos, size=lb.size)
        lb.bind(
            pos=lambda o, *a: setattr(o._bg, "pos", o.pos),
            size=lambda o, *a: setattr(o._bg, "size", o.size),
        )
        Window.add_widget(lb)
        return lb
    except Exception:
        return None
