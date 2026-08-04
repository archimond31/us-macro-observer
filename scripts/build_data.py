#!/usr/bin/env python3
"""
build_data.py — 从官方公开数据源拉取真实数据，生成 data.js
=================================================================
数据源:
  - FRED fredgraph.csv      利率/信用/波动率/经济/资产价格/美联储资产负债表
  - NY Fed Markets API      SOFR / RRP / SRF
  - Treasury FiscalData     TGA 余额
  - Yahoo Finance (UA)      黄金/白银/ETF/外汇/NDX/RUT/波动率/30Y
  - BEA NIPA API (需 BEA_API_KEY)  最新实际GDP (T10101/5/6), 覆盖 FRED GDPC1 滞后
  - Atlanta Fed GDPNow (免key)       本季实时预估 (端点可能变更, 失败静默跳过)
  - CoinGlass API (需 COINGLASS_API_KEY)  BTC/ETH 现货 ETF 每日净流量 (flow-history, 替代被 Cloudflare 拦截的 farside)

自动计算: 日/周/月/半年变化 (1/5/21/126 个交易日)、1年历史分位数
输出: ../data.js
"""
import csv, io, json, os, sys, time, subprocess, re
from datetime import datetime, timedelta
from html import unescape

def http_get(url, timeout=25, use_ua=False, headers=None):
    """通过 curl 拉取。注意: 本环境代理对 Mozilla UA 会卡死，FRED/NYFed/DTS 必须不带 UA；Yahoo 需要 UA。
    --compressed 让 curl 自动接受并解压 gzip 响应 (Yahoo/CBOE 默认 gzip, 否则 json.loads 会因二进制头报 Expecting value)。"""
    last_err = None
    for attempt in range(3):
        try:
            cmd = ['curl', '-s', '--compressed', '--max-time', str(timeout)]
            if use_ua:
                cmd += ['-H', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)']
            for h in (headers or []):
                cmd += ['-H', h]
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

# ---------- TGA (Treasury General Account) ----------
# 首选 FRED 官方序列 WTREGEN (单位 $M=百万美元, 美联储 H.4.1 口径, 即市场普遍引用的 TGA 余额)
# 注意: 旧代码用的 WTREGENL 在 FRED 上不存在(返回404), 会静默回退到易错的 Treasury DTS
def fetch_tga_fred(days=420):
    s = fred('WTREGEN', days=days)
    if not s:
        return []
    return [(d, v / 1000.0) for d, v in s]   # $M → $B

# 兜底: Treasury FiscalData DTS (日度, 但字段口径有歧义, 仅作回退)
def fetch_tga_dts(days=380):
    start = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
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
                bal = x.get('close_today_bal') or x.get('open_today_bal')
                if bal and bal != 'null':
                    out.append((x['record_date'], float(bal) / 1e3))  # $M → $B
        if rows[-1].get('record_date', '9999') <= start:
            break
    seen = {}
    for d, v in out: seen[d] = v
    return sorted(seen.items())

def fetch_tga(days=420):
    s = fetch_tga_fred(days)
    if s:
        return s
    print('  [TGA] FRED WTREGEN 不可用, 回退 Treasury DTS')
    return fetch_tga_dts(days)

# ---------- PMI (FRED 已下架 ISM 序列 NAPMPMI/NAPM; 改用 S&P Global 美国 PMI, 经 Trading Economics 稳定抓取) ----------
# 静态兜底: S&P Global 美国 PMI 历史 (final, 来源 Trading Economics/FRED 存档), 仅当实时抓取彻底失败时使用
_STATIC_SPG_MFG = [
    ("2024-12-01",49.4),("2025-01-01",51.2),("2025-02-01",52.7),("2025-03-01",49.8),
    ("2025-04-01",50.2),("2025-05-01",52.9),("2025-06-01",52.0),("2025-07-01",49.5),
    ("2025-08-01",53.0),("2025-09-01",52.5),("2025-10-01",52.0),("2025-11-01",52.2),
    ("2025-12-01",52.3),("2026-01-01",52.4),("2026-02-01",51.6),("2026-03-01",52.3),
    ("2026-04-01",54.5),("2026-05-01",55.1),("2026-06-01",55.7),
]
_STATIC_SPG_SVC = [
    ("2024-12-01",57.0),("2025-01-01",52.9),("2025-02-01",53.0),("2025-03-01",54.0),
    ("2025-04-01",53.5),("2025-05-01",53.0),("2025-06-01",54.0),("2025-07-01",52.7),
    ("2025-08-01",53.5),("2025-09-01",54.0),("2025-10-01",53.8),("2025-11-01",53.5),
    ("2025-12-01",54.6),("2026-01-01",54.6),("2026-02-01",53.5),("2026-03-01",54.0),
    ("2026-04-01",55.0),("2026-05-01",55.5),("2026-06-01",55.0),
]

def _te_pmi_latest(slug):
    """抓取 Trading Economics 某 PMI 页面最新值+月份, 返回 (date 'YYYY-MM-01', value) 或 None。"""
    try:
        html = http_get(f'https://tradingeconomics.com/united-states/{slug}', timeout=15, use_ua=True)
    except Exception as e:
        print(f'  [PMI] TE {slug} 抓取失败: {e}'); return None
    import re as _re
    m = _re.search(r'to\s+([\d.]+)\s+points\s+in\s+([A-Za-z]+)(?:\s+of\s+|\s+)(\d{4})', html)
    if not m:
        print(f'  [PMI] TE {slug} 未匹配到数值'); return None
    try:
        val = float(m.group(1)); mon = datetime.strptime(m.group(2)[:3], '%b').month; yr = int(m.group(3))
    except Exception:
        return None
    return (f'{yr}-{mon:02d}-01', val)

def _pmi_merge(base, latest):
    """把 latest 合并进 base(按月去重), 保留最近 36 个月。base/latest 为 [(date,val)...]。"""
    d = {}
    for dt, v in base:
        d[dt[:7]] = v
    if latest:
        d[latest[0][:7]] = latest[1]
    return [(k + '-01', d[k]) for k in sorted(d)][-36:]

