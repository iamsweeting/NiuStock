# 牛票（Nstock）

一款在 **Android 手机**上运行的**三合一股票技术分析工具**，集成了两个工作区的成果：

| 功能 | 来源 | 说明 |
| --- | --- | --- |
| 📈 牛门线 | 牛门线分析（Kivy/KivyMD） | 唐奇安通道 + ATR 复合指标，最近 **10 个交易日** K 线 + 文字判读 |
| 🧮 枢轴点 | 股票枢轴点 StockPivotCalc | 五种枢轴算法（经典/斐波那契/卡玛利亚/伍迪/迪马克），按日/按周 |
| 📋 批量枢轴点 | 批量枢轴点 BatchStock | 多代码批量计算 + 一键复制结果 |
| 🏦 大盘信息 | 新增功能 | 本日实时（两市成交额/预测额/9大指数/沪深300中位数）+ 近5日历史（成交额/中间价/WTI/伦敦金/韩国半导体） |

> 技术栈：Python + [Kivy](https://kivy.org) + [KivyMD](https://kivymd.readthedocs.io)（Material Design 界面）
> 打包：Buildozer 在 GitHub Actions 中自动构建 APK（`nstock-1.0.0-arm64-v8a-debug.apk`）
> 应用名：**牛票**（英文 **Nstock**）· 包名 `org.nstock.nstock` · 图标：股票枢轴点图标

---

## 功能特性

- 🗂 **四页底部导航**：牛门线 / 枢轴点 / 批量枢轴点 / 大盘，一键切换
- 🏦 **大盘信息页**（切换页面自动刷新，TTL 90 秒 + 请求节流，低请求量防反爬）：
  - 本日实时：两市成交额 + **本日预测额**（按已交易时长线性外推）、
    上证/中证1000/沪深300/恒生/恒生科技/伦敦金/沪金/韩国KOSPI/日经 9 大标的、
    **沪深300中位数**（成分股价格中位数）+ **沪深300中位数市盈率(TTM)**（乐咕乐股）
  - 近 5 个交易日：两市成交额、美元兑人民币中间价、WTI原油、伦敦金、韩国半导体（三星电子+SK海力士）
  - 数据源：新浪（批量行情）、Yahoo（韩/日指数）、乐咕乐股（中位数PE）、
    中国货币网（中间价）、东方财富（两市成交额历史），各小节独立容错
- 🌐 **统一数据源**（自动切换，不显示切换按钮）：
  - 主：**腾讯财经历史K线**（前复权，含成交额，支持按周与下一交易日验证）
  - 备：**新浪财经历史K线**（腾讯失败自动回退）
- ⏱ **盘中处理**：枢轴点所选日=今天且处于交易时段（北京时间 9:15~15:00）时，
  自动使用**最近一个已收盘交易日**并标注（盘中K线跳动，枢轴数值不稳定）；
  牛门线图表保留盘中实时K线
- 📊 **牛门线 10 个交易日窗口**：NML/QRL/SMX（+CBX20/CBX60 成本线）5 色指标
- 🔍 **查询名单快捷按钮**：快捷区显示**名单前 3 个**，默认预置
  半导体设备ETF（159516）、稀土ETF（562800）、中证1000ETF（159845）；
  查询过的代码自动记入名单（最近在前、去重、上限 20），支持长按移除与清空
- 🚀 **品牌启动页**：深色蒙层 + 图标 + 「牛票启动中…」 + 进度里程碑，保证任何背景下清晰可见
- 🌗 **仅深色主题**：红涨绿跌，移动端友好
- 📅 日历回看任意交易日；枢轴点支持按日/按周、下一交易日/周误差验证标色
- 📋 批量枢轴点支持算法单选、单元格点击复制、一键复制全部

---

## 牛门线原理

牛门线本质是**唐奇安通道（Donchian Channel）+ ATR 波动率**的复合变形指标：

| 指标线 | 公式 | 含义 |
| --- | --- | --- |
| NML（牛门线） | `REF(HHV(H,20),1) + 0.5×ATR(14)` | 前 20 日最高价 + 0.5 倍平均真实波幅，突破入场 / 压力线 |
| QRL（强阻力线） | `REF(HHV(H,20),1) + 1.0×ATR(14)` | 前 20 日最高价 + 1 倍 ATR，强压力 / 止盈线 |
| SMX（生命线） | `MA(C,10)` | 10 日均线，趋势参考 / 止损线 |
| CBX20 / CBX60 | 20/60 日加权平均成本 | 标的版：`SUM(AMOUNT,N)/SUM(V,N)/100`；指数版：`SUM(C*V,N)/SUM(V,N)` |

## 枢轴点原理

| 算法 | PP 公式 | 说明 |
| --- | --- | --- |
| 经典 | `(H+L+C)/3` | R1~R3 / S1~S3 |
| 斐波那契 | `PP ± (H-L)×0.382/0.618/1.0` | R1~R3 / S1~S3 |
| 卡玛利亚 | `C ± (H-L)/12/6/4/2` | R1~R4 / S1~S4 |
| 伍迪 | `(H+L+2C)/4` | R1~R2 / S1~S2 |
| 迪马克 | 按 C 与 O 关系取 `X/4` | R1 / S1 |

> 验证：用下一交易日/周实际高低点对比，误差 ≤1% 标红(R)/绿(S)，≤2% 标橙/黄。

---

## 📲 在手机上安装（GitHub 自动打包）

1. 将本项目推送到你的 GitHub 仓库：

   ```bash
   git init
   git add .
   git commit -m "牛票 Nstock v1.0"
   git branch -M main
   git remote add origin https://github.com/<你的用户名>/nstock.git
   git push -u origin main
   ```

2. 打开仓库 **Actions** 标签页，`Build Android APK` 工作流自动运行：
   - `Unit tests`：先跑指标/判读/解析/枢轴算法/名单单元测试
   - `Build Android APK`：Buildozer（Docker）打包（首次约 30~60 分钟，之后有缓存更快）

3. 构建成功后，在本次运行的 **Summary → Artifacts** 下载 `nstock-apk`，
   解压得到 `nstock-1.0.0-arm64-v8a-debug.apk`，传到手机安装（需允许"安装未知来源应用"）。

---

## 🖥 本地运行与测试（可选，开发用）

桌面预览（需要 Python 3.8+）：

```bash
pip install kivy==2.2.0 kivymd==1.1.1 requests
bash tools/fetch_fonts.sh     # 下载中文字体（Windows 可用 Git Bash / WSL）
python main.py
```

运行单元测试：

```bash
pip install pytest
python -m pytest tests -v
```

沙箱受限环境（无法安装 pytest）可运行内置轻量 runner：

```bash
python tools/run_tests_local.py
```

## 项目结构

```
nstock/
├── main.py                    # 程序入口
├── buildozer.spec             # Buildozer 打包配置（title=牛票, package=nstock）
├── app/
│   ├── config.py              # 常量：DISPLAY_POINTS=10、默认名单、统一数据源链、配色
│   ├── api.py                 # 统一数据源（腾讯→新浪）+ 牛门线/枢轴点获取与聚合
│   ├── indicator.py           # 牛门线指标计算（纯函数）
│   ├── interpreter.py         # 牛门线文字判读（纯函数）
│   ├── pivot.py               # 五种枢轴算法 + 代码解析 + 验证标色（纯函数，移植）
│   ├── batch.py               # 批量枢轴点辅助（纯函数，移植）
│   ├── watchlist.py           # 查询名单持久化（最近在前、去重、上限20、管理）
│   ├── market.py              # 大盘信息：多数据源获取 + 纯解析函数 + 预测额计算
│   ├── chart.py               # Canvas K 线图（10 个交易日窗口）+ 日期轴
│   ├── clipboard.py           # 跨平台剪贴板（Android jnius）
│   ├── ui.py                  # App 外壳：品牌启动页 + 底部导航四页
│   ├── ui_niumen.py           # 牛门线页
│   ├── ui_pivot.py            # 枢轴点页
│   ├── ui_batch.py            # 批量枢轴点页
│   ├── ui_market.py           # 大盘信息页
│   ├── diag.py                # 启动诊断与启动页进度
│   └── assets/                # 图标（股票枢轴点图标）、字体（CI 下载）
├── tests/                     # 单元测试（指标/判读/解析/枢轴/名单/聚合）
├── tools/
│   ├── fetch_fonts.sh         # 下载 Noto Sans SC 中文字体
│   ├── run_tests_local.py     # 沙箱内轻量测试 runner（无 pytest 也可用）
│   └── docker_build.sh        # Docker 构建脚本
└── .github/workflows/
    └── build-apk.yml          # GitHub Actions：测试 + 打包 APK + 上传产物
```

---

## 常见问题

**Q：界面中文显示为方块？**
A：Kivy 默认字体不含中文。GitHub Actions 构建前会自动下载 Noto Sans SC 并打包进 APK；
若手动构建（非 CI）请先执行 `tools/fetch_fonts.sh`。

**Q：提示"获取数据失败"？**
A：统一数据源链（腾讯→新浪）均失败时提示。请确认代码格式（如 `159516`、`600519`、`HSTECH`）、
手机网络正常。部分海外代码（如个别期货/外汇品种）免费接口可能没有收录。

**Q：为什么枢轴点显示"今日盘中，自动使用最近收盘日"？**
A：所选日=今天且正处于交易时段（北京时间 9:15~15:00）时，盘中K线尚未定型，直接计算
枢轴数值会随价格跳动且无验证意义，因此自动回退到最近一个已收盘交易日。

**Q：成本线数值与券商软件不一致？**
A：腾讯 K 线含成交额时按 `SUM(AMOUNT,N)/SUM(V,N)/100`（成交额口径）；新浪备用源无成交额，
按 `收盘价×成交量` 加权估算，界面会标注"（估算口径）"。

**Q：APK 内 Python / Kivy / KivyMD 是什么版本？**
A：`buildozer.spec` 钉住 **Python 3.11.5 + Kivy 2.2.0 + KivyMD 1.1.1**（与牛门线工程一致，
已通过真机验证；p4a 相关兼容说明见 buildozer.spec 内注释）。

---

## 免责声明

本项目仅为技术指标（牛门线/枢轴点）的原理演示与个人学习工具，界面中的文字判读与数值
由程序按固定规则自动生成，**不构成任何投资建议**。股市有风险，投资需谨慎。

数据来源：腾讯财经（web.ifzq.gtimg.cn）、新浪财经（quotes.sina.cn）。
