# ============================================================================
# Buildozer 配置 —— 将 Kivy/KivyMD 应用（牛票 Nstock）打包为 Android APK
# 构建在 GitHub Actions 的 kivy/buildozer Docker 镜像中执行
# ============================================================================

[app]

# 应用信息
title = 牛票
package.name = nstock
package.domain = org.nstock

# 源码目录与打包范围
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,otf,ttf,txt,json,md
source.exclude_dirs = tests,.github,.buildozer,bin,tools,__pycache__,p4a-recipes

# 版本（用户确认发布版本 1.5）
version = 1.5
# 数字版本号 → Android versionCode（必须大于旧版 1024105，避免降级拒绝；
# 1500000 去点转 int = 1500000，下次 1.6 → 1600000）
version.numeric = 1500000

# Python 依赖。
# python3==3.11.5：由 docker_build.sh 动态改写为容器内构建 Python 的确切版本；
# 必须为 3.11.5 —— 本地覆盖的 hostpython3 recipe（p4a-recipes/）版本即 3.11.5，
# 且 p4a 要求两者一致；同时 Kivy 2.2.0 只能在 <=3.12 上构建（Python 3.13+
# 移除 cgi 模块，导致 "config.pxi 缺失" / "ModuleNotFoundError: cgi"）。
# cython：保证 .pyx/.pxi 预处理（cythonize）在构建环境中可用。
# kivy/kivymd 钉住社区验证过的兼容组合（避免 pip 解析器在 kivymd 1.2.0 + kivy 最新版
# 之间报 "Cannot install ... conflicting dependencies"）；requests/pillow 走 p4a recipe 默认。
# 代码兼容 Kivy 2.2+/2.3+ 与 KivyMD 1.1.1+/1.2.0。

requirements = python3==3.11.5,cython,kivy==2.2.0,kivymd==1.1.1,requests,pillow



# 屏幕方向与全屏
orientation = portrait
fullscreen = 0

# Android 配置
android.permissions = INTERNET
# API 34：满足现代 p4a/AGP8 的 compileSdk>=34 要求；避开 Android 15 对 targetSdk 35
# 的强制 edge-to-edge（SDL2 2.30 已处理，但 34 行为变化最小）
android.api = 34
android.minapi = 24
# 仅 arm64-v8a：p4a v2026.05.09 的多架构构建有 bug——两个架构共用 build/venv，
# 第二个架构的 `python -m venv venv`（无 --clear）会把捆绑的旧版 pip 覆盖到已升级的
# pip 上，导致 "cannot import name 'open_rich_spinner'" 构建失败（develop 分支已修，
# 加 --clear 并移除 pip 自升级步骤）。单架构规避该问题，且 2025 年机型均为 arm64。
android.archs = arm64-v8a
android.accept_sdk_license = True
android.allow_backup = True
android.private_storage = True

# p4a（python-for-android）钉到 2026 最新 release：自带 SDL2 2.30.x 与 NDK r27 支持，
# 兼容 Android 15+ 与 16KB 内存页设备（2024 年初的 v2024.01.21 + NDK r25c 在新机
# 上表现为黑屏/原生库无法加载）。新版 p4a 的 hostpython3 硬编码 3.14.2 且强制
# python3 同版本，与 Kivy 2.2.0（仅支持 <=3.12）冲突 —— 通过 p4a.local_recipes 本地
# 覆盖 hostpython3 版本为 3.11.5（见 p4a-recipes/），与构建 Python 3.11.5 一致。
p4a.branch = v2026.05.09
p4a.local_recipes = %(source.dir)s/p4a-recipes

# NDK r27b：16KB 内存页对齐等 Android 15 时代要求的默认实现（r25c 无 16KB 支持）
android.ndk = 27b

# 固定调试签名密钥：debug 包由 AGP 用 ~/.android/debug.keystore 签名（缺失时
# 自动生成 -> 每次全新 runner 签名漂移，真机升级报 INSTALL_FAILED_UPDATE_
# INCOMPATIBLE）。tools/docker_build.sh 启动时把仓库内 keystore/debug.keystore
# （androiddebugkey/android）复制到该位置，所有构建共享同一签名。
# 注意：buildozer 对任意 p4a.* 键无通用透传，p4a.android_keystore 会被静默忽略；
# 且 p4a 的 --keystore 系列参数仅 release 构建生效，debug 走 AGP 默认路径。

# ---- Release 签名（v1.5 起发布 release 版）----
# 签名信息经环境变量注入 p4a（实测 buildozer 对 spec 的 android.keystore 系列键
# 透传不可靠，日志报 "P4A_RELEASE_KEYSTORE missing"）：
#   tools/docker_build.sh 构建前 export：
#     P4A_RELEASE_KEYSTORE=/home/user/hostcwd/keystore/release.keystore
#     P4A_RELEASE_KEYSTORE_PASSWD=nstock2026
#     P4A_RELEASE_KEYSTORE_ALIAS=nstock
#     P4A_RELEASE_KEYSTORE_ALIAS_PASSWD=nstock2026
# 密钥：keystore/release.keystore（RSA-2048，有效期 30 年）。
# 注意：release 签名与 debug 不同，真机从 debug 版升级需先卸载旧包
# （INSTALL_FAILED_UPDATE_INCOMPATIBLE）。
android.release_artifact = apk

# 图标（由 tools/make_icon.ps1 生成；当前使用股票枢轴点图标 —— 需求 5）
icon.filename = %(source.dir)s/app/assets/icon.png

[buildozer]

log_level = 2
warn_on_root = 1