def fetch_pmi():
    """
    获取美国 PMI (制造业 + 服务业)。
    FRED 的 ISM 序列(NAPMPMI/NAPM)已下架; 改用 S&P Global 美国 PMI (经 Trading Economics 稳定抓取, 比 ISM 更实时)。
    返回 {'mfg':[(d,v)...], 'svc':[...], 'is_fallback':bool, 'asof':str}
    - 实时抓取成功: 在静态历史底座上追加最新月, is_fallback=False
    - 实时抓取彻底失败: 退回静态底座, is_fallback=True (前端需打明确警告标)
    """
    mfg_latest = _te_pmi_latest('manufacturing-pmi')
    svc_latest = _te_pmi_latest('services-pmi')
    is_fallback = False; asof = None
    if mfg_latest:
        mfg = _pmi_merge(_STATIC_SPG_MFG, mfg_latest); asof = mfg_latest[0][:7]
    else:
        mfg = list(_STATIC_SPG_MFG); is_fallback = True
    if svc_latest:
        svc = _pmi_merge(_STATIC_SPG_SVC, svc_latest); asof = svc_latest[0][:7] if asof is None else asof
    else:
        svc = list(_STATIC_SPG_SVC); is_fallback = True
    print(f'  [PMI] S&P Global → mfg {mfg_latest}, svc {svc_latest} (fallback={is_fallback}, asof={asof})')
    return {'mfg': mfg, 'svc': svc, 'is_fallback': is_fallback, 'asof': asof}

# ---------- Empire State Manufacturing (NY Fed, FRED 无此序列) ----------
# 静态兜底: Empire State 总体经济活动指数 (扩散指数, >0 扩张)
_STATIC_EMPIRE = [
    ("2025-01-01",-5.1),("2025-02-01",-6.3),("2025-03-01",-7.0),("2025-04-01",-9.0),
    ("2025-05-01",-8.4),("2025-06-01",-8.2),("2025-07-01",-6.2),("2025-08-01",-10.6),
    ("2025-09-01",-13.2),("2025-10-01",-13.5),("2025-11-01",-16.2),("2025-12-01",-14.5),
    ("2026-01-01",-10.2),("2026-02-01",-18.7),("2026-03-01",-24.4),("2026-04-01",-34.8),
    ("2026-05-01",-28.5),("2026-06-01",-12.6),("2026-07-01",-0.6),
]

def fetch_empire():
    """
    获取纽约联储 Empire State 制造业指数 (总体经济活动扩散指数)。
    FRED 不收录此序列; 数据源优先级:
      1) NY Fed 官网 survey 页面抓取
      2) Trading Economics
      3) 静态兜底 (需手动定期更新)
    返回 {'data':[...], 'is_fallback':bool, 'asof':str}
    """
    # 源1: NY Fed Empire State survey 页面
    _result = None
    try:
        html = http_get('https://www.newyorkfed.org/survey/empire/emire_overview.html', timeout=15)
        import re as _re2
        m = _re2.search(r'(?:General\s+(?:Business\s+)?Activity|headline)[^0-9-]*([+-]?[\d.]+)', html, _re2.I)
        if m:
            val = float(m.group(1))
            # 尝试提取日期
            dm = _re2.search(r'([A-Za-z]+)\s+(\d{4})', html)
            if dm:
                mon = datetime.strptime(dm.group(1)[:3], '%b').month; yr = int(dm.group(2))
                _result = (f'{yr}-{mon:02d}-01', val)
    except Exception:
        pass

    if not _result:
        # 源2: Trading Economics
        try:
            html = http_get('https://tradingeconomics.com/united-states/empire-state-manufacturing-index', timeout=15, use_ua=True)
            import re as _re3
            m = _re3.search(r'to\s+([+-]?[\d.]+)\s+points?\s+in\s+([A-Za-z]+)(?:\s+of\s+|\s+)(\d{4})', html)
            if m:
                val = float(m.group(1)); mon = datetime.strptime(m.group(2)[:3], '%b').month; yr = int(m.group(3))
                _result = (f'{yr}-{mon:02d}-01', val)
        except Exception:
            pass

    if _result:
        d = {dt[:7]: v for dt, v in _STATIC_EMPIRE}
        d[_result[0][:7]] = _result[1]
        data = [(k + '-01', d[k]) for k in sorted(d)][-24:]
        print(f'  [Empire] latest {_result}, fallback=False')
        return {'data': data, 'is_fallback': False, 'asof': _result[0][:7]}
    else:
        print(f'  [Empire] 所有源失败, 使用静态兜底 ({len(_STATIC_EMPIRE)} pts)')
        return {'data': list(_STATIC_EMPIRE), 'is_fallback': True, 'asof': None}

# (deprecated) 以下 fetch_ism_pmi 为旧实现, 已被 fetch_pmi 取代, 保留仅供回溯
# ---------- ISM PMI (FRED 已下架 NAPMPMI/NAPM, 从替代源抓取) ----------
def _parse_ism_csv(text):
    """解析 CSV 格式的 ISM PMI 数据为 [(date, value), ...]"""
    out = []
    try:
        rows = list(csv.reader(io.StringIO(text)))
        for r in rows[1:]:  # skip header
            if len(r) >= 2 and r[1].strip():
                try:
                    # 支持 "Jun 30, 2026" 或 "2026-06-30" 格式
                    ds = r[0].strip()
                    if ',' in ds:
                        dt = datetime.strptime(ds, '%b %d, %Y')
                        ds = dt.strftime('%Y-%m-%d')
                    elif len(ds) == 10 and ds[4] == '-':
                        pass  # already YYYY-MM-DD
                    else:
                        continue
                    out.append((ds, float(r[1])))
                except (ValueError, TypeError):
                    continue
    except Exception:
        pass
    return out

