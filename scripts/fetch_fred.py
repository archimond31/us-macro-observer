#!/usr/bin/env python3
"""
fetch_fred.py — 从 FRED API 拉取真实宏观数据并生成 data.json
================================================================
使用方法:
  1. 在 https://fredaccount.stlouisfed.org/apikeys 免费注册获取 API Key
  2. 设置环境变量: set FRED_API_KEY=你的key   (Windows)
                    export FRED_API_KEY=你的key  (Linux/Mac)
  3. 运行: python fetch_fred.py
  4. 生成的 data.json 会被 app.js 自动加载（如果存在）

依赖: pip install requests
"""

import json
import os
import sys
from datetime import datetime, timedelta

try:
    import requests
except ImportError:
    print("请先安装 requests: pip install requests")
    sys.exit(1)

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
API_KEY = os.environ.get("FRED_API_KEY", "")

if not API_KEY:
    print("=" * 60)
    print(" 未检测到 FRED_API_KEY 环境变量")
    print("=" * 60)
    print(" 获取免费 API Key:")
    print(" 1. 访问 https://fredaccount.stlouisfed.org/apikeys")
    print(" 2. 注册并创建 API Key")
    print(" 3. 设置环境变量:")
    print("    Windows: set FRED_API_KEY=你的key")
    print("    Linux:   export FRED_API_KEY=你的key")
    print(" 4. 重新运行此脚本")
    sys.exit(1)

# FRED 数据系列映射表
SERIES = {
    # 利率
    "DGS1":  {"label": "1Y国债",   "section": "rates"},
    "DGS2":  {"label": "2Y国债",   "section": "rates"},
    "DGS5":  {"label": "5Y国债",   "section": "rates"},
    "DGS10": {"label": "10Y国债",  "section": "rates"},
    "DGS30": {"label": "30Y国债",  "section": "rates"},
    "T10Y2Y":{"label": "10Y-2Y利差","section": "rates"},
    "T10YIE":{"label": "10Y通胀保值","section": "rates"},
    "DFEDTARU":{"label": "联邦基金利率上限","section": "rates"},

    # 美联储
    "WALCL": {"label": "美联储总资产",   "section": "fed"},
    "TREAST":{"label": "国债持仓",       "section": "fed"},
    "MBST":  {"label": "MBS持仓",        "section": "fed"},

    # 流动性
    "RRPONTSYD":{"label": "RRP余额",     "section": "liquidity"},
    "WTREGEN":  {"label": "TGA余额",     "section": "liquidity"},
    "WRESBAL":  {"label": "银行准备金",  "section": "liquidity"},
    "SOFR":     {"label": "SOFR",        "section": "liquidity"},

    # 经济数据
    "CPIAUCSL": {"label": "CPI",         "section": "economy"},
    "CPILFESL": {"label": "核心CPI",     "section": "economy"},
    "UNRATE":   {"label": "失业率",      "section": "economy"},
    "PAYEMS":   {"label": "非农就业",    "section": "economy"},
    "GDP":      {"label": "GDP",         "section": "economy"},

    # 信用市场
    "BAMLH0A0HYM2":{"label": "HY OAS",  "section": "credit"},
    "BAMLC0A0CM":  {"label": "IG OAS",  "section": "credit"},
    "NFCI":        {"label": "NFCI",     "section": "credit"},

    # 波动率
    "VIXCLS":  {"label": "VIX",         "section": "volatility"},
}


def fetch_series(series_id, days=180):
    """从 FRED 拉取单个数据系列"""
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    params = {
        "series_id": series_id,
        "api_key": API_KEY,
        "file_type": "json",
        "observation_start": start_date,
        "observation_end": end_date,
    }
    try:
        resp = requests.get(FRED_BASE, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        observations = data.get("observations", [])
        # 过滤掉无效值
        points = []
        for obs in observations:
            val = obs.get("value", ".")
            if val != ".":
                points.append({
                    "date": obs.get("date"),
                    "value": float(val)
                })
        print(f"  {series_id}: {len(points)} 条记录")
        return points
    except Exception as e:
        print(f"  {series_id}: 拉取失败 - {e}")
        return []


def main():
    print("=" * 60)
    print(" FRED 数据拉取工具")
    print("=" * 60)
    print(f" API Key: {API_KEY[:8]}...")
    print(f" 拉取 {len(SERIES)} 个数据系列\n")

    result = {
        "meta": {
            "lastUpdated": datetime.now().strftime("%Y-%m-%d %H:%M ET"),
            "dataSource": f"FRED API (实时数据)",
            "fetchTime": datetime.now().isoformat()
        },
        "series": {}
    }

    for series_id, info in SERIES.items():
        print(f"拉取 {info['label']} ({series_id})...")
        points = fetch_series(series_id)
        result["series"][series_id] = {
            "label": info["label"],
            "section": info["section"],
            "data": points
        }

    output_path = os.path.join(os.path.dirname(__file__), "..", "data.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n数据已保存到: {output_path}")
    print(f"共 {len(result['series'])} 个系列")
    print("\n刷新页面即可查看真实数据。")


if __name__ == "__main__":
    main()
