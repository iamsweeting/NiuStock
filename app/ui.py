# -*- coding: utf-8 -*-
"""牛票（Nstock）—— Kivy/KivyMD 移动端外壳。

三大功能页（底部导航切换）：
  1. 牛门线（ui_niumen.NiumenPage）
  2. 枢轴点（ui_pivot.PivotPage）
  3. 批量枢轴点（ui_batch.BatchPage）

品牌启动页（需求 2）：全屏深色蒙层 + 图标 + 「牛票启动中…」 + 进度里程碑，
至少停留 1.8 秒且首屏数据加载完成后移除（30 秒兜底）。
"""
import os
import time

from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp, sp
from kivy.resources import resource_find
from kivy.uix.behaviors.button import ButtonBehavior
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image
from kivy.uix.screenmanager import Screen, ScreenManager
from kivy.uix.scrollview import ScrollView
from kivy.utils import get_color_from_hex

from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDIconButton
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel
from kivymd.uix.toolbar import MDTopAppBar

from . import config, diag
from .diag import status as diag_status
from .watchlist import Watchlist

# 底部导航标签定义（自定义底栏，替换 KivyMD MDBottomNavigation——
# 其 1.1.1 + Kivy 2.2.0 组合存在构造崩溃与文字重影问题）
TAB_DEFS = [
    ("niumen", "牛门线", "chart-line"),
    ("pivot", "枢轴点", "calculator"),
    ("batch", "批量枢轴", "format-list-bulleted"),
    ("market", "大盘", "finance"),
]

_IDLE_COLOR = (0.62, 0.66, 0.72, 1.0)
_ACTIVE_COLOR = get_color_from_hex("#8ab4f8")


class _TabItem(ButtonBehavior, MDBoxLayout):
    """自定义底部导航项：图标 + 文字，点击切换（无放大动画，无重影）。"""

    def __init__(self, **kw):
        super().__init__(**kw)
        self._name = ""
        self._icon = None
        self._label = None

    def on_release(self):
        try:
            App.get_running_app()._switch_to(self._name)
        except Exception:  # noqa: BLE001
            pass


def _disable_kivymd_elevation_shadows():
    """全局禁用 KivyMD 阴影/ripple 绘制（Adreno 825 驱动崩溃规避）。

    真机 tombstone 系列证实：KivyMD 1.1.1 的 elevation 阴影用
    RenderContext + 自定义 GLSL（elevation.frag）绘制，在 Adreno 825
    上首次绘制即 SIGSEGV；ripple（Ellipse + Stencil 指令）同样崩溃。
    修复方式：包装各阴影行为类的 __init__，构造后强制 elevation=0 并移除
    阴影 RenderContext；全局禁用 ripple 指令创建；禁用按钮点击时 elevation 动画。
    """
    try:
        from kivymd.uix.behaviors.elevation import CommonElevationBehavior
        from kivymd.uix.button.button import ButtonElevationBehaviour
        from kivymd.uix.dialog import BaseDialog
    except Exception:  # noqa: BLE001
        return

    def _make_no_shadow(orig_init):
        def _init(self, *a, **kw):
            orig_init(self, *a, **kw)
            try:
                self.elevation = 0
                ctx = getattr(self, "context", None)
                canvas_before = getattr(getattr(self, "canvas", None), "before", None)
                if ctx is not None and canvas_before is not None:
                    try:
                        if ctx in canvas_before.children:
                            canvas_before.remove(ctx)
                    except Exception:  # noqa: BLE001
                        pass
            except Exception:  # noqa: BLE001
                pass
        return _init

    CommonElevationBehavior.__init__ = _make_no_shadow(CommonElevationBehavior.__init__)
    ButtonElevationBehaviour.__init__ = _make_no_shadow(ButtonElevationBehaviour.__init__)
    BaseDialog.__init__ = _make_no_shadow(BaseDialog.__init__)

    try:
        from kivymd.uix.behaviors.ripple_behavior import CommonRipple

        def _no_ripple_touch(orig_td):
            def _td(self, touch):
                self._no_ripple_effect = True
                return orig_td(self, touch)
            return _td

        CommonRipple.on_touch_down = _no_ripple_touch(CommonRipple.on_touch_down)

        def _no_ripple_anim(self, touch):
            self._no_ripple_effect = True
            return None

        CommonRipple.call_ripple_animation_methods = _no_ripple_anim
    except Exception:  # noqa: BLE001
        pass

    try:
        orig_td_btn = ButtonElevationBehaviour.on_touch_down

        def _btn_td(self, touch):
            self._anim_raised = None
            return orig_td_btn(self, touch)

        ButtonElevationBehaviour.on_touch_down = _btn_td
    except Exception:  # noqa: BLE001
        pass