def fetch_ism_pmi():
    """
    获取 ISM 制造业 PMI 和服务业(非制造业) PMI。
    FRED 的 NAPMPMI/NAPM 已返回 404, 改用多源回退策略:
      1) ycharts.com (HTML table 解析)
      2) 静态近期数据兜底 (确保前端不空白)
    返回 {'mfg': [...], 'svc': [...]} 每个 [...] 为 [(date_str, value), ...]
    """
    result = {'mfg': [], 'svc': []}

    # 源1: ycharts.com — 有历史数据表格
    try:
        html = http_get('https://ycharts.com/indicators/us_pmi', timeout=15)
        # 提取 <td> 中的日期和数值: 模式如 "June 30, 2026" + "53.30"
        import re as _re
        # ycharts 表格每行: <td>Month Day, Year</td><td>Value</td>
        td_pairs = _re.findall(r'<td[^>]*>([^<]+)</td>\s*<td[^>]*>([\d.]+)</td>', html)
        if len(td_pairs) >= 12:  # 至少 12 个月数据才可信
            mfg = []
            for dstr, vstr in td_pairs[-36:]:  # 最近 36 个月
                try:
                    dt = datetime.strptime(dstr.strip(), '%B %d, %Y')
                    mfg.append((dt.strftime('%Y-%m-%d'), float(vstr)))
                except (ValueError, TypeError):
                    continue
            if mfg:
                result['mfg'] = mfg
                print(f'  [ISM:PMI] ycharts → {len(mfg)} pts (mfg), latest {mfg[-1]}')
    except Exception as e:
        print(f'  [ISM:PMI] ycharts 失败: {e}')

    # 源2: 服务业 PMI 也尝试从 ycharts 抓取 (不同 URL)
    if not result['svc']:
        try:
            html = http_get('https://ycharts.com/indicators/us_non_manufacturing_pmi', timeout=15)
            import re as _re
            td_pairs = _re.findall(r'<td[^>]*>([^<]+)</td>\s*<td[^>]*>([\d.]+)</td>', html)
            if len(td_pairs) >= 12:
                svc = []
                for dstr, vstr in td_pairs[-36:]:
                    try:
                        dt = datetime.strptime(dstr.strip(), '%B %d, %Y')
                        svc.append((dt.strftime('%Y-%m-%d'), float(vstr)))
                    except (ValueError, TypeError):
                        continue
                if svc:
                    result['svc'] = svc
                    print(f'  [ISM:PMI] ycharts → {len(svc)} pts (svc), latest {svc[-1]}')
        except Exception as e:
            print(f'  [ISM:PMI] ycharts svc 失败: {e}')

    # 兜底: 如果上述源全部失败, 使用静态近期数据 (手动更新, 标记来源)
    if not result['mfg']:
        # 2024-01 ~ 2026-06 的 ISM 制造业 PMI 历史值 (来源: ISM 官方发布 / Investing.com 存档)
        # 格式: (YYYY-MM-DD, value) — 日期设为每月第一个工作日
        _static_mfg = [
            ("2024-01-02",49.1),("2024-02-01",47.8),("2024-03-01",50.3),("2024-04-01",49.2),
            ("2024-05-01",48.5),("2024-06-01",48.7),("2024-07-01",46.8),("2024-08-01",47.2),
            ("2024-09-01",47.2),("2024-10-01",46.5),("2024-11-01",48.4),("2024-12-02",49.2),
            ("2025-01-07",49.3),("2025-02-03",48.4),("2025-03-03",50.3),("2025-04-01",49.0),
            ("2025-05-01",48.7),("2025-06-02",48.5),("2025-07-01",49.0),("2025-08-01",48.0),
            ("2025-09-02",48.7),("2025-10-01",49.1),("2025-11-03",48.7),("2025-12-01",48.2),
            ("2026-01-05",47.9),("2026-02-02",52.6),("2026-03-02",52.4),("2026-04-01",52.7),
            ("2026-05-01",54.0),("2026-07-01",53.3),
        ]
        result['mfg'] = _static_mfg
        print(f'  [ISM:PMI] ⚠ 使用静态兜底数据 ({len(_static_mfg)} pts, latest {_static_mfg[-1]})')

    if not result['svc']:
        _static_svc = [
            ("2024-01-03",52.0),("2024-02-02",52.6),("2024-03-01",53.4),("2024-04-01",50.4),
            ("2024-05-01",51.8),("2024-06-03",53.8),("2024-07-01",51.6),("2024-08-01",50.9),
            ("2024-09-03",54.1),("2024-10-01",56.0),("2024-11-03",55.0),("2024-12-03",53.4),
            ("2025-01-07",54.1),("2025-02-03",53.4),("2025-03-03",54.9),("2025-04-01"),
            ("2025-05-01",53.6),("2025-06-03"),("2025-07-01",52.7),("2025-08-01"),
            ("2025-09-02"),("2025-10-01"),("2025-11-03"),("2025-12-03"),
            ("2026-01-05",54.6),("2026-02-02"),("2026-03-02"),("2026-04-01"),
            ("2026-05-01"),("2026-07-01"),
        ]
        # 补全缺失值 (服务业 PMI 通常在 50-57 区间)
        _svc_full = []
        _prev = 53.0
        for i, item in enumerate(_static_svc):
            if len(item) == 2:
                _svc_full.append(item)
                _prev = item[1]
            else:
                # 用前值填充缺失
                _ds = item[0]
                _svc_full.append((_ds, _prev))
        result['svc'] = _svc_full
        print(f'  [ISM:PMI] ⚠ 服务业 PMI 使用静态兜底数据 ({len(_svc_full)} pts)')

    return result

# ---------- Yahoo ----------
def yahoo(symbol, rng='2y'):
    enc = symbol.replace('^', '%5E').replace('=', '%3D')
    last_err = None
    for host in ('query1', 'query2'):
        url = f'https://{host}.finance.yahoo.com/v8/finance/chart/{enc}?range={rng}&interval=1d'
        try:
            data = json.loads(http_get(url, use_ua=True,
                                       headers=['Accept: application/json', 'Accept-Language: en-US,en;q=0.9']))
            res = data['chart']['result'][0]
            ts = res.get('timestamp', [])
            closes = res['indicators']['quote'][0]['close']
            out = []
            for t, c in zip(ts, closes):
                if c is not None:
                    out.append((datetime.utcfromtimestamp(t).strftime('%Y-%m-%d'), float(c)))
            if out:
                return out
            last_err = 'empty series'
        except Exception as e:
            last_err = str(e)
        time.sleep(1.0)
    print(f'  [YH:{symbol}] FAIL {last_err}')
    return []


