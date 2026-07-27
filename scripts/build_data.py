#!/usr/bin/env python3
"""
build_data.py — 从官方公开数据源拉取真实数据，生成 data.js
=================================================================
数据源（全部免 API Key）:
  - FRED fredgraph.csv      利率/信用/波动率/经济/资产价格/美联储资产负债表
  - NY Fed Markets API      SOFR / RRP / SRF
  - Treasury FiscalData     TGA 余额
  - Yahoo Finance (UA)      黄金/白银/ETF/外汇/NDX/RUT

自动计算: 日/周/月/半年变化 (1/5/21/126 个交易日)、1年历史分位数
输出: ../data.js
"""
import csv, io, json, sys, time, subprocess
from datetime import datetime, timedelta

def http_get(url, timeout=25, use_ua=False):
    """通过 curl 拉取。注意: 本环境代理对 Mozilla UA 会卡死，FRED/NYFed/DTS 必须不带 UA；Yahoo 需要 UA"""
    last_err = None
    for attempt in range(3):
        try:
            cmd = ['curl', '-s', '--max-time', str(timeout)]
            if use_ua:
                cmd += ['-H', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)']
            cmd.append(url)
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 15, encoding='utf-8', errors='replace')
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout
            last_err = f'curl exit {r.returncode}'
        except Exception as e:
            last_err = str(e)
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(last_err or 'unknown')

# ---------- FRED ----------
def fred(series_id, days=380):
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}&coed={end}'
    try:
        text = http_get(url)
        rows = list(csv.reader(io.StringIO(text)))
        if len(rows) < 2: return []
        out = []
        for r in rows[1:]:
            if len(r) >= 2 and r[1] not in ('', '.'):
                # 校验日期格式, 防止 FRED 错误页/HTML 垃圾行进入序列 (如下架序列)
                if len(r[0]) != 10 or r[0][4] != '-' or r[0][7] != '-':
                    continue
                try: out.append((r[0], float(r[1])))
                except ValueError: pass
        return out
    except Exception as e:
        print(f'  [FRED:{series_id}] FAIL {e}')
        return []

# ---------- NY Fed ----------
def nyfed_sofr(n=130):
    try:
        data = json.loads(http_get(f'https://markets.newyorkfed.org/api/rates/secured/sofr/last/{n}.json'))
        return [(x['effectiveDate'], float(x['percentRate'])) for x in reversed(data.get('refRates', []))]
    except Exception as e:
        print(f'  [NYFED:SOFR] FAIL {e}'); return []

def nyfed_rrp(n=130):
    try:
        data = json.loads(http_get(f'https://markets.newyorkfed.org/api/rates/reverserepo/all/last/{n}.json'))
        ops = data.get('repo', {}).get('operations', [])
        out = []
        for x in reversed(ops):
            amt = x.get('totalAmtAccepted') or x.get('totalAmtSubmitted')
            if amt: out.append((x['operationDate'], float(amt) / 1e9))  # → $B
        return out
    except Exception as e:
        print(f'  [NYFED:RRP] FAIL {e}'); return []

def nyfed_srf(n=60):
    try:
        data = json.loads(http_get(f'https://markets.newyorkfed.org/api/rates/standingrepo/all/last/{n}.json'))
        ops = data.get('repo', {}).get('operations', [])
        out = []
        for x in reversed(ops):
            amt = x.get('totalAmtAccepted') or 0
            out.append((x['operationDate'], float(amt) / 1e6))  # → $M
        return out
    except Exception as e:
        print(f'  [NYFED:SRF] FAIL {e}'); return []

