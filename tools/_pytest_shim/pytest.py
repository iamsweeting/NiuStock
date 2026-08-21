# -*- coding: utf-8 -*-
"""pytest 最小兼容层（仅本地沙箱 runner 使用，CI 用真实 pytest）。"""


class _Approx:
    def __init__(self, expected, rel=None, abs=None):
        self.expected = expected
        self.rel = rel
        self.abs = abs

    def __eq__(self, other):
        try:
            diff = abs(other - self.expected)
            tol = self.abs if self.abs is not None else max(1e-9, abs(self.expected) * 1e-9)
            return diff <= tol
        except Exception:
            return False

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return "approx(%r)" % (self.expected,)


def approx(v, rel=None, abs=None):
    return _Approx(v, rel=rel, abs=abs)


class _Raises:
    def __init__(self, exc):
        self.exc = exc

    def __enter__(self):
        return self

    def __exit__(self, t, v, tb):
        if t is None:
            raise AssertionError("%s not raised" % self.exc)
        return issubclass(t, self.exc)


def raises(exc):
    return _Raises(exc)