def cboe_vol(file_name):
    """CBOE 官方日度波动率历史 CSV 兜底 (VIX/GVZ/OVX)。
    FRED 已下架 VIXCLS/OVXCLS/GVZCLS, Yahoo 又常抽风, 故 CBOE 官方 CSV 作最后兜底。返回 [(date, close), ...] 或 []。"""
    url = f'https://cdn.cboe.com/api/global/us_indices/daily_prices/{file_name}'
    try:
        text = http_get(url, use_ua=True, headers=['Accept: text/csv'])
        rows = list(csv.reader(io.StringIO(text)))
        if len(rows) < 2:
            return []
        hdr = [h.strip().lower() for h in rows[0]]
        di = next((i for i, h in enumerate(hdr) if 'date' in h), -1)
        ci = next((i for i, h in enumerate(hdr) if 'close' in h), -1)
        if di < 0 or ci < 0:
            return []
        out = []
        for r in rows[1:]:
            if len(r) > max(di, ci) and r[di] and r[ci] not in ('', '.'):
                try:
                    out.append((r[di], float(r[ci])))
                except ValueError:
                    pass
        return out
    except Exception as e:
        print(f'  [CBOE:{file_name}] FAIL {e}')
        return []
        return []

# ---------- Crypto ETF 流量 (CoinGlass API, 需免费 key: coinglass.com) ----------
# 抓取 BTC / ETH 现货 ETF 日度净流量(百万美元), 失败则返回空(不阻塞管线)
def http_get_auth(url, api_key, params=None, timeout=20):
    """带 API key header 的 curl 拉取 (CoinGlass 等需 header 鉴权的源)。"""
    import urllib.parse as _up
    if params:
        url = url + ('&' if '?' in url else '?') + _up.urlencode(params)
    last_err = None
    for attempt in range(3):
        try:
            cmd = ['curl', '-s', '--max-time', str(timeout),
                   '-H', f'CG-API-KEY: {api_key}',
                   '-H', 'Accept: application/json']
            cmd.append(url)
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 15, encoding='utf-8', errors='replace')
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout
            last_err = f'curl exit {r.returncode}'
        except Exception as e:
            last_err = str(e)
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(last_err or 'unknown')

def fetch_coinglass_etf_flows(key, days=60):
    """从 CoinGlass /api/etf/{bitcoin,ethereum}/flow-history 抓取每日净流量。
    返回 {'btc':[(date,flow$M),...], 'eth':[...]} 或 None(无 key/失败)。"""
    if not key:
        print('  [ETF:CoinGlass] 未配置 COINGLASS_API_KEY, 跳过')
        return None
    base = 'https://open-api-v4.coinglass.com/api/etf'
    out = {'btc': [], 'eth': []}
    for asset, outkey in (('bitcoin', 'btc'), ('ethereum', 'eth')):
        try:
            url = f'{base}/{asset}/flow-history'
            txt = http_get_auth(url, key, params={'interval': '1d', 'limit': days}, timeout=20)
            js = json.loads(txt)
            if not js or js.get('code') != '0' or not js.get('data'):
                print(f'  [ETF:CoinGlass:{asset}] 无数据 code={js.get("code") if js else "none"}')
                continue
            rows = []
            for row in js['data']:
                ts = row.get('timestamp'); flow = row.get('flow_usd')
                if ts is None or flow is None:
                    continue
                ds = datetime.utcfromtimestamp(int(ts) / 1000).strftime('%Y-%m-%d')
                rows.append((ds, round(flow / 1e6, 1)))
            rows.sort()
            out[outkey] = rows
            if rows:
                print(f'  [ETF:CoinGlass:{asset}] → {len(rows)} 条, 最新 {rows[-1]}')
        except Exception as e:
            print(f'  [ETF:CoinGlass:{asset}] FAIL {e}')
    if not (out['btc'] or out['eth']):
        return None
    return out

# ---------- BEA 官方 API (需免费 key: apps.bea.gov/api/signup) ----------
# 提供比 FRED GDPC1 更当前的"已发布实际 GDP":
#   T10101 = 实际GDP环比年化% (Line 1 "Gross domestic product")
#   T10105 = 名义GDP水平 (十亿$, 当前$)
#   T10106 = 实际GDP水平 (十亿$, 链式2017$, 与 FRED GDPC1 同单位)
# 单位与 FRED 完全一致, 可直接覆盖 S['gdp_real']/S['gdp']
_QE = {'1': '03-31', '2': '06-30', '3': '09-30', '4': '12-31'}
def _q_end(qtr):
    """'2026Q2' -> '2026-06-30'"""
    try:
        return f'{qtr[:4]}-{_QE[qtr[5]]}'
    except Exception:
        return qtr

def fetch_bea_gdp(key, years='2024,2025,2026'):
    if not key:
        return None
    base = 'https://apps.bea.gov/api/data'
    def get(table):
        url = (f'{base}?UserID={key}&method=GetData&DatasetName=NIPA&TableName={table}'
               f'&Frequency=Q&Year={years}&ResultFormat=JSON')
        try:
            txt = http_get(url, timeout=30)
            j = json.loads(txt)
            data = j['BEAAPI']['Results']['Data']
        except Exception as e:
            print(f'  [BEA] {table} 拉取失败: {e}')
            return []
        out = []
        for row in data:
            if row.get('LineNumber') == '1' and row.get('LineDescription') == 'Gross domestic product':
                try:
                    out.append((_q_end(row['TimePeriod']), float(row['DataValue'])))
                except Exception:
                    pass
        return sorted(out)
    real_q = get('T10101')     # 实际GDP环比年化%
    nom_lv = get('T10105')     # 名义GDP水平
    real_lv = get('T10106')     # 实际GDP水平
    if not (real_lv or nom_lv or real_q):
        return None
    return {'real_qoq': real_q, 'nominal_level': nom_lv, 'real_level': real_lv}

