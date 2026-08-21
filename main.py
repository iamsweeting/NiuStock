# -*- coding: utf-8 -*-
"""牛票（Nstock）—— 程序入口。

Android 上由 python-for-android 运行本文件；桌面预览直接 `python main.py`。
"""
import os
import sys
import threading
import traceback

# 确保项目根目录可被导入（桌面运行与 Android 均适用）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.diag import make_status_label, status  # noqa: E402

status("进程启动（python 入口）")

from app.ui import NiumenApp  # noqa: E402

status("app.ui 导入完成")


def _crash_log_path():
    """崩溃日志落盘位置：Android 为应用私有存储（debug 包可用 run-as 读取）。"""
    try:
        from kivy.app import App
        app = App.get_running_app()
        if app is not None:
            return os.path.join(app.user_data_dir, "crash.log")
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "crash.log")


def _dump_crash(tp, val, tb):
    """记录未捕获异常：写入 crash.log、打印到 stderr（Android 上进入 logcat），
    并尝试在界面浮层显示（便于无 adb 时直接截图反馈）。"""
    msg = "".join(traceback.format_exception(tp, val, tb))
    try:
        with open(_crash_log_path(), "w", encoding="utf-8") as f:
            f.write(msg)
    except Exception:
        pass
    print("[牛票崩溃]\n%s" % msg, file=sys.stderr)
    try:
        from kivy.app import App
        from kivy.clock import Clock
        app = App.get_running_app()
        if app is not None and hasattr(app, "_show_crash"):
            Clock.schedule_once(lambda dt: app._show_crash(msg), 0)
    except Exception:
        pass


def _install_crash_hooks():
    sys.excepthook = _dump_crash
    if hasattr(threading, "excepthook"):
        def _thread_hook(args):
            _dump_crash(args.exc_type, args.exc_value, args.exc_traceback)
        threading.excepthook = _thread_hook


if __name__ == "__main__":
    _install_crash_hooks()
    app = NiumenApp()
    app.status_label = make_status_label()
    status("App 实例创建完成，启动 Kivy 事件循环")
    try:
        app.run()
    except SystemExit:
        raise
    except BaseException:
        _dump_crash(*sys.exc_info())
        raise
