# 生成应用图标（512x512 PNG）。
# 需要 Windows + .NET System.Drawing；仅在本地开发时使用，图标已入库无需重复生成。
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

$size = 512
$bmp = New-Object System.Drawing.Bitmap($size, $size)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAlias

# 圆角路径
$path = New-Object System.Drawing.Drawing2D.GraphicsPath
$r = 110
$path.AddArc(0, 0, $r, $r, 180, 90)
$path.AddArc($size - $r, 0, $r, $r, 270, 90)
$path.AddArc($size - $r, $size - $r, $r, $r, 0, 90)
$path.AddArc(0, $size - $r, $r, $r, 90, 90)
$path.CloseFigure()
$g.SetClip($path)

# 背景渐变（深蓝）
$rect = New-Object System.Drawing.Rectangle(0, 0, $size, $size)
$bg = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
    $rect,
    [System.Drawing.Color]::FromArgb(255, 38, 72, 128),
    [System.Drawing.Color]::FromArgb(255, 10, 18, 40),
    90)
$g.FillRectangle($bg, $rect)

# 装饰网格点（弱化）
$gridPen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(40, 255, 255, 255), 2)
for ($i = 1; $i -lt 8; $i++) {
    $x = $i * 64
    $g.DrawLine($gridPen, $x, 0, $x, $size)
    $g.DrawLine($gridPen, 0, $x, $size, $x)
}

# K线蜡烛：红涨（左）、绿跌（右）
function Draw-Candle($x, $bodyTop, $bodyBottom, $wickTop, $wickBottom, $color) {
    $pen = New-Object System.Drawing.Pen($color, 14)
    $g.DrawLine($pen, $x, $wickTop, $x, $wickBottom)
    $body = New-Object System.Drawing.SolidBrush($color)
    $g.FillRectangle($body, ($x - 34), $bodyTop, 68, [Math]::Max($bodyBottom - $bodyTop, 8))
}

$red = [System.Drawing.Color]::FromArgb(255, 239, 83, 80)
$green = [System.Drawing.Color]::FromArgb(255, 102, 187, 106)
Draw-Candle 176 210 150 240 120 $red
Draw-Candle 336 260 320 230 290 $green

# 顶部"牛"字
$font = New-Object System.Drawing.Font("Microsoft YaHei", 190, [System.Drawing.FontStyle]::Bold)
$white = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 255, 255, 255))
$sf = New-Object System.Drawing.StringFormat
$sf.Alignment = [System.Drawing.StringAlignment]::Center
$sf.LineAlignment = [System.Drawing.StringAlignment]::Center
$textRect = New-Object System.Drawing.RectangleF(0, -20, $size, 260)
$g.DrawString("牛", $font, $white, $textRect, $sf)

$outDir = Join-Path $PSScriptRoot "..\app\assets"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$outPath = Join-Path $outDir "icon.png"
$bmp.Save($outPath, [System.Drawing.Imaging.ImageFormat]::Png)
Write-Output "icon saved: $outPath"
$g.Dispose(); $bmp.Dispose()