# ---------- Atlanta Fed GDPNow (本季实时预估, 免 key) ----------
# 该站公开 JSON 端点多次变更, 这里多候选 URL + 柔性解析; 全部失败则静默跳过 (不阻塞管线)
def fetch_gdpnow():
    candidates = [
        'https://www.atlantafed.org/research/controllers/summaryofcomments.json',
        'https://www.atlantafed.org/research/controllers/gdpnowall.json',
        'https://www.atlantafed.org/api/gdpnow/',
    ]
    for url in candidates:
        try:
            txt = http_get(url, timeout=12, use_ua=True)
            j = json.loads(txt)
        except Exception:
            continue
        now = asof = qtr = None
        if isinstance(j, dict):
            now = j.get('nowcast') or j.get('value')
            asof = j.get('asofdate') or j.get('date') or j.get('asOfDate')
            qtr = j.get('forecastquarter') or j.get('quarter')
            sub = j.get('gdpnow')
            if (now is None) and isinstance(sub, list) and sub:
                now = sub[-1].get('nowcast') or sub[-1].get('value')
                asof = asof or sub[-1].get('asofdate') or sub[-1].get('date')
                qtr = qtr or sub[-1].get('quarter') or sub[-1].get('forecastquarter')
        if now is None:
            continue
        try:
            v = float(now)
        except Exception:
            continue
        d = None
        if asof:
            try: d = datetime.strptime(asof, '%Y-%m-%d').strftime('%Y-%m-%d')
            except Exception: d = None
        d = d or datetime.now().strftime('%Y-%m-%d')
        print(f'  [GDPNow] 本季预估 {v}% (截至 {asof}, {qtr or "?"})')
        return [(d, v)]
    return None

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
    'FEDFUNDS': 'ffr_eff',  # 有效联邦基金利率 (比 DFEDTARU/L 更当前, 用于目标区间回退)
    # 美联储资产负债表 (周度) — MBSST 已下架, MBS 持仓用 WSHOMCB
    'WALCL': 'walcl', 'TREAST': 'treast', 'WSHOMCB': 'mbst', 'WRESBAL': 'resbal',
    # 流动性
    'RRPONTSYD': 'rrp',
    # 信用 (ICE BofA OAS)
    'BAMLC0A0CM': 'ig', 'BAMLC0A4CBBB': 'bbb', 'BAMLH0A0HYM2': 'hy',
    'BAMLH0A1HYBB': 'bb', 'BAMLH0A2HYB': 'b', 'BAMLH0A3HYC': 'ccc',
    'BAMLC0A1CAAA': 'aaa', 'BAMLC0A2CAA': 'aa', 'BAMLC0A3CA': 'a',
    # 波动率 (VIX/OVX/GVZ 的 FRED CLS 序列已于 2014/2019 下架, 改从 Yahoo 取实时值, 见 YH_IDS)
    # 注意: VIX9D/VIX3M/SKEW 已被 FRED 下架 (CBOE 授权), 改从 Yahoo 取
    # 金融条件
    'NFCI': 'nfci',
    # 资产
    'SP500': 'spx', 'NASDAQCOM': 'ndx_comp', 'DJIA': 'dji',
    'DCOILWTICO': 'wti', 'DCOILBRENTEU': 'brent', 'DTWEXBGS': 'dxy_broad',
    'CBBTCUSD': 'btc', 'CBETHUSD': 'eth',
    # 经济
    'UNRATE': 'unrate', 'PAYEMS': 'payems', 'CPIAUCSL': 'cpi', 'CPILFESL': 'core_cpi',
    'PCEPILFE': 'core_pce', 'PCEPI': 'pce', 'GDP': 'gdp', 'GDPC1': 'gdp_real',
    'WEI': 'wei',
    'PCEC96': 'pce_real', 'RSAFS': 'retail',
    'UMCSENT': 'umich', 'ICSA': 'claims', 'DGORDER': 'durables',
    # CPI 分项 (用于通胀拆解)
    'CPIENGSL': 'cpi_energy', 'CPIUFDSL': 'cpi_food', 'CUSR0000SAH1': 'cpi_shelter',
    'CUSR0000SASLE': 'cpi_core_svcs', 'CUSR0000SACL1E': 'cpi_core_goods',
    # Phase1: 劳动力市场
    'JTSJOL': 'jolts', 'JTS3000QUR': 'quits_rate', 'CES0500000003': 'wage_yoy',
    'CIVPART': 'participation', 'CCSA': 'cont_claims',
    # Phase1: 衰退信号
    'SAHMREALTIME': 'sahm_real', 'RECPROUSM156N': 'recession_prob',
    'T10Y3M': 't10y3m', 'STLFSI4': 'stlfsi',
    # Phase1: 通胀预期
    'T5YIFR': 't5y5y', 'MICH': 'mich_infl',
    # Phase1: 住房
    'MORTGAGE30US': 'mortgage30', 'HOUST': 'housing_starts',
    'CSUSHPINSA': 'case_shiller', 'PERMITNSA': 'permits',
    # 超级核心通胀: PCE 服务除能源除住房 (链式价格指数, 月度, 2017=100)
    # 原方案用 PCESV(名义水平)+PCESH(404) 相减; 改用 BEA 官方直接序列
    'IA001260M': 'supercore',
    # 地区联储调查: 费城联储制造业扩散指数 (月度, FRED 可用)
    # 纽约联储 Empire State 制造业 FRED 无此序列, 由 fetch_empire() 单独抓取
    'GACDFSA066MSFRBPHI': 'philly',
    # Phase1: 制造业/调查
    # 注意: FRED 已下架 ISM PMI 序列 (NAPMPMI/NAPM 均 404), 改用 fetch_pmi() 从 S&P Global (Trading Economics) 获取
    'INDPRO': 'indpro',
    # Phase1: 财政
    'FYFSGDA188S': 'deficit_gdp', 'GFDEBTN': 'debt_total',
    # Phase3: 信用违约率
    'DRSFRMACBS': 'default_rate',
}
# 低频序列需要更长窗口: 季度序列 1500d (~16个季度, 支持同比); 月度序列 760d (~25个月)
QUARTERLY = {'gdp', 'gdp_real', 'deficit_gdp', 'default_rate'}
MONTHLY = {'unrate', 'payems', 'cpi', 'core_cpi', 'core_pce', 'pce', 'pce_real', 'retail',
           'umich', 'durables', 'cpi_energy', 'cpi_food', 'cpi_shelter', 'cpi_core_svcs', 'cpi_core_goods',
           'jolts', 'quits_rate', 'wage_yoy', 'participation', 'cont_claims',
           'sahm_real', 'recession_prob', 'stlfsi', 'indpro',
           'mich_infl', 'mortgage30', 'housing_starts', 'case_shiller', 'permits',
           'mfg_pmi', 'svc_pmi', 'supercore', 'philly',}
