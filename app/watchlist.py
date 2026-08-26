# -*- coding: utf-8 -*-
"""牛门线查询名单（自选）持久化。

规则（需求确认）：
  - 每个代码记录累计查询次数 count（重启保留）；
  - 排序分两段：
      前三名（快捷按钮）：受门槛保护 —— 进入第1名需比现第1名多 +30 次，
          进入第2/3名需比现任多 +50 次；每次触摸最多升一位（无级联）。
      第4名以后（近期查询列表）：纯按 count 降序排列。
  - 第三名被替换：第4名（或更后）代码 count 比现第3名多 ≥50 时顶掉它，
      原第3名顺延到第4名（同一次触摸只升一位，不继续往上顶）。
  - 上限 config.WATCHLIST_LIMIT（10 条），超出淘汰排名最末；
  - 首次安装预置默认名单（159516 半导体设备ETF / 688008 澜起科技 / 513310 中韩半导体ETF）；
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
        self._items = []          # [{"code": ..., "name": ..., "count": n}] 排名在前
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
                    old_format = False
                    for it in data:
                        if isinstance(it, dict) and it.get("code"):
                            items.append({
                                "code": str(it["code"]),
                                "name": str(it.get("name") or it["code"]),
                                "count": int(it.get("count") or 0),
                            })
                            if "count" not in it:
                                old_format = True
                    if items:
                        if old_format:
                            # 旧数据（最近在前、无 count）：默认前三置顶，其余保留
                            items = self._migrate_old(items)
                        else:
                            items = self._rank(items, touched_code=None)
                        self._items = items[:config.WATCHLIST_LIMIT]
                        return self._items
        except Exception:  # noqa: BLE001
            pass
        self._items = [dict(it, count=0) for it in config.DEFAULT_WATCHLIST]
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
    # 排序
    # ------------------------------------------------------------------
    @staticmethod
    def _promote_threshold(target_index):
        """进入 target_index 名次所需超过的次数（0 为第 1 名）。"""
        return config.RANK_PROMOTE_TOP1 if target_index == 0 else config.RANK_PROMOTE_OTHER

    @staticmethod
    def _migrate_old(items):
        """旧格式迁移：默认前三置顶（count=0），其余代码按原顺序跟在后面。"""
        default_codes = [d["code"] for d in config.DEFAULT_WATCHLIST]
        head = [dict(d, count=0) for d in config.DEFAULT_WATCHLIST]
        seen = set(default_codes)
        tail = [it for it in items if it["code"] not in seen]
        return head + tail

    def _rank(self, items, touched_code):
        """排序：
        1) 第3名及以后（含第3名）：无门槛，纯按 count 降序（多 1 次即可上升）；
        2) 前两名门槛保护：升入第1名需比现第1名多 +30，升入第2名需比现第2名多 +50；
           每次触摸最多升一位（无级联）。
        """
        items = list(items)
        # 1) 第3名及以后：纯 count 降序（默认前三中的第三名同样参与，无门槛）
        if len(items) > 2:
            head, tail = items[:2], items[2:]
            tail.sort(key=lambda it: it["count"], reverse=True)
            items = head + tail
        # 2) 前两名门槛
        if touched_code is None:
            # 加载：逐对检查一次（3→2 需 +50；2→1 需 +30）
            if len(items) > 2 and items[2]["count"] - items[1]["count"] >= self._promote_threshold(1):
                items[1], items[2] = items[2], items[1]
            if len(items) > 1 and items[1]["count"] - items[0]["count"] >= self._promote_threshold(0):
                items[0], items[1] = items[1], items[0]
            return items
        idx = next((i for i, it in enumerate(items) if it["code"] == touched_code), -1)
        # 触摸对象：最多升一位（只可能跨前两名门槛）
        if idx == 2 and items[2]["count"] - items[1]["count"] >= self._promote_threshold(1):
            items[1], items[2] = items[2], items[1]
        elif idx == 1 and items[1]["count"] - items[0]["count"] >= self._promote_threshold(0):
            items[0], items[1] = items[1], items[0]
        return items

    # ------------------------------------------------------------------
    # 操作
    # ------------------------------------------------------------------
    def items(self):
        """当前名单（按排名）。"""
        self.load()
        return list(self._items)

    def touch(self, code, name=None):
        """查询成功后记录：count +1，按阈值重排（最多升一位），裁剪上限，落盘。"""
        self.load()
        code = (code or "").strip()
        if not code:
            return
        found = None
        for it in self._items:
            if it["code"] == code:
                found = it
                break
        if found:
            found["count"] = found.get("count", 0) + 1
            if name:
                found["name"] = (name or code).strip()
        else:
            self._items.append({
                "code": code, "name": (name or code).strip(), "count": 1,
            })
        self._items = self._rank(self._items, touched_code=code)
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
        self._items = [dict(it, count=0) for it in config.DEFAULT_WATCHLIST]
        self._save()

    def top(self, n=3):
        """取前 n 个快捷标的；不足时用默认名单补齐。"""
        items = self.items()
        seen = {it["code"] for it in items}
        for it in config.DEFAULT_WATCHLIST:
            if len(items) >= n:
                break
            if it["code"] not in seen:
                items.append(dict(it, count=0))
        return items[:n]