# ---------- Treasury DTS (TGA) ----------
def fetch_tga(days=380):
    start = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    # 注意: 方括号必须编码为 %5B %5D; sort=-record_date 才能正确应用 filter 并取到最新值
    # 每页400行(含非TGA账户), 需翻页直至覆盖整个窗口
    out = []
    for page in range(1, 5):
        url = ('https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/operating_cash_balance'
               f'?filter=record_date:gte:{start}&sort=-record_date&page%5Bsize%5D=400&page%5Bnumber%5D={page}')
        try:
            data = json.loads(http_get(url))
        except Exception as e:
            print(f'  [DTS:TGA] page{page} FAIL {e}'); break
        rows = data.get('data', [])
        if not rows: break
        for x in rows:
            if x.get('account_type', '').startswith('Treasury General Account'):
                bal = x.get('open_today_bal')
                if bal and bal != 'null':
                    out.append((x['record_date'], float(bal) / 1e3))  # $M → $B
        # 本页最旧日期已早于起点 → 覆盖完成
        if rows[-1].get('record_date', '9999') <= start:
            break
    # 去重 + 时间升序
    seen = {}
    for d, v in out: seen[d] = v
    return sorted(seen.items())

# ---------- Yahoo ----------
def yahoo(symbol, rng='1y'):
    enc = symbol.replace('^', '%5E').replace('=', '%3D')
    url = f'https://query2.finance.yahoo.com/v8/finance/chart/{enc}?range={rng}&interval=1d'
    try:
        data = json.loads(http_get(url, use_ua=True))
        res = data['chart']['result'][0]
        ts = res.get('timestamp', [])
        closes = res['indicators']['quote'][0]['close']
        out = []
        for t, c in zip(ts, closes):
            if c is not None:
                out.append((datetime.utcfromtimestamp(t).strftime('%Y-%m-%d'), float(c)))
        return out
    except Exception as e:
        print(f'  [YH:{symbol}] FAIL {e}')
        return []

# ---------- 计算 ----------
def chg(series, back):
    """变化值: 最新 - back个点之前 (series按时间升序)"""
    if len(series) < back + 1: return None
    return series[-1][1] - series[-1 - back][1]

def pct_chg(series, back):
    if len(series) < back + 1: return None
    prev = series[-1 - back][1]
    if prev == 0: return None
    return (series[-1][1] / prev - 1) * 100

def percentile(series, window=252):
    """最新值在最近window个点中的分位 (0-100)"""
    vals = [v for _, v in series[-window:]]
    if len(vals) < 5: return 50
    cur = vals[-1]
    rank = sum(1 for v in vals if v <= cur)
    return round(rank / len(vals) * 100)

def tf(series, is_pct=False):
    """四尺度变化 dict: d/w/m/h6"""
    f = pct_chg if is_pct else chg
    return {
        'd': f(series, 1), 'w': f(series, 5),
        'm': f(series, 21), 'h6': f(series, 126)
    }

def fmt(v, digits=2, sign=True, unit=''):
    if v is None: return '—'
    s = f'{v:+.{digits}f}' if sign else f'{v:.{digits}f}'
    return s + unit

def last(series):
    return series[-1] if series else (None, None)

print('=' * 60)
print(' US Macro Observer · 真实数据管线')
print('=' * 60)
T0 = time.time()