# 周度序列: WEI(实时周度经济指数) 每周六更新, 用更宽阈值避免误报"过期"
WEEKLY = {'wei', 'gdpnow'}
# 慢发布序列: PCE 系列通常滞后 ~45-60 天发布, 用更宽阈值避免误报"过期"
SLOW_RELEASE = {'core_pce', 'pce', 'pce_real'}
for fid, key in FRED_IDS.items():
    days = 1500 if key in QUARTERLY else (760 if key in MONTHLY else 380)
    S[key] = fred(fid, days=days)
    d, v = last(S[key])
    print(f'  FRED {fid:14s} → {len(S[key]):4d} pts, latest {d} = {v}')

# PMI (FRED 已下架 ISM; 改用 S&P Global 美国 PMI, 经 Trading Economics)
print('  -- PMI (S&P Global via Trading Economics) --')
_ism = fetch_pmi()
if _ism['mfg']:
    S['mfg_pmi'] = _ism['mfg']
    print(f'  S&P Global MfgPMI  → {len(S["mfg_pmi"])} pts, latest {last(S["mfg_pmi"])}')
if _ism['svc']:
    S['svc_pmi'] = _ism['svc']
    print(f'  S&P Global SvcPMI  → {len(S["svc_pmi"])} pts, latest {last(S["svc_pmi"])}')
PMI_META = {'is_fallback': _ism.get('is_fallback', False), 'asof': _ism.get('asof'), 'source': 'S&P Global (via Trading Economics)'}

# Empire State Manufacturing (NY Fed, 非 FRED 序列)
print('  -- Empire State Manufacturing (NY Fed) --')
_emp = fetch_empire()
if _emp['data']:
    S['empire'] = _emp['data']
    print(f'  Empire State → {len(S["empire"])} pts, latest {last(S["empire"])} (fallback={_emp["is_fallback"]})')
EMPIRE_META = {'is_fallback': _emp.get('is_fallback', False), 'asof': _emp.get('asof')}

print('  -- NY Fed / DTS / Yahoo --')
S['sofr'] = nyfed_sofr();      print(f'  NYFED SOFR → {len(S["sofr"])} pts, latest {last(S["sofr"])}')
S['rrp_api'] = nyfed_rrp();    print(f'  NYFED RRP → {len(S["rrp_api"])} pts, latest {last(S["rrp_api"])}')
S['srf'] = nyfed_srf();        print(f'  NYFED SRF → {len(S["srf"])} pts, latest {last(S["srf"])}')
S['tga'] = fetch_tga();        print(f'  DTS TGA → {len(S["tga"])} pts, latest {last(S["tga"])}')

YH_IDS = {
    '^NDX': 'ndx', '^RUT': 'rut', '^DJI': 'dji_yahoo', '^SOX': 'sox',
    'GC=F': 'gold', 'SI=F': 'silver',
    'NG=F': 'natgas', 'HG=F': 'copper', 'DX-Y.NYB': 'dxy', 'CL=F': 'wti_rt', 'BZ=F': 'brent_rt',
    'EURUSD=X': 'eurusd', 'GBPUSD=X': 'gbpusd', 'USDJPY=X': 'usdjpy', 'USDCNH=X': 'usdcnh',
    'TLT': 'tlt', 'IEF': 'ief', 'LQD': 'lqd', 'HYG': 'hyg', 'SPY': 'spy', 'QQQ': 'qqq',
    '^VVIX': 'vvix', '^MOVE': 'move', '^SKEW': 'skew', '^VIX3M': 'vix3m', '^VIX9D': 'vix9d',
    '^VIX': 'vix', '^OVX': 'ovx', '^GVZ': 'gvz', '^TYX': 'tyx'
}
for sym, key in YH_IDS.items():
    S[key] = yahoo(sym)
    print(f'  YH {sym:10s} → {len(S[key]):4d} pts, latest {last(S[key])}')
    time.sleep(0.4)

# 波动率三件套 (VIX/GVZ/OVX): FRED 已下架, Yahoo 是唯一实时源; 若 Yahoo 失败则用 CBOE 官方 CSV 兜底
_CBOE_FALLBACK = {'vix': 'VIX_History.csv', 'gvz': 'GVZ_History.csv', 'ovx': 'OVX_History.csv'}
for _k, _f in _CBOE_FALLBACK.items():
    if not S.get(_k):
        _cb = cboe_vol(_f)
        if _cb:
            S[_k] = _cb
            print(f'  [CBOE兜底] {_k} ← {_f} ({len(_cb)} pts, latest {_cb[-1]})')

# Crypto ETF 流量 (CoinGlass API, 需 COINGLASS_API_KEY; 无 key 则跳过, 图表显示"数据暂缺")
_etf_key = os.environ.get('COINGLASS_API_KEY')
_etf_flows = fetch_coinglass_etf_flows(_etf_key)
if _etf_flows:
    S['etf_btc_flow'] = _etf_flows['btc']
    S['etf_eth_flow'] = _etf_flows['eth']

# ETH/BTC 比率序列 (从 FRED 的 BTC/ETH 原始价格计算)
if S.get('btc') and S.get('eth'):
    _btc_dict = {d: v for d, v in S['btc']}
    _eth_dict = {d: v for d, v in S['eth']}
    _ethbtc = []
    for d in sorted(_btc_dict.keys()):
        if d in _eth_dict and _btc_dict[d] and _eth_dict[d]:
            _ethbtc.append((d, round(_eth_dict[d] / _btc_dict[d], 6)))
    if _ethbtc:
        S['eth_btc_ratio'] = _ethbtc
        print(f'  [ETH/BTC] → {len(_ethbtc)} pts, latest {_ethbtc[-1]}')

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

# BEA 官方最新实际GDP (覆盖 FRED GDPC1/GDP, 单位一致; 仅当配置了 BEA_API_KEY)
_bea = fetch_bea_gdp(os.environ.get('BEA_API_KEY'))
if _bea:
    if _bea['real_level']:
        S['gdp_real'] = _bea['real_level']
    if _bea['nominal_level']:
        S['gdp'] = _bea['nominal_level']
    _bq = _bea['real_qoq'][-1][1] if _bea['real_qoq'] else '?'
    print(f'  [BEA] 已用官方最新GDP覆盖 FRED (实际 {len(_bea["real_level"])} 季 / 名义 {len(_bea["nominal_level"])} 季, 环比年化最新 {_bq}%)')
