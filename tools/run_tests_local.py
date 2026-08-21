# -*- coding: utf-8 -*-
"""沙箱内本地测试 runner：模拟 pytest 最小接口（approx/raises），
逐模块导入 tests/ 下 test_*.py 并执行全部 test_* 函数。

GitHub Actions（CI）仍使用真实 pytest（tools/docker 环境），本脚本仅用于
本地沙箱快速验证，避免在受限环境安装 pytest。
"""
import importlib.util
import inspect
import os
import sys
import tempfile
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")

# 沙箱内 tempfile 必须落在工作区（系统 %TEMP% 被沙箱拒绝写入）
_TMP = os.path.join(ROOT, ".pytmp")
os.makedirs(_TMP, exist_ok=True)
os.environ["TMP"] = _TMP
os.environ["TEMP"] = _TMP
import tempfile
tempfile.tempdir = _TMP

# ---- 最小 pytest 兼容层 ----
SHIM = os.path.join(ROOT, "tools", "_pytest_shim")
sys.path.insert(0, SHIM)
sys.path.insert(0, ROOT)

# 确保 shim 生效（若环境有真 pytest 则优先真 pytest）
try:
    import pytest as _real  # noqa: F401
    import pytest  # noqa: F401
except Exception:
    pass


def _discover():
    mods = []
    for fn in sorted(os.listdir(TESTS)):
        if fn.startswith("test_") and fn.endswith(".py"):
            mods.append(fn[:-3])
    return mods


def main():
    failed = 0
    total = 0
    for name in _discover():
        path = os.path.join(TESTS, name + ".py")
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception:
            print("[IMPORT FAIL] %s" % name)
            traceback.print_exc()
            failed += 1
            continue
        for attr in dir(mod):
            if attr.startswith("test_"):
                total += 1
                try:
                    fn = getattr(mod, attr)
                    args = inspect.signature(fn).parameters
                    kwargs = {}
                    if "tmp_path" in args:
                        # 手工建目录而非 mkdtemp：沙箱拒绝写入 mkdtemp 子目录
                        import uuid
                        from pathlib import Path
                        td = os.path.join(tempfile.tempdir or _TMP,
                                          "nstock_t_" + uuid.uuid4().hex[:8])
                        os.makedirs(td, exist_ok=True)
                        kwargs["tmp_path"] = Path(td)
                        fn(**kwargs)
                    else:
                        fn()
                    print("[PASS] %s.%s" % (name, attr))
                except Exception:
                    failed += 1
                    print("[FAIL] %s.%s" % (name, attr))
                    traceback.print_exc()
    print("=" * 50)
    print("total=%d failed=%d" % (total, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