_disable_kivymd_elevation_shadows()

SPLASH_MIN_SEC = 1.8        # 品牌启动页最短停留（需求确认：1~2 秒）
SPLASH_MAX_SEC = 30.0       # 兜底：最迟移除


def _ensure_cjk_font():
    """注册中文字体（Kivy 默认 Roboto 不含中文）。

    优先使用打包的 Noto Sans SC（CI 下载）；缺失时尝试 Android 系统字体。
    """
    regular = bold = None
    p = resource_find(config.FONT_REGULAR)
    print("[牛票] FONT regular lookup:", config.FONT_REGULAR, "->", p)
    if p and os.path.exists(p):
        regular = p
        pb = resource_find(config.FONT_BOLD)
        bold = pb if pb and os.path.exists(pb) else None
    if not regular:
        for cand in ("/system/fonts/NotoSansCJK-Regular.ttc",
                     "/system/fonts/DroidSansFallback.ttf"):
            print("[牛票] FONT system cand:", cand, os.path.exists(cand))
            if os.path.exists(cand):
                regular = cand
                break
    print("[牛票] FONT chosen regular:", regular, "bold:", bold)
    if regular:
        try:
            LabelBase.register(name="Roboto", fn_regular=regular, fn_bold=bold or regular)
            LabelBase.register(name="RobotoMedium", fn_regular=regular, fn_bold=bold or regular)
            LabelBase.register(name="CJK", fn_regular=regular, fn_bold=bold or regular)
            print("[牛票] FONT registered OK (Roboto/RobotoMedium/CJK)")
        except Exception as e:  # noqa: BLE001
            print("[牛票] FONT register FAILED:", repr(e))
    return regular


