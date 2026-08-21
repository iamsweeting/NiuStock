#!/usr/bin/env bash
# 下载中文字体（Kivy 默认 Roboto 不含中文，界面中文必须依赖 CJK 字体）。
# 在 GitHub Actions 构建前执行；字体文件较大，已被 .gitignore 排除，不进入仓库。
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)/app/assets/fonts"
mkdir -p "$DIR"

# 主源（GitHub raw）与镜像（jsDelivr CDN）
BASE_PRIMARY="https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/OTF/SimplifiedChinese"
BASE_MIRROR="https://cdn.jsdelivr.net/gh/notofonts/noto-cjk@main/Sans/OTF/SimplifiedChinese"

FILES=(
  "NotoSansCJKsc-Regular.otf"
  "NotoSansCJKsc-Bold.otf"
)

for f in "${FILES[@]}"; do
  out="$DIR/$f"
  echo ">> 下载 $f ..."
  if ! curl -fL --retry 3 -o "$out" "$BASE_PRIMARY/$f"; then
    echo ">> 主源失败，尝试 jsDelivr 镜像 ..."
    curl -fL --retry 3 -o "$out" "$BASE_MIRROR/$f"
  fi
  # 校验非空
  if [ ! -s "$out" ]; then
    echo "!! 字体下载失败：$f" >&2
    exit 1
  fi
done

echo ">> 字体就绪："
ls -la "$DIR"
