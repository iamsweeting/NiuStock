#!/usr/bin/env bash
# ============================================================================
# 在 kivy/buildozer 容器内执行的构建脚本（工作目录 = /home/user/hostcwd = 仓库根）。
#
# 背景：kivy/buildozer:latest 镜像的 venv Python 为 3.14.x，而 Kivy 2.x 只能在
# Python <=3.12 上构建（cython 0.29 依赖的 cgi 模块在 3.13+ 被移除），且 p4a 要求
# 运行环境 Python 版本与 buildozer.spec 钉版一致（否则报
# "python3 should have same version as hostpython3, x != y"）。
#
# 版本约束：构建 Python 必须为 3.11.5 —— 与 p4a-recipes/ 本地覆盖的 hostpython3
# 版本一致（新版 p4a v2026.05.09 的 hostpython3 默认 3.14.2 并强制 python3 同版本，
# 与 Kivy 2.2.0 冲突，故本地覆盖为 3.11.5）；且 Kivy 2.2.0 只能在 <=3.12 上构建
# （3.13+ 移除 cgi 模块，报 config.pxi 缺失）。故本脚本固定取 3.11.5。
#
# 另：镜像基座升级（Ubuntu 25.04 基底）后自带 /usr/bin/cmake 为 CMake 4.x；
# CMake 4.0 起移除了对 cmake_minimum_required(<3.5) 项目的兼容，导致 p4a 的
# jpeg（libjpeg-turbo 2.1.0, min 2.8.12）等 cmake recipe configure 报
# "Compatibility with CMake < 3.5 has been removed from CMake."，
# 因此本脚本把 cmake 用 pip 钉到 3.29.6 并置入 PATH 首位，全局绕开该问题。
#
# 本脚本：
#   1. 打印容器内可用 Python 清单（诊断用）；
#   2. 自动选择 3.11.5 的 Python（与 p4a-recipes/ 覆盖的 hostpython3 版本一致；
#      找不到依次尝试 apt / uv 安装，仍失败则明确报错退出）；
#   3. 用选中的 Python 新建独立 venv，安装最新 buildozer + cython + pip<24，
#      并把 cmake 钉为 3.29.6（置入 PATH 首位）；
#   4. 把 buildozer.spec 中 python3 钉版动态改为该 Python 的"确切版本"，
#      从构造上消除 hostpython3 版本不匹配；
#   5. 清理镜像预置的旧 python 构建产物（保留 SDK/NDK），再执行构建。
# ============================================================================
set -uo pipefail

# 容器内 git 对挂载目录（hostcwd 等）的所有权检查会报 dubious ownership；
# freetype 等 recipe 的 make 可能触发 git 调用（如 check_out_submodule），
# 全局豁免避免误报（构建不依赖真实 git 历史）。
git config --global --add safe.directory '*' 2>/dev/null || true

# 固定 debug 签名：debug 包由 AGP 用默认 $HOME/.android/debug.keystore 签名，
# 该文件缺失时 AGP 自动生成（每次全新 runner 都生成新密钥 -> 签名漂移，
# 真机升级报 INSTALL_FAILED_UPDATE_INCOMPATIBLE）。把仓库内固定 keystore
# （alias=androiddebugkey / pass=android，标准 Android 调试密钥参数）放过去，
# AGP 存在即复用，所有构建共享同一签名。
mkdir -p /root/.android /home/user/.android
cp -f /home/user/hostcwd/keystore/debug.keystore /root/.android/debug.keystore 2>/dev/null || true
cp -f /home/user/hostcwd/keystore/debug.keystore /home/user/.android/debug.keystore 2>/dev/null || true
echo "== debug keystore 就位: $(ls -la /root/.android/debug.keystore 2>/dev/null | awk '{print $5, $9}') =="

echo "================ Python 版本清单（诊断） ================"
for p in /usr/bin/python3* /usr/local/bin/python3*; do
  if [ -x "$p" ]; then echo "  $p -> $("$p" --version 2>&1)"; fi
done

# ---------- 1. 选择 Python ----------
# 只接受 3.11.5（必须与 p4a v2024.01.21 的 hostpython3 默认版本完全一致，
# 否则 Python 3.12 configure 交叉编译报 "has incompatible version ..."）。
PYBIN=""
for p in python3.11 python3.12 python3.10 python3; do
  if command -v "$p" >/dev/null 2>&1; then
    v="$("$p" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null || echo bad)"
    if [ "$v" = "3.11.5" ]; then PYBIN="$p"; break; fi
  fi
done

# ---------- 2. 找不到则依次尝试 apt → uv（python-build-standalone） ----------
if [ -z "$PYBIN" ]; then
  echo ">> 未发现 3.11.5，尝试 apt 安装 python3.11 ..."
  if apt-get update -qq >/dev/null 2>&1 && apt-get install -y -qq python3.11 python3.11-venv >/dev/null 2>&1 \
     && command -v python3.11 >/dev/null 2>&1; then
    # apt 提供的 3.11.x 补丁版本未必是 3.11.5，仍需精确校验
    v="$(python3.11 -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null || echo bad)"
    [ "$v" = "3.11.5" ] && PYBIN=python3.11
  fi