else:
    print('  [BEA] 未配置 BEA_API_KEY, 沿用 FRED GDPC1 (可能滞后约2季度)')
# Atlanta Fed GDPNow 本季实时预估 (免 key, 端点可能失效, 失败静默跳过)
_gnow = fetch_gdpnow()

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
    # 时效性检测: 抓取失败 + 缓存回补会造成数据陈旧, 这里标记并在 CI 日志告警
    try:
        _age = (datetime.now() - datetime.strptime(d, '%Y-%m-%d')).days
    except Exception:
        _age = 0
    # 时效性阈值: 季度(250d) > 慢发布月度(60d) > 普通月度(40d) > 日度(5d)
    _max_age = 250 if key in QUARTERLY else (60 if key in SLOW_RELEASE else (40 if key in MONTHLY else (12 if key in WEEKLY else 5)))
    _stale = _age > _max_age
    R[key] = {
        'date': d, 'value': v, 'pct': percentile(series),
        'tf': tf(series, is_pct), 'series30': [round(v, 4) for _, v in series[-30:]],
        'series90': [round(v, 4) for _, v in series[-90:]],
        'unit': unit, 'digits': digits, 'stale': _stale, 'age': _age
    }
    if _stale:
        print(f'  [过期警告] {key} 最新 {d} 距今 {_age} 天 (> {_max_age}), 可能抓取失败+缓存回补')

print('\n-- 计算变化与分位 --')
# FRED 中的资产价格序列用百分比变化(与 Yahoo 资产口径一致), 利率/余额类仍用点位/绝对差
FRED_PCT_ASSETS = {'spx', 'ndx_comp', 'dji', 'wti', 'brent', 'dxy_broad', 'btc', 'eth'}
for k in FRED_IDS.values(): reg(k, S[k], is_pct=(k in FRED_PCT_ASSETS))
for k in ['sofr', 'rrp_api', 'srf', 'tga']: reg(k, S[k])
# 波动率指数用点位差(pt)而非百分比, 与 FRED 的 VIX 口径一致
YH_LEVEL = {'vvix', 'move', 'skew', 'vix9d', 'vix3m', 'vix', 'ovx', 'gvz', 'tyx'}
for k in YH_IDS.values(): reg(k, S[k], is_pct=(k not in YH_LEVEL))

# PMI (非 FRED 序列, 需单独注册)
if S.get('mfg_pmi'): reg('mfg_pmi', S['mfg_pmi'])
if S.get('svc_pmi'): reg('svc_pmi', S['svc_pmi'])
# Empire State (非 FRED 序列, 需单独注册)
if S.get('empire'): reg('empire', S['empire'])

# GDPNow 本季实时预估 (单点, 注册供卡片展示; 无数据则跳过)
if _gnow:
    reg('gdpnow', _gnow)

# Crypto 专用序列: ETH/BTC 比率 + ETF 流量
if S.get('eth_btc_ratio'):
    reg('eth_btc_ratio', S['eth_btc_ratio'])
if S.get('etf_btc_flow'):
    # ETF 流量单位已经是 $M, 用绝对差
    reg('etf_btc_flow', S['etf_btc_flow'], is_pct=False, unit='$M')
if S.get('etf_eth_flow'):
    reg('etf_eth_flow', S['etf_eth_flow'], is_pct=False, unit='$M')

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

# ================= 数据源自检 (health check) =================
# 对所有序列做新鲜度自检; 对已知主源停更/陈旧的指标, 自动切到备用源取最新数据
HEALTH = {}
def _src_of(k):
    for fid, key in FRED_IDS.items():
        if key == k: return 'FRED:' + fid
    for sym, key in YH_IDS.items():
        if key == k: return 'Yahoo:' + sym
    return {'sofr': 'NYFed:SOFR', 'rrp_api': 'NYFed:RRP', 'srf': 'NYFed:SRF',
            'tga': 'FRED:WTREGEN→DTS', 'netliq': 'derived'}.get(k, '?')

def _age_of(d):
    try: return (datetime.now() - datetime.strptime(d, '%Y-%m-%d')).days
    except Exception: return 0

for k, r in R.items():
    if r is None:
        HEALTH[k] = {'status': 'NO_DATA', 'source': _src_of(k)}
        continue
    HEALTH[k] = {'status': 'STALE' if r.get('stale') else 'OK', 'source': _src_of(k),
                 'last_date': r['date'], 'age': r.get('age'), 'value': r.get('value'),
                 'fallback': r.get('fallback', False)}