# ================= 拉取全部序列 =================
S = {}  # series store
FRED_IDS = {
    # 利率
    'DGS1MO': 'dgs1mo', 'DGS3MO': 'dgs3mo', 'DGS6MO': 'dgs6mo', 'DGS1': 'dgs1',
    'DGS2': 'dgs2', 'DGS3': 'dgs3', 'DGS5': 'dgs5', 'DGS7': 'dgs7',
    'DGS10': 'dgs10', 'DGS20': 'dgs20', 'DGS30': 'dgs30',
    'DFII5': 'tips5', 'DFII10': 'tips10', 'DFII30': 'tips30', 'T10YIE': 'bei10',
    'DFEDTARU': 'ffr_up', 'DFEDTARL': 'ffr_lo', 'IORB': 'iorb', 'DPCREDIT': 'disc',
    # 美联储资产负债表 (周度) — MBSST 已下架, MBS 持仓用 WSHOMCB
    'WALCL': 'walcl', 'TREAST': 'treast', 'WSHOMCB': 'mbst', 'WRESBAL': 'resbal',
    # 流动性
    'RRPONTSYD': 'rrp',
    # 信用 (ICE BofA OAS)
    'BAMLC0A0CM': 'ig', 'BAMLC0A4CBBB': 'bbb', 'BAMLH0A0HYM2': 'hy',
    'BAMLH0A1HYBB': 'bb', 'BAMLH0A2HYB': 'b', 'BAMLH0A3HYC': 'ccc',
    'BAMLC0A1CAAA': 'aaa', 'BAMLC0A2CAA': 'aa', 'BAMLC0A3CA': 'a',
    # 波动率
    'VIXCLS': 'vix', 'OVXCLS': 'ovx', 'GVZCLS': 'gvz',
    # 注意: VIX9D/VIX3M/SKEW 已被 FRED 下架 (CBOE 授权), 改从 Yahoo 取
    # 金融条件
    'NFCI': 'nfci',
    # 资产
    'SP500': 'spx', 'NASDAQCOM': 'ndx_comp', 'DJIA': 'dji',
    'DCOILWTICO': 'wti', 'DTWEXBGS': 'dxy_broad',
    'CBBTCUSD': 'btc', 'CBETHUSD': 'eth',
    # 经济
    'UNRATE': 'unrate', 'PAYEMS': 'payems', 'CPIAUCSL': 'cpi', 'CPILFESL': 'core_cpi',
    'PCEPILFE': 'core_pce', 'PCEPI': 'pce', 'GDP': 'gdp', 'GDPC1': 'gdp_real',
    'PCEC96': 'pce_real', 'RSAFS': 'retail',
    'UMCSENT': 'umich', 'ICSA': 'claims', 'DGORDER': 'durables',
    # CPI 分项 (用于通胀拆解)
    'CPIENGSL': 'cpi_energy', 'CPIUFDSL': 'cpi_food', 'CUSR0000SAH1': 'cpi_shelter',
    'CUSR0000SASLE': 'cpi_core_svcs', 'CUSR0000SACL1E': 'cpi_core_goods',
}
# 低频序列需要更长窗口: 季度序列 1500d (~16个季度, 支持同比); 月度序列 760d (~25个月)
QUARTERLY = {'gdp', 'gdp_real'}
MONTHLY = {'unrate', 'payems', 'cpi', 'core_cpi', 'core_pce', 'pce', 'pce_real', 'retail',
           'umich', 'durables', 'cpi_energy', 'cpi_food', 'cpi_shelter', 'cpi_core_svcs', 'cpi_core_goods'}
for fid, key in FRED_IDS.items():
    days = 1500 if key in QUARTERLY else (760 if key in MONTHLY else 380)
    S[key] = fred(fid, days=days)
    d, v = last(S[key])
    print(f'  FRED {fid:14s} → {len(S[key]):4d} pts, latest {d} = {v}')

print('  -- NY Fed / DTS / Yahoo --')
S['sofr'] = nyfed_sofr();      print(f'  NYFED SOFR → {len(S["sofr"])} pts, latest {last(S["sofr"])}')
S['rrp_api'] = nyfed_rrp();    print(f'  NYFED RRP → {len(S["rrp_api"])} pts, latest {last(S["rrp_api"])}')
S['srf'] = nyfed_srf();        print(f'  NYFED SRF → {len(S["srf"])} pts, latest {last(S["srf"])}')
S['tga'] = fetch_tga();        print(f'  DTS TGA → {len(S["tga"])} pts, latest {last(S["tga"])}')

YH_IDS = {
    '^NDX': 'ndx', '^RUT': 'rut', 'GC=F': 'gold', 'SI=F': 'silver',
    'NG=F': 'natgas', 'HG=F': 'copper', 'DX-Y.NYB': 'dxy',
    'EURUSD=X': 'eurusd', 'GBPUSD=X': 'gbpusd', 'USDJPY=X': 'usdjpy', 'USDCNH=X': 'usdcnh',
    'TLT': 'tlt', 'IEF': 'ief', 'LQD': 'lqd', 'HYG': 'hyg', 'SPY': 'spy', 'QQQ': 'qqq',
    '^VVIX': 'vvix', '^MOVE': 'move', '^SKEW': 'skew', '^VIX3M': 'vix3m', '^VIX9D': 'vix9d'
}
for sym, key in YH_IDS.items():
    S[key] = yahoo(sym)
    print(f'  YH {sym:10s} → {len(S[key]):4d} pts, latest {last(S[key])}')
    time.sleep(0.4)

