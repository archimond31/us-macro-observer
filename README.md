# US Macro Observer · 美国宏观数据观察平台

7 大板块 × 官方真实数据 × 每日自动更新。纯静态站点，无构建步骤。

## 快速开始

```bash
cd us-macro-observer
python -m http.server 8765
# 浏览器访问 http://localhost:8765
```

## 数据流水线（全部免 API Key）

```
build_data.py  →  拉取官方数据 → computed.json / raw_series.json
gen_datajs.py  →  计算同比/变化/分位 + 生成叙述 → ../data.js
render_smoke.cjs → 无头渲染 7 板块冒烟测试 (CI 质量门)
```

```bash
cd scripts
python build_data.py     # ~3 分钟, 86 个序列
python gen_datajs.py
node render_smoke.cjs    # 退出码 0 = 通过
```

### 数据源

| 源 | 内容 | 备注 |
|----|------|------|
| FRED fredgraph.csv | 利率/信用OAS/波动率(VIX/OVX/GVZ)/经济/资产负债表 | 无需 Key |
| NY Fed Markets API | SOFR / RRP / SRF | 无需 Key |
| Treasury FiscalData DTS | TGA 余额 (分页拉取) | 无需 Key |
| Yahoo Finance chart API | 股指/ETF/商品/外汇 + VVIX/MOVE/SKEW/VIX9D/VIX3M | 需 UA 头 |

### 数据准确性约定

- **图表与表格数值 = 官方源真实计算**，无任何硬编码/伪造序列
- 同比 (YoY) 按日期最近邻匹配基期；月度序列取 760 天窗口，季度序列 1500 天
- 净流动性 ($B) = WALCL($M/1000) − RRP − TGA，按周三快照 ±4 天最近邻对齐
- 相关性矩阵 = 近 60 个共同交易日日度收益的真实 Pearson 相关
- FRED 已下架的 CBOE 序列 (SKEW/VIX9D/VIX3M) 改走 Yahoo；解析器带日期格式校验，垃圾行自动丢弃
- FOMC 时间线 / 官员讲话 / 鹰鸽打分 = 分析师策展内容 (结构化标注)
- 月度频率指标的四尺度: 月格=Δ1个月，半年格=Δ6个月 (日/周格显示 "—")

## 每日自动更新

`.github/workflows/daily-update.yml`：每天 UTC 01:00（北京 09:00）自动重跑流水线并提交 `data.js`，冒烟测试失败则中止。配合 GitHub Pages 即公网每日更新：

1. 把本目录推送到 GitHub 仓库
2. Settings → Pages → Source 选 `main` 分支根目录
3. Actions 里手动触发一次 "Daily Macro Data Update" 验证

## 项目结构

```
us-macro-observer/
├── index.html            # 主页面
├── styles.css            # 样式
├── data.js               # 真实数据 (自动生成, 勿手改)
├── app.js                # 应用逻辑 + 图表渲染
├── .github/workflows/    # 每日更新 workflow
└── scripts/
    ├── build_data.py     # 取数 (FRED/NYFed/DTS/Yahoo)
    ├── gen_datajs.py     # 计算 + 生成 data.js
    ├── render_smoke.cjs  # 无头渲染冒烟测试
    └── fetch_fred.py     # (旧) FRED API Key 版, 已被 build_data.py 取代
```

## 扩展方向

- [ ] AI 研判层（LLM 基于真实数据生成每日市场摘要）
- [ ] 历史回测 / 信号胜率统计
- [ ] 暗色主题
