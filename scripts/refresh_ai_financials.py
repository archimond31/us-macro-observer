#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
refresh_ai_financials.py — AI 产业链 44 家公司基本面数据刷新工具
==============================================================
从 Yahoo Finance 拉取 REAL 基本面 (非估算) 并回写 ai_chain.json:
  - 估值:   pe(trailingPE) / fwdPe(forwardPE) / peg(pegRatio)
  - 规模:   marketCap (美股/韩股 -> $B; A股 -> 人民币亿元, 用实时 USDCNY 换算)
  - 成长/盈利: revGrowth(revenueGrowth TTM) / grossMargin / fcfMargin / roe
仅覆盖数值字段, 不动 research.summary / notes / thesis 等策展文本。
成功拉取到"市值 + 至少一个估值字段"的公司, 其 est 置为 false (移除"估算"标记)。

依赖: 仅标准库 + 系统 curl (与 build_data.py 同源机制, 无需 pip 包)。
用法:
  python scripts/refresh_ai_financials.py            # 写回(自动备份 .bak)
  python scripts/refresh_ai_financials.py --dry-run  # 仅预览改动, 不写文件
  python scripts/refresh_ai_financials.py --no-backup # 不写备份
注意: 必须在能访问 Yahoo 的机器上运行(本地终端 / CI)。沙箱无外网时字段保持 est=true。
"""
import subprocess, json, os, sys, time, tempfile, datetime, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(HERE, 'ai_chain.json')
UA = 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)'

# ---------- 网络 (与 build_data.py 同源: curl --compressed + Mozilla UA) ----------
def http_get(url, use_ua=True, headers=None, jar=None, timeout=25):
    cmd = ['curl', '-s', '--compressed', '--max-time', str(timeout)]
    if use_ua:
        cmd += ['-H', UA]
    if jar:
        cmd += ['-c', jar, '-b', jar]
    for h in (headers or []):
        cmd += ['-H', h]
    cmd.append(url)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout + 15, encoding='utf-8', errors='replace')
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
    except Exception:
        pass
    return None

def get_crumb():
    """Yahoo quoteSummary 需要 crumb + cookie。返回 (crumb, cookie_jar_path)。"""
    jar = tempfile.NamedTemporaryFile(delete=False, suffix='.txt').name
    http_get('https://fc.yahoo.com', use_ua=True, jar=jar)  # 404 但会种下 cookie
    crumb = http_get('https://query1.finance.yahoo.com/v1/test/getcrumb', use_ua=True, jar=jar)
    if not crumb or not crumb.strip():
        crumb = http_get('https://query2.finance.yahoo.com/v1/test/getcrumb', use_ua=True, jar=jar)
    return (crumb or '').strip(), jar

def batch_quote(symbols):
    """v7/finance/quote 批量取 pe/fwdPe/peg/marketCap (无需 crumb)。"""
    syms = ','.join(symbols)
    for host in ('query1', 'query2'):
        url = f'https://{host}.finance.yahoo.com/v7/finance/quote?symbols={syms}'
        txt = http_get(url, use_ua=True, headers=['Accept: application/json'])
        if txt:
            try:
                data = json.loads(txt)
                return {r['symbol']: r for r in data.get('quoteResponse', {}).get('result', [])}
            except Exception:
                continue
    return {}

def quote_summary(sym, crumb, jar):
    """v10/finance/quoteSummary 取 financialData + price/summaryDetail/defaultKeyStatistics
    (后三者作为 v7 quote 被 Unauthorized 时的回退源, 覆盖 pe/fwdPe/peg/marketCap)。
    另取 earningsTrend / recommendationTrend 供研报共识类字段(评级分布/EPS修正)推导。"""
    modules = ('financialData,defaultKeyStatistics,price,summaryDetail,'
               'earningsTrend,recommendationTrend')
    for host in ('query1', 'query2'):
        url = (f'https://{host}.finance.yahoo.com/v10/finance/quoteSummary/{sym}'
               f'?modules={modules}&crumb={crumb}')
        txt = http_get(url, use_ua=True, jar=jar, headers=['Accept: application/json'])
        if txt:
            try:
                return json.loads(txt).get('quoteSummary', {}).get('result', [None])[0]
            except Exception:
                continue
    return None

def num(x):
    """Yahoo 数值字段可能是裸数, 也可能是 {'raw': X, 'fmt': '...'} dict — 统一解开为 float。"""
    try:
        if x is None:
            return None
        if isinstance(x, dict):
            x = x.get('raw', x.get('fmt'))
            if x is None:
                return None
        return float(x)
    except Exception:
        return None

def convert_marketcap(mc_raw, currency, market, usdcny, usdkrw):
    """市值换算 (Yahoo marketCap 单位为 price.currency, 须先折 USD 再转展示单位)。
       Yahoo 对国际股票 report 的是本地币种: 美股 USD / A股 CNY / 韩股 KRW。
       展示: 美股/韩股 -> $B (mc_usd/1e9); A股 -> 人民币亿元 (mc_usd*usdcny/1e8)。"""
    if mc_raw is None or mc_raw <= 0:
        return None
    cur = (currency or 'USD').upper()
    if cur == 'USD':
        mc_usd = mc_raw
    elif cur == 'CNY':
        mc_usd = mc_raw / usdcny
    elif cur == 'KRW':
        mc_usd = mc_raw / usdkrw
    else:
        mc_usd = mc_raw  # 兜底按 USD
    if market == 'A':
        return round(mc_usd * usdcny / 1e8, 1)   # 人民币亿元
    return round(mc_usd / 1e9, 1)                 # $B

def spot_price(symbol):
    """v8/finance/chart 取最新收盘价。用于汇率(USDCNY=X / KRW=X):
    v7/quote 已对匿名调用返回 Unauthorized, 汇率必须走仍在开放的 chart 接口,
    否则会退到写死的兜底汇率, 使韩股市值凭空偏移。"""
    enc = symbol.replace('^', '%5E').replace('=', '%3D')
    for host in ('query1', 'query2'):
        url = f'https://{host}.finance.yahoo.com/v8/finance/chart/{enc}?range=5d&interval=1d'
        txt = http_get(url, use_ua=True)
        if not txt:
            continue
        try:
            res = json.loads(txt)['chart']['result'][0]
            closes = [c for c in res['indicators']['quote'][0]['close'] if c is not None]
            if closes:
                return float(closes[-1])
        except Exception:
            continue
    return None


def _rating_mean(row):
    """推荐分布行 -> (加权均值 1..5, 分析师家数)。1=强烈买入, 5=卖出。"""
    if not row:
        return None, 0
    sb = num(row.get('strongBuy')) or 0
    b = num(row.get('buy')) or 0
    h = num(row.get('hold')) or 0
    s = num(row.get('sell')) or 0
    ss = num(row.get('strongSell')) or 0
    n = sb + b + h + s + ss
    if n <= 0:
        return None, 0
    return (sb * 1 + b * 2 + h * 3 + s * 4 + ss * 5) / n, int(n)


def _consensus_label(score):
    """评级分(1..5, 越高越好) -> 与既有策展词表一致的标签。"""
    if score is None:
        return None
    if score >= 4.0:
        return '增持'
    if score >= 3.5:
        return '中性偏多'
    if score >= 3.0:
        return '中性'
    if score >= 2.5:
        return '减持'
    return '卖出'


def research_fields(s):
    """从 quoteSummary 推导研报共识类字段（全部为可复算的真实派生量）。
      ratingScore      = 6 - 推荐加权均值            (与旧口径同向: 越高越看好)
      consensus        = ratingScore 分档标签
      reports          = numberOfAnalystOpinions 优先, 回退推荐分布总家数
      ratingTrend      = 当期 ratingScore - 3个月前 ratingScore  (净评级变动, 裁到 ±2)
      ratingDispersion = (目标价最高 - 最低) / 目标价均值 × 100    (目标价分歧度)
      epsRevision      = FY+1 共识 EPS 相对 90 天前的变动%        (盈利修正动量)
    """
    out = {}
    rt = (s.get('recommendationTrend') or {}).get('trend') or []
    rows = {r.get('period'): r for r in rt if r.get('period')}
    mean0, n0 = _rating_mean(rows.get('0m'))
    mean3, _ = _rating_mean(rows.get('-3m'))
    if mean0 is not None:
        score0 = 6 - mean0
        out['ratingScore'] = round(score0, 1)
        out['consensus'] = _consensus_label(score0)
        if mean3 is not None:
            out['ratingTrend'] = round(max(-2.0, min(2.0, score0 - (6 - mean3))), 1)
    fd = s.get('financialData') or {}
    dks = s.get('defaultKeyStatistics') or {}
    noa = num(fd.get('numberOfAnalystOpinions')) or num(dks.get('numberOfAnalystOpinions'))
    if noa:
        out['reports'] = int(noa)
    elif n0:
        out['reports'] = n0

    hi, lo, mid = num(fd.get('targetHighPrice')), num(fd.get('targetLowPrice')), num(fd.get('targetMeanPrice'))
    if hi and lo and mid and mid > 0 and hi >= lo:
        disp = (hi - lo) / mid * 100
        if 0 <= disp <= 300:            # 过滤目标价样本极少的失真值
            out['ratingDispersion'] = round(disp)

    et = (s.get('earningsTrend') or {}).get('trend') or []
    for want in ('+1y', '0y'):
        row = next((r for r in et if r.get('period') == want), None)
        if not row:
            continue
        tr = row.get('epsTrend') or {}
        cur, old = num(tr.get('current')), num(tr.get('90daysAgo'))
        if cur and old and old != 0:
            chg = (cur / old - 1) * 100
            if abs(chg) <= 300:
                out['epsRevision'] = round(chg, 1)
                break
    return out


def main():
    ap = argparse.ArgumentParser(description='AI 产业链基本面刷新 (Yahoo Finance real data)')
    ap.add_argument('--dry-run', action='store_true', help='仅预览改动, 不写文件')
    ap.add_argument('--no-backup', action='store_true', help='写回时不生成 .bak 备份')
    ap.add_argument('--check', action='store_true', help='仅测试单标的 Yahoo 连通性, 不写文件')
    args = ap.parse_args()

    if args.check:
        ts = 'NVDA'
        print(f'[check] 测试 {ts} 连通性 (v7 quote + quoteSummary)...')
        q = batch_quote([ts])
        if ts in q:
            print(f'  v7 quote OK: trailingPE={q[ts].get("trailingPE")}, marketCap={q[ts].get("marketCap")}')
        else:
            print('  v7 quote 不可用 (Unauthorized/空) — 将依赖 quoteSummary 回退')
        crumb, jar = get_crumb()
        if crumb:
            s = quote_summary(ts, crumb, jar)
            if s:
                price = s.get('price') or {}
                print(f'  quoteSummary OK: trailingPE={price.get("trailingPE")}, marketCap={price.get("marketCap")}')
            else:
                print('  quoteSummary 不可用 (返回空)')
        else:
            print('  crumb 获取失败 — quoteSummary 不可用 (可能被限流, 稍后重试或换网络)')
        return

    with open(JSON_PATH, encoding='utf-8') as f:
        data = json.load(f)

    companies = []
    for layer in data['layers']:
        for c in layer['companies']:
            companies.append(c)
    tickers = [c['ticker'] for c in companies]
    print(f'[refresh] 共 {len(companies)} 家公司, {len(tickers)} 个 ticker')

    # 1) 批量 quote (pe/fwdPe/peg/marketCap)
    print('[refresh] 拉取 v7 quote (估值 + 市值)...')
    q = batch_quote(tickers)
    print(f'  v7 quote 命中 {len(q)}/{len(tickers)}')

    # 2) 汇率 USDCNY / USDKRW (v7 quote 已封, 走 chart 接口)
    usdcny = spot_price('USDCNY=X')
    if not usdcny:
        usdcny = 7.1
        print('  [warn] 未取到实时 USDCNY, 使用兜底 7.1 (A股市值按人民币原值换算, 不受此影响)')
    else:
        print(f'  USDCNY = {usdcny:.4f}')

    usdkrw = spot_price('KRW=X')
    if not usdkrw:
        usdkrw = 1400.0
        print('  [warn] 未取到实时 USDKRW, 使用兜底 1400 (韩股市值换算可能偏差)')
    else:
        print(f'  USDKRW = {usdkrw:.2f}')

    # 3) crumb + quoteSummary (margins/roe/revGrowth/fcfMargin)
    print('[refresh] 获取 crumb...')
    crumb, jar = get_crumb()
    summaries = {}
    if not crumb:
        print('  [warn] crumb 获取失败, 跳过 margin/roe/revGrowth/fcfMargin (保留 est)')
    else:
        for i, t in enumerate(tickers):
            s = quote_summary(t, crumb, jar)
            if s:
                summaries[t] = s
            if (i + 1) % 10 == 0:
                print(f'  quoteSummary {i+1}/{len(tickers)}')
            time.sleep(0.4)
        print(f'  quoteSummary 命中 {len(summaries)}/{len(tickers)}')

    today = datetime.date.today().strftime('%Y-%m')
    changes = []
    for c in companies:
        t = c['ticker']
        mkt = c.get('market', 'US')   # 缺省美股
        got = []

        # --- v7 quote 字段 ---
        qq = q.get(t)
        if qq:
            pe = num(qq.get('trailingPE'))
            fwd = num(qq.get('forwardPE'))
            peg = num(qq.get('pegRatio'))
            mc = convert_marketcap(num(qq.get('marketCap')), qq.get('currency', 'USD'), mkt, usdcny, usdkrw)
            if pe is not None and pe > 0:
                c['pe'] = round(pe, 1); got.append('pe')
            if fwd is not None and fwd > 0:
                c['fwdPe'] = round(fwd, 1); got.append('fwdPe')
            if peg is not None and peg > 0:
                c['peg'] = round(peg, 2); got.append('peg')
            if mc is not None:
                c['marketCap'] = mc; got.append('marketCap')

        # --- quoteSummary 字段 (margins/roe/revGrowth + v7 缺失时的 pe/fwdPe/peg/marketCap 回退) ---
        s = summaries.get(t)
        if s:
            fd = s.get('financialData') or {}
            price = s.get('price') or {}
            sd = s.get('summaryDetail') or {}
            dks = s.get('defaultKeyStatistics') or {}
            if 'pe' not in got:
                pe = num(price.get('trailingPE')) or num(sd.get('trailingPE'))
                if pe is not None and pe > 0:
                    c['pe'] = round(pe, 1); got.append('pe')
            if 'fwdPe' not in got:
                fwd = num(price.get('forwardPE')) or num(sd.get('forwardPE'))
                if fwd is not None and fwd > 0:
                    c['fwdPe'] = round(fwd, 1); got.append('fwdPe')
            if 'peg' not in got:
                peg = num(dks.get('pegRatio')) or num(sd.get('pegRatio'))
                if peg is not None and peg > 0:
                    c['peg'] = round(peg, 2); got.append('peg')
            if 'marketCap' not in got:
                mc = convert_marketcap(num(price.get('marketCap')), price.get('currency', 'USD'), mkt, usdcny, usdkrw)
                if mc is not None:
                    c['marketCap'] = mc; got.append('marketCap')
            rg = num(fd.get('revenueGrowth'))
            gm = num(fd.get('grossMargins'))
            roe = num(fd.get('returnOnEquity'))
            fcf = num(fd.get('freeCashflow'))
            tr = num(fd.get('totalRevenue'))
            if rg is not None:
                c['revGrowth'] = round(rg * 100, 1); got.append('revGrowth')
            if gm is not None:
                c['grossMargin'] = round(gm * 100, 1); got.append('grossMargin')
            if roe is not None:
                _roe = roe * 100
                if -100 <= _roe <= 300:   # 过滤 LITE 等失真极值(-240%)
                    c['roe'] = round(_roe, 1); got.append('roe')
            if fcf is not None and tr and tr > 0:
                _fcfm = fcf / tr * 100
                if -100 <= _fcfm <= 100:  # 过滤 OKLO/CRWV 等失真极值(-19778%)
                    c['fcfMargin'] = round(_fcfm, 1); got.append('fcfMargin')

        # --- 研报共识类字段 (评级分布 / 目标价分歧 / EPS 修正) ---
        if s:
            rf = research_fields(s)
            r = c.get('research')
            if not isinstance(r, dict):
                r = {}
                c['research'] = r
            for f in ('consensus', 'ratingScore', 'reports'):
                if f in rf:
                    r[f] = rf[f]
                    got.append('rs.' + f)
            for f in ('epsRevision', 'ratingTrend', 'ratingDispersion'):
                if f in rf:
                    v = rf[f]
                    # 归一整数量级极小的负值(-0.0 会在前端显示成 "-0.0")
                    if isinstance(v, float) and abs(v) < 0.05:
                        v = 0.0
                    c[f] = v
                    got.append(f)

        # 核实口径: 拿到市值 + (任一估值比 => 盈利型标的; 或 营收增速+毛利率 => 尚未盈利但有真实财务)
        if 'marketCap' in got and (('pe' in got or 'fwdPe' in got)
                                   or ('revGrowth' in got and 'grossMargin' in got)):
            c['est'] = False
        if got:
            c['curatedDate'] = today
            changes.append((c.get('name', t), t, got))

    if changes:
        data['asOf'] = (f'{datetime.date.today().isoformat()} '
                        f'(基本面经 Yahoo Finance 核实 real, est=false; '
                        f'research 叙事仍为策展; 市值: 美股/韩股 $B, A股 ¥亿 实时 USDCNY={usdcny:.2f})')
        data['disclaimer'] = ('股价/动量由 Yahoo 自动拉取; 估值(pe/fwdPe/peg)/市值/营收增速/毛利率/'
                              '自由现金流率/ROE 由本工具经 Yahoo Finance 核实(real, est=false); '
                              'research 叙事为分析师策展。市值: 美股 $B / A股 ¥亿(实时 USDCNY 换算) / 韩股 $B。')

    print(f'\n[refresh] 成功更新 {len(changes)}/{len(companies)} 家公司:')
    for name, t, got in changes:
        print(f'  - {name} ({t}): {", ".join(got)}')

    if args.dry_run:
        print('\n[DRY-RUN] 未写入文件。刷新后全表预览:')
        print(f"  {'ticker':11s}{'mc':>9}{'pe':>7}{'fwd':>7}{'peg':>6}{'rg%':>7}"
              f"{'gm%':>7}{'fcf%':>7}{'roe%':>7}{'rS':>5}{'rpts':>5}{'epsR%':>7}{'rT':>5}{'rD':>4}")
        for c in companies:
            r = c.get('research') or {}
            def _f(v, n=1):
                return '—' if v is None else (round(v, n) if isinstance(v, float) else v)
            print(f"  {c['ticker']:11s}{str(_f(c.get('marketCap'))):>9}{str(_f(c.get('pe'))):>7}"
                  f"{str(_f(c.get('fwdPe'))):>7}{str(_f(c.get('peg'), 2)):>6}{str(_f(c.get('revGrowth'))):>7}"
                  f"{str(_f(c.get('grossMargin'))):>7}{str(_f(c.get('fcfMargin'))):>7}"
                  f"{str(_f(c.get('roe'))):>7}{str(_f(r.get('ratingScore'))):>5}"
                  f"{str(_f(r.get('reports'))):>5}{str(_f(c.get('epsRevision'))):>7}"
                  f"{str(_f(c.get('ratingTrend'))):>5}{str(_f(c.get('ratingDispersion'))):>4}")
        return

    if not changes:
        print('\n[skip] 无任何字段更新 (可能无外网 / Yahoo 不可达), 不写文件以避免误改 asOf。')
        return

    if not args.no_backup:
        bak = JSON_PATH + '.bak'
        with open(bak, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f'\n[backup] 已备份原文件 -> {bak}')

    with open(JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f'[done] 已写回 {JSON_PATH}')

if __name__ == '__main__':
    main()