class NiumenApp(MDApp):
    """牛票 App 外壳。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.title = "牛票"
        self.watchlist = Watchlist()
        self.pages = {}
        self.last_code = config.DEFAULT_CODE   # 牛门线/枢轴点共享的默认代码（需求 4）
        self._loading = False
        self._first_load_done = False
        self._splash_removed = False
        self._splash_started = time.time()

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------
    def build(self):
        diag_status("build() 开始")
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "Blue"
        self.theme_cls.primary_hue = "700"
        _ensure_cjk_font()
        diag_status("字体注册完成")

        from kivymd.uix.screen import MDScreen
        self.screen = MDScreen()
        root = MDBoxLayout(orientation="vertical")
        self.screen.add_widget(root)

        # 顶栏（应用名显示"牛票"）
        self.topbar = MDTopAppBar(
            title="牛票",
            md_bg_color=get_color_from_hex("#12294a"),
            elevation=0,  # KivyMD 阴影着色器在 Adreno 驱动上崩溃（真机 SIGSEGV）
            right_action_items=[
                ["refresh", lambda x: self._refresh_current()],
            ],
        )
        root.add_widget(self.topbar)

        # 页面容器（ScreenManager）+ 自定义底部导航栏
        self.sm = ScreenManager()
        for name, _text, _icon in TAB_DEFS:
            self.sm.add_widget(self._build_tab(name))
        root.add_widget(self.sm)

        # 自定义底部导航（无动画、无重影；选中高亮图标+文字）
        bar = MDBoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(58),
            md_bg_color=get_color_from_hex("#0d1b2a"),
        )
        self._tabs = {}
        for name, text, icon in TAB_DEFS:
            tab = _TabItem(
                orientation="vertical", size_hint_x=1, size_hint_y=None,
                height=dp(58), spacing=dp(0),
            )
            tab._name = name
            ico = MDIconButton(
                icon=icon, theme_icon_color="Custom", icon_color=_IDLE_COLOR,
                size_hint=(None, None), size=(dp(30), dp(30)),
                pos_hint={"center_x": 0.5},
            )
            ico.disabled = True  # 触摸交给 _TabItem(ButtonBehavior) 处理
            lb = MDLabel(
                text=text, font_style="Caption", font_size=sp(10),
                halign="center", size_hint_y=None, height=dp(18),
                theme_text_color="Custom", text_color=_IDLE_COLOR,
            )
            tab.add_widget(ico)
            tab.add_widget(lb)
            tab._icon = ico
            tab._label = lb
            bar.add_widget(tab)
            self._tabs[name] = tab
        root.add_widget(bar)
        self.sm.current = "niumen"
        self._select_tab("niumen")

        # 加载蒙层（全屏半透明，位于导航之上）
        self.loader = FloatLayout()
        _dim = FloatLayout(size_hint=(1, 1))
        with _dim.canvas.before:
            Color(0, 0, 0, 0.45)
            _dim._bg_rect = Rectangle(pos=_dim.pos, size=_dim.size)
        _dim.bind(
            pos=lambda o, *a: setattr(o._bg_rect, "pos", o.pos),
            size=lambda o, *a: setattr(o._bg_rect, "size", o.size),
        )
        self.loader.add_widget(_dim)
        self.loader.add_widget(MDLabel(
            text="加载中…", font_style="Subtitle1",
            halign="center", valign="center",
            theme_text_color="Primary",
            size_hint=(None, None), size=(dp(180), dp(64)),
            pos_hint={"center_x": 0.5, "center_y": 0.5},
        ))

        # 品牌启动页（需求 2）
        self._build_splash()

        diag_status("界面构建完成")
        # 首屏自动查询第一个默认标的
        Clock.schedule_once(lambda dt: self.pages["niumen"].on_query(config.DEFAULT_CODE), 0.5)
        Clock.schedule_interval(self._splash_tick, 0.15)
        Clock.schedule_once(lambda dt: self._raise_status_label(), 0.1)
        self._start_watchdog()
        return self.screen

    def _build_tab(self, name):
        """构建一个页面 Screen（ScrollView + 内容盒），并注册页面实例。"""
        from .ui_niumen import NiumenPage
        from .ui_pivot import PivotPage
        from .ui_batch import BatchPage
        from .ui_market import MarketPage
        makers = {
            "niumen": NiumenPage, "pivot": PivotPage,
            "batch": BatchPage, "market": MarketPage,
        }
        scr = Screen(name=name)
        body = ScrollView(do_scroll_x=False, bar_width=dp(4))
        box = MDBoxLayout(
            orientation="vertical",
            padding=[dp(12), dp(8), dp(12), dp(24)],
            spacing=dp(10),
            size_hint_y=None,
        )
        box.bind(minimum_height=box.setter("height"))
        body.add_widget(box)
        page = makers[name](self)
        page.build(box)
        scr.add_widget(body)
        self.pages[name] = page
        return scr

    def _switch_to(self, name):
        """切换页面：同步 ScreenManager 与底栏高亮；
        大盘页自动刷新（TTL 冷却）；枢轴点默认代码与牛门线同步。
        每次切换强制移除启动蒙层与状态标签（杜绝"牛票启动中…"残留）。"""
        if name == self.sm.current:
            return
        self._remove_splash()
        self._remove_status_label()
        self.sm.current = name
        self._select_tab(name)
        try:
            if name == "market":
                page = self.pages.get("market")
                if page is not None:
                    page.refresh_if_stale()
            elif name == "pivot":
                page = self.pages.get("pivot")
                if page is not None:
                    page.sync_default_code(self.last_code)
        except Exception:  # noqa: BLE001
            pass

    def _select_tab(self, name):
        for n, tab in self._tabs.items():
            sel = (n == name)
            try:
                tab._icon.icon_color = _ACTIVE_COLOR if sel else _IDLE_COLOR
                tab._label.text_color = (1, 1, 1, 1) if sel else _IDLE_COLOR
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # 品牌启动页（需求 2：文字在背景中清晰可见）
    # ------------------------------------------------------------------
    def _build_splash(self):
        self.splash = FloatLayout(size_hint=(1, 1))
        # 背景用固定窗口尺寸：Adreno 上 canvas 自动变换失效（画到窗口原点），
        # 用 pos=(0,0)+Window.size 无论如何都能盖满整个窗口
        with self.splash.canvas.before:
            Color(0.02, 0.05, 0.09, 0.97)
            self.splash._bg_rect = Rectangle(pos=(0, 0), size=Window.size)
        Window.bind(size=lambda w, v: setattr(self.splash._bg_rect, "size", v))
        self.splash.bind(
            size=lambda o, *a: setattr(o._bg_rect, "size", Window.size),
        )

        icon_path = resource_find("app/assets/icon.png")
        if icon_path:
            img = Image(
                source=icon_path, size_hint=(None, None), size=(dp(96), dp(96)),
                pos_hint={"center_x": 0.5, "center_y": 0.62},
            )
            self.splash.add_widget(img)
        self.splash.add_widget(MDLabel(
            text="牛票", font_style="H4", bold=True,
            halign="center", valign="middle",
            theme_text_color="Custom", text_color=(1, 1, 1, 1),
            size_hint=(1, None), height=dp(48),
            pos_hint={"center_x": 0.5, "center_y": 0.50},
        ))
        self.splash.add_widget(MDLabel(
            text="牛票启动中…", font_style="Subtitle1",
            halign="center", valign="middle",
            theme_text_color="Custom", text_color=(0.92, 0.95, 1.0, 1),
            size_hint=(1, None), height=dp(36),
            pos_hint={"center_x": 0.5, "center_y": 0.42},
        ))
        self.splash_progress = MDLabel(
            text="正在初始化…", font_style="Caption",
            halign="center", valign="middle",
            theme_text_color="Custom", text_color=(0.55, 0.62, 0.72, 1),
            size_hint=(1, None), height=dp(24),
            pos_hint={"center_x": 0.5, "center_y": 0.36},
        )
        self.splash.add_widget(self.splash_progress)

        diag.set_progress_cb(self._splash_progress_cb)
        self.screen.add_widget(self.splash)

    def _splash_progress_cb(self, msg):
        try:
            self.splash_progress.text = str(msg)
        except Exception:  # noqa: BLE001
            pass

    def _splash_tick(self, dt):
        if self._splash_removed:
            return
        elapsed = time.time() - self._splash_started
        if (elapsed >= SPLASH_MIN_SEC and self._first_load_done) or elapsed >= SPLASH_MAX_SEC:
            self._remove_splash()

    def _remove_splash(self):
        if self._splash_removed:
            return
        self._splash_removed = True
        # 从任意父节点移除（不依赖 self.screen 引用，杜绝残留）
        try:
            if self.splash is not None and self.splash.parent is not None:
                self.splash.parent.remove_widget(self.splash)
        except Exception:  # noqa: BLE001
            pass
        diag.set_progress_cb(None)
        self._remove_status_label()

    def notify_first_load_done(self):
        """首屏数据加载完成（牛门线页回调），用于移除启动页。"""
        self._first_load_done = True
        self._splash_tick(0)

    # ------------------------------------------------------------------
    # 加载蒙层
    # ------------------------------------------------------------------
    def show_loading(self, on):
        if on and not self._loading:
            self.screen.add_widget(self.loader)
            self._loading = True
        elif not on and self._loading:
            self.screen.remove_widget(self.loader)
            self._loading = False

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    def _refresh_current(self):
        page = self.pages.get("niumen")
        if page is not None and getattr(page, "_last_code", None):
            page.on_query(page._last_code)
        else:
            self._toast("请在本页输入代码查询")

    def _toast(self, msg):
        try:
            from kivymd.toast import toast
            toast(msg)
        except Exception:  # noqa: BLE001
            print("[牛票] %s" % msg)

    def _raise_status_label(self):
        """UI 根控件覆盖了启动状态标签，把它重新置顶以便继续可见。"""
        try:
            from kivy.core.window import Window
            if diag._status_label is not None and diag._status_label.parent is not None:
                Window.remove_widget(diag._status_label)
                Window.add_widget(diag._status_label)
        except Exception:  # noqa: BLE001
            pass

    def _remove_status_label(self):
        diag.remove_status_label()

    def _start_watchdog(self):
        """每 10 秒记录一次事件循环存活。"""
        def check(dt):
            diag_status("watchdog: 事件循环正常，运行 %.0fs" % dt, show_toast=False)
            Clock.schedule_once(check, 10)
        Clock.schedule_once(check, 10)

    def _show_crash(self, msg):
        """把异常信息显示在界面浮层上，便于无 adb 时直接截图反馈。"""
        try:
            from kivy.uix.label import Label as KivyLabel
            overlay = MDCard(
                size_hint=(0.95, 0.8),
                pos_hint={"center_x": 0.5, "center_y": 0.5},
                md_bg_color=(0.08, 0.08, 0.10, 0.96),
                elevation=0,
            )
            sv = ScrollView()
            lb = KivyLabel(
                text="[b]程序异常[/b]\n\n%s" % msg,
                markup=True,
                font_size=dp(12),
                color=(1, 0.45, 0.45, 1),
                size_hint_y=None,
                padding=[dp(12), dp(12)],
            )
            lb.bind(width=lambda o, *a: setattr(o, "text_size", (o.width, None)))
            lb.bind(texture_size=lambda o, *a: setattr(o, "height", o.texture_size[1]))
            sv.add_widget(lb)
            overlay.add_widget(sv)
            self.screen.add_widget(overlay)
        except Exception:  # noqa: BLE001
            pass
