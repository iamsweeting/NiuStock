# -*- coding: utf-8 -*-
"""牛门线查询名单（自选）持久化。

规则（需求确认）：
  - 每次查询成功的代码按「最近查询顺序」去重，最新在前；
  - 上限 config.WATCHLIST_LIMIT（20 条），超出淘汰最旧；
  - 首次安装预置默认名单（159516 / 513310 / 159845 三只 ETF）；
  - 提供管理：remove(code) 删除单条、clear() 清空全部。

存储：Android 上为应用私有存储 user_data_dir/watchlist.json；
桌面调试时回退到用户目录 watchlist.json。
"""
import json
import os

from . import config


class Watchlist:
    def __init__(self, path=None):
        self.path = path
        self._items = []          # [{"code": ..., "name": ...}] 最新在前
        self._loaded = False

    # ------------------------------------------------------------------
    # 路径与加载
    # ------------------------------------------------------------------
    def _default_path(self):
        if self.path:
            return self.path
        try:
            from kivy.app import App
            app = App.get_running_app()
            if app is not None:
                return os.path.join(app.user_data_dir, "watchlist.json")
        except Exception:  # noqa: BLE001
            pass
        return os.path.join(os.path.expanduser("~"), "watchlist.json")

    def load(self):
        """加载名单；文件缺失或损坏时返回默认名单（不写盘，等首次变更再写）。"""
        if self._loaded:
            return self._items
        self._loaded = True
        p = self._default_path()
        try:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    items = []
                    for it in data:
                        if isinstance(it, dict) and it.get("code"):
                            items.append({
                                "code": str(it["code"]),
                                "name": str(it.get("name") or it["code"]),
                            })
                    if items:
                        self._items = items[:config.WATCHLIST_LIMIT]
                        return self._items
        except Exception:  # noqa: BLE001
            pass
        self._items = [dict(it) for it in config.DEFAULT_WATCHLIST]
        return self._items

    def _save(self):
        p = self._default_path()
        try:
            d = os.path.dirname(p)
            if d:
                os.makedirs(d, exist_ok=True)
            tmp = p + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._items, f, ensure_ascii=False, indent=1)
            os.replace(tmp, p)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # 操作
    # ------------------------------------------------------------------
    def items(self):
        """当前名单（最新在前）。"""
        self.load()
        return list(self._items)

    def touch(self, code, name=None):
        """查询成功后记录：去重、移到最前、裁剪上限、落盘。"""
        self.load()
        code = (code or "").strip()
        if not code:
            return
        new_item = {"code": code, "name": (name or code).strip()}
        self._items = [it for it in self._items if it["code"] != code]
        self._items.insert(0, new_item)
        self._items = self._items[:config.WATCHLIST_LIMIT]
        self._save()

    def remove(self, code):
        """删除单条。"""
        self.load()
        before = len(self._items)
        self._items = [it for it in self._items if it["code"] != code]
        if len(self._items) != before:
            self._save()

    def clear(self):
        """清空全部（回到默认预置名单）。"""
        self.load()
        self._items = [dict(it) for it in config.DEFAULT_WATCHLIST]
        self._save()

    def top(self, n=3):
        """取前 n 个快捷标的；不足时用默认名单补齐。"""
        items = self.items()
        seen = {it["code"] for it in items}
        for it in config.DEFAULT_WATCHLIST:
            if len(items) >= n:
                break
            if it["code"] not in seen:
                items.append(dict(it))
        return items[:n]