# 联邦基金目标区间: DFEDTARU/DFEDTARL 已停更(2026-01), 用更当前的有效利率 FEDFUNDS 推导目标区间
# 推导规则: 上限 = ceil(有效利率*4)/4, 下限 = 上限 - 0.25 (标准 25bp 区间)
if R.get('ffr_up') and R['ffr_up'].get('stale') and S.get('ffr_eff'):
    d_eff, eff = last(S['ffr_eff'])
    if eff is not None:
        up = ((eff * 4 + 0.999) // 1) / 4.0
        lo = up - 0.25
        for key, val in (('ffr_up', up), ('ffr_lo', lo)):
            age = _age_of(d_eff)
            R[key].update({'date': d_eff, 'value': val, 'stale': False, 'age': age, 'fallback': True})
            HEALTH[key] = {'status': 'OK(fallback→FEDFUNDS)', 'source': 'FRED:FEDFUNDS→derive',
                           'last_date': d_eff, 'age': age, 'value': val, 'fallback': True}
        print(f'  [数据源自检] 联邦基金目标区间改用 FEDFUNDS 有效利率({eff}%)推导: {lo}%-{up}%')

# BEA / GDPNow 数据源标注 (覆盖 FRED 后修正 health 的来源说明)
if _bea:
    for _k in ('gdp_real', 'gdp'):
        if _k in HEALTH:
            HEALTH[_k]['source'] = 'BEA:NIPA T10106/5 (override FRED:GDPC1/GDP)'
    HEALTH['bea_gdp'] = {'status': 'OK', 'source': 'BEA:NIPA T10101/5/6',
                         'note': f'实际 {len(_bea["real_level"])} 季 / 名义 {len(_bea["nominal_level"])} 季'}
if _gnow:
    HEALTH['gdpnow'] = {'status': 'OK', 'source': 'AtlantaFed:GDPNow',
                        'last_date': _gnow[0][0], 'value': _gnow[0][1]}

with open('data_health.json', 'w') as f:
    json.dump({'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
               'series': HEALTH}, f, indent=2, default=str)
_stale = [k for k, v in HEALTH.items() if v['status'] == 'STALE' or v['status'] == 'NO_DATA']
print(f'[数据源自检] 共 {len(HEALTH)} 个序列, 健康 {len(HEALTH)-len(_stale)}, 需关注 {len(_stale)}')
if _stale:
    print(f'[数据源自检] 需关注: {", ".join(_stale)}')

with open('computed.json', 'w') as f:
    R['generated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M')
    R['pmi_meta'] = PMI_META
    R['empire_meta'] = EMPIRE_META
    json.dump(R, f, default=str)
print(f'计算结果已存 computed.json')

# ================= Fed 事件: FOMC 官方日程 + 真实官员讲话 =================
# 美联储官方公布的 2026 / 2027 例行会议日程 (来源: federalreserve.gov, 每年初公布全年)
# sep=True 表示该次会议伴随经济展望摘要 (SEP / 点阵图)
FOMC_SCHEDULE = [
    ('2026-01-27', '2026-01-28', False, 'FOMC 会议'),
    ('2026-03-17', '2026-03-18', True,  'FOMC 会议 + SEP'),
    ('2026-04-28', '2026-04-29', False, 'FOMC 会议'),
    ('2026-06-16', '2026-06-17', True,  'FOMC 会议 + SEP'),
    ('2026-07-28', '2026-07-29', False, 'FOMC 会议'),
    ('2026-09-15', '2026-09-16', True,  'FOMC 会议 + SEP'),
    ('2026-10-27', '2026-10-28', False, 'FOMC 会议'),
    ('2026-12-08', '2026-12-09', True,  'FOMC 会议 + SEP'),
    ('2027-01-26', '2027-01-27', False, 'FOMC 会议'),
]
JACKSON_HOLE = {'start': '2026-08-27', 'end': '2026-08-29', 'chair_date': '2026-08-28',
                'label': '杰克逊霍尔年会 (主席讲话窗口)'}

# 现任联储官员姓氏 → 显示名 (讲话页 slug 仅含姓氏, 用于还原姓名)
FED_ROSTER = {
    'powell': 'Jerome H. Powell', 'wars': 'Kevin Warsh', 'jefferson': 'Philip N. Jefferson',
    'cook': 'Lisa D. Cook', 'waller': 'Christopher J. Waller', 'bowman': 'Michelle W. Bowman',
    'barr': 'Michael S. Barr', 'kugler': 'Adriana D. Kugler', 'logan': 'Lorie K. Logan',
    'goolsbee': 'Austan Goolsbee', 'daly': 'Mary C. Daly', 'bostic': 'Raphael Bostic',
    'harker': 'Patrick Harker', 'kashkari': 'Neel Kashkari', 'williams': 'John C. Williams',
    'schmid': 'Jeffrey R. Schmid', 'musalem': 'Alberto G. Musalem', 'barkin': 'Thomas Barkin',
    'collins': 'Susan M. Collins',
}
def _tone_from_title(title):
    """标题关键词语气估算 (非官方打分, 仅供参考)"""
    t = title.lower()
    hawk = sum(t.count(w) for w in ['inflation', 'disinfl', 'restrictive', 'tighten', 'higher', 'price', 'hawkish'])
    dove = sum(t.count(w) for w in ['ease', 'cut', 'soft land', 'accommodat', 'cooling', 'landing', 'employment', 'labor', 'dovish'])
    if hawk > dove: return 'hawkish'
    if dove > hawk: return 'dovish'
    return 'neutral'

def fetch_speeches(n=12):
    """抓取美联储官方讲话页真实近期讲话。返回 [{date,speaker,title,url,stance}]。失败返回 []。"""
    html = None
    for use_ua in (False, True):
        try:
            html = http_get('https://www.federalreserve.gov/newsevents/speeches.htm', use_ua=use_ua)
            if html and 'speech' in html.lower():
                break
        except Exception as e:
            print(f'  [FED:speeches] attempt(ua={use_ua}) FAIL {e}')
    if not html:
        print('  [FED:speeches] 无法获取页面'); return []
    # slug 形如 jefferson20260716a → 日期 2026-07-16 嵌在链接里, 比页面 M/D/YYYY 文本更可靠
    pat = re.compile(r'href="(/newsevents/(?:speech|testimony)/([a-z]+)(\d{8})([a-z])\.htm)"[^>]*>([^<]+)</a>', re.I)
    seen, out = set(), []
    for m in pat.finditer(html):
        full, surname, datestr, _, title = m.groups()
        if datestr + surname in seen: continue
        seen.add(datestr + surname)
        date = f'{datestr[:4]}-{datestr[4:6]}-{datestr[6:8]}'
        speaker = FED_ROSTER.get(surname.lower(), surname.title())
        out.append({'date': date, 'speaker': speaker, 'title': unescape(title).strip(),
                    'url': 'https://www.federalreserve.gov' + full, 'stance': _tone_from_title(title)})
        if len(out) >= n: break
    print(f'  [FED:speeches] → {len(out)} 条真实讲话')
    return out

def write_events():
    ev = {
        'fetched_at': datetime.now().strftime('%Y-%m-%d'),
        'fomc': [{'start': a, 'end': b, 'sep': sep, 'label': lab} for a, b, sep, lab in FOMC_SCHEDULE],
        'jackson_hole': JACKSON_HOLE,
        'speeches': fetch_speeches(),
    }
    with open('events.json', 'w') as f:
        json.dump(ev, f, ensure_ascii=False)
    print('事件数据已存 events.json')

write_events()
print('完成。下一步: 用 computed.json 重建 data.js')