# 与上次运行合并: 本次拉取失败(空)的序列沿用昨日缓存, 避免瞬时故障导致前端数据回退为空
try:
    PREV = json.load(open('raw_series.json'))
    healed = []
    for k in list(S.keys()):
        if not S[k] and PREV.get(k):
            S[k] = PREV[k]
            healed.append(k)
    if healed:
        print(f'  [缓存回补] {len(healed)} 个序列沿用上次数据: {", ".join(healed)}')
except Exception:
    pass

# 保存原始数据供检查
with open('raw_series.json', 'w') as f:
    json.dump({k: v for k, v in S.items()}, f)
print(f'\n原始序列已存 raw_series.json ({time.time()-T0:.1f}s)')

# ================= 汇总关键数值 =================
R = {}  # results
def reg(key, series, is_pct=False, unit='', digits=2):
    d, v = last(series)
    if v is None:
        R[key] = None; print(f'  !! {key} no data'); return
    R[key] = {
        'date': d, 'value': v, 'pct': percentile(series),
        'tf': tf(series, is_pct), 'series30': [round(v, 4) for _, v in series[-30:]],
        'series90': [round(v, 4) for _, v in series[-90:]],
        'unit': unit, 'digits': digits
    }

print('\n-- 计算变化与分位 --')
# FRED 中的资产价格序列用百分比变化(与 Yahoo 资产口径一致), 利率/余额类仍用点位/绝对差
FRED_PCT_ASSETS = {'spx', 'ndx_comp', 'dji', 'wti', 'dxy_broad', 'btc', 'eth'}
for k in FRED_IDS.values(): reg(k, S[k], is_pct=(k in FRED_PCT_ASSETS))
for k in ['sofr', 'rrp_api', 'srf', 'tga']: reg(k, S[k])
# 波动率指数用点位差(pt)而非百分比, 与 FRED 的 VIX 口径一致
YH_LEVEL = {'vvix', 'move', 'skew', 'vix9d', 'vix3m'}
for k in YH_IDS.values(): reg(k, S[k], is_pct=(k not in YH_LEVEL))

# 净流动性(同单位 $B) = WALCL($M→$B) - RRP($B) - TGA($B)
# WALCL 为周三快照, RRP/TGA 为日度 → 按最近邻(±4天)对齐, 避免交集过稀
def merge_netliq():
    from bisect import bisect_left
    walcl = {d: v / 1000.0 for d, v in S['walcl']}           # $M → $B
    rrp = dict(S['rrp_api'] if S['rrp_api'] else S['rrp'])    # $B
    tga = dict(S['tga'])                                      # $B
    def nearest(dates_map, d0, tol=4):
        ds = sorted(dates_map)
        if not ds: return None
        i = bisect_left(ds, d0)
        cands = [ds[j] for j in (i - 1, i) if 0 <= j < len(ds)]
        if not cands: return None
        best = min(cands, key=lambda d: abs((datetime.fromisoformat(d) - datetime.fromisoformat(d0)).days))
        if abs((datetime.fromisoformat(best) - datetime.fromisoformat(d0)).days) <= tol:
            return dates_map[best]
        return None
    out = []
    for d in sorted(walcl):
        r = nearest(rrp, d); t = nearest(tga, d)
        if r is not None and t is not None:
            out.append((d, walcl[d] - r - t))
    return out  # $B
S['netliq'] = merge_netliq()
print(f'  NETLIQ → {len(S["netliq"])} pts, latest {last(S["netliq"])}')
reg('netliq', S['netliq'])

with open('computed.json', 'w') as f:
    json.dump(R, f, default=str)
print(f'计算结果已存 computed.json')
print('完成。下一步: 用 computed.json 重建 data.js')