fi
if [ -z "$PYBIN" ]; then
  # kivy/buildozer:latest（Ubuntu 25.x 基底）只提供 python 3.13/3.14，apt 里也没有
  # python3.11；改用它自带的 python3 建临时 venv，pip 装 uv，再由 uv 拉取
  # python-build-standalone 的 CPython 3.11.5（自包含、无需 root、任意发行版可用）。
  echo "!! apt 无 3.11.5，改用 uv 拉取 python 3.11.5 ..."
  python3 -m venv /tmp/bz-boot-venv
  /tmp/bz-boot-venv/bin/pip install --quiet --upgrade uv 2>/dev/null || \
    /tmp/bz-boot-venv/bin/pip install --quiet --upgrade --break-system-packages uv 2>/dev/null || true
  if [ -x /tmp/bz-boot-venv/bin/uv ]; then
    /tmp/bz-boot-venv/bin/uv python install 3.11.5 >/dev/null 2>&1 || true
    PYBIN="$(/tmp/bz-boot-venv/bin/uv python find 3.11.5 2>/dev/null || true)"
  fi
fi
if [ -z "$PYBIN" ]; then
  echo "============================================================"
  echo "!! 无法获得 Python 3.11.5（apt 与 uv 均已尝试）。"
  echo "!! 本地覆盖的 hostpython3（p4a-recipes/）固定为 3.11.5，目标 python3 必须一致；"
  echo "!! 且 Kivy 2.2.0 只能在 <=3.12 上构建（3.13+ 移除 cgi 模块，报 config.pxi 缺失）。"
  echo "!! 请先让容器可用 python3.11.5（apt install python3.11 python3.11-venv，"
  echo "!! 或 uv python install 3.11.5）后重试。当前可用 Python："
  for p in /usr/bin/python3* /usr/local/bin/python3*; do
    [ -x "$p" ] && echo "    $p -> $("$p" --version 2>&1)"
  done
  echo "============================================================"
  exit 1
fi
echo "== 使用构建 Python: $PYBIN -> $("$PYBIN" --version 2>&1) =="

# ---------- 3. 新建独立 venv 并安装工具链 ----------
"$PYBIN" -m venv /tmp/bz-venv
# 新 venv 内无 PEP 668 标记；先降 pip<24（兼容旧 p4a 内部 API），再装 buildozer/cython
/tmp/bz-venv/bin/pip install --upgrade --quiet "pip<24" buildozer cython || \
  /tmp/bz-venv/bin/pip install --upgrade --quiet --break-system-packages "pip<24" buildozer cython
/tmp/bz-venv/bin/python -m pip --version

# CMake 钉为 3.29.6 并置于 PATH 首位：镜像 /usr/bin/cmake 已是 CMake 4.x，
# 4.0 移除了对 cmake_minimum_required(<3.5) 的兼容，p4a 的 jpeg（libjpeg-turbo 2.1.0，
# min 2.8.12）/ sdl2_image 等 recipe 会直接 configure 失败。
# pip 的 cmake wheel 为 py3-none，3.10-3.14 的 venv 均可安装；buildozer/p4a 的 recipe
# 环境继承父进程 PATH（仅在头部追加 NDK 目录），故 venv bin 置首即可生效。
/tmp/bz-venv/bin/pip install --upgrade --quiet "cmake==3.29.6" || \
  /tmp/bz-venv/bin/pip install --upgrade --quiet --break-system-packages "cmake==3.29.6"
export PATH="/tmp/bz-venv/bin:$PATH"
echo "== cmake: $(command -v cmake) -> $(cmake --version | head -1) =="

# ---------- 4. 钉版与运行 Python 版本对齐 ----------
PYVER="$("$PYBIN" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
sed -i "s/python3==[0-9.]*/python3==$PYVER/" buildozer.spec
echo "== buildozer.spec requirements 已同步: python3==$PYVER =="
grep '^requirements' buildozer.spec

# ---------- 5. 清理镜像预置的旧 python 构建产物（保留 SDK/NDK） ----------
rm -rf /root/.buildozer/android/platform/build-* \
       /root/.buildozer/android/platform/python* \
       /root/.buildozer/android/platform/hostpython* 2>/dev/null || true
rm -rf /home/user/.buildozer/android/platform/build-* \
       /home/user/.buildozer/android/platform/python* \
       /home/user/.buildozer/android/platform/hostpython* 2>/dev/null || true

# ---------- 6. 构建 ----------
echo ">> 开始构建（release，签名 keystore/release.keystore，alias=nstock）..."
# release 签名：p4a 通过环境变量接收密钥（实测 buildozer 对 spec 键透传不可靠，
# 报 "P4A_RELEASE_KEYSTORE missing" 产出 unsigned APK），这里显式注入。
export P4A_RELEASE_KEYSTORE=/home/user/hostcwd/keystore/release.keystore
export P4A_RELEASE_KEYSTORE_PASSWD=nstock2026
export P4A_RELEASE_KEYSTORE_ALIAS=nstock
export P4A_RELEASE_KEYSTORE_ALIAS_PASSWD=nstock2026
echo "== release 签名注入: $P4A_RELEASE_KEYSTORE ($(ls -la "$P4A_RELEASE_KEYSTORE" 2>/dev/null | awk '{print $5}') bytes) =="
echo y | /tmp/bz-venv/bin/buildozer -v android release
