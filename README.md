# US Macro Observer · 美国宏观数据观察平台

## 快速开始

```bash
# 方式 1：直接打开
用浏览器打开 index.html 即可查看（样本数据）

# 方式 2：本地服务器（推荐，Chart.js 需要 HTTP 协议）
cd us-macro-observer
python -m http.server 8765
# 浏览器访问 http://localhost:8765
```

## 获取真实数据

```bash
# 1. 注册免费 FRED API Key
#    https://fredaccount.stlouisfed.org/apikeys

# 2. 设置环境变量
set FRED_API_KEY=你的key          # Windows
export FRED_API_KEY=你的key        # Linux/Mac

# 3. 安装依赖并运行
pip install requests
python scripts/fetch_fred.py
```

## 7 个子板块

| 板块 | 内容 | 数据源 |
|------|------|--------|
| 大类资产 | 股票/债券/商品/外汇/加密货币 + 相关性矩阵 | Yahoo Finance |
| 利率 | 收益率曲线 + 关键利率走势 | FRED (DGS系列) |
| 美联储 | 资产负债表 + 政策利率 + QT | FRED (WALCL等) |
| 流动性 | 净流动性 + RRP/TGA + LPI 压力指数 | FRED + NY Fed |
| 经济数据 | CPI/就业/GDP/PMI | FRED |
| 信用市场 | HY/IG利差 + NFCI | FRED (BAML系列) |
| 波动率 | VIX/MOVE + 期限结构 | FRED + Cboe |

## 技术栈

- 纯 HTML/CSS/JS，无构建步骤
- Chart.js v4（CDN）
- 数据层：data.js（样本）或 data.json（FRED API 真实数据）
- 可选：Python 脚本从 FRED 拉取真实数据

## 项目结构

```
us-macro-observer/
├── index.html          # 主页面
├── styles.css          # 样式
├── data.js             # 样本数据（内置）
├── app.js              # 应用逻辑 + 图表渲染
├── scripts/
│   └── fetch_fred.py   # FRED API 数据拉取脚本
└── README.md
```

## 扩展方向

- [ ] 接入 Yahoo Finance 非官方 API 获取实时行情
- [ ] 添加 AI 研判层（LLM 生成市场摘要）
- [ ] 增加历史回测功能
- [ ] 添加暗色主题
- [ ] 部署到 Vercel/Cloudflare Pages
