#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ai_curate_check.py — AI 产业链季报策展体检 / 待办清单生成器
==========================================================
只读工具：绝不修改 ai_chain.json，只产出「策展待办清单」两份文件（均在 .gitignore 内）：

    scripts/ai_curate_todo.md    人读清单（按 P0/P1/P2 分级）
    scripts/ai_curate_todo.json  机读清单（供后续脚本消费）

检查口径
--------
P0 硬财务与估值   marketCap / pe / fwdPe / peg / revGrowth / grossMargin / fcfMargin / roe / peHist5y
                  -> 可由 scripts/refresh_ai_financials.py 机械刷新（Yahoo Finance 真实值）
P1 研报共识       epsRevision / ratingTrend / ratingDispersion / research.consensus|ratingScore|reports
                  -> 同源机械刷新；research.summary 为叙事，需人工按季报复核
P2 定性字段       aiExposure / aiRevPct / aiRevGrowth / pricingPower / notes / thesis / research.summary
                  -> 季度复核即可，不做月度更新

判定规则
--------
1) 陈旧：curatedDate 距基准日的月数 > --stale-months（默认 3）-> 全部字段进待办
2) 缺失：字段不存在或为 None
3) 越界：marketCap <= 0；pe <= 0（亏损股允许缺 pe，但不允许为 0/负）；
        fcfMargin ∉ [-100,100]；roe ∉ [-100,300]（过滤一次性损益失真）
4) peHist5y 无公开数据源可机械推导 -> 永远列入 P0「需人工核对 5 年 PE 中枢」

用法
----
    python scripts/ai_curate_check.py                    # 以今天为基准日
    python scripts/ai_curate_check.py --asof 2026-11-01  # 指定基准日（确定性测试/幂等校验）
    python scripts/ai_curate_check.py --stale-months 4   # 放宽陈旧阈值
    python scripts/ai_curate_check.py --quiet            # 只写文件不打印摘要
幂等性：同一 --asof 重复运行，输出字节完全一致（无随机序、无运行时刻戳）。
"""
import json
import argparse
import datetime
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CHAIN = os.path.join(HERE, 'ai_chain.json')
COMPUTED = os.path.join(HERE, 'computed.json')
OUT_MD = os.path.join(HERE, 'ai_curate_todo.md')
OUT_JSON = os.path.join(HERE, 'ai_curate_todo.json')

P0_FIELDS = ['marketCap', 'pe', 'fwdPe', 'peg', 'revGrowth',
             'grossMargin', 'fcfMargin', 'roe', 'peHist5y']
P1_FIELDS = ['epsRevision', 'ratingTrend', 'ratingDispersion']
P2_FIELDS = ['aiExposure', 'aiRevPct', 'aiRevGrowth', 'pricingPower', 'notes']
# 注: thesis 是可选字段（当前仅少数公司有），不计入必填检查，但仍参与叙事硬编码 PE 扫描
RESEARCH_FIELDS = ['consensus', 'ratingScore', 'reports', 'summary']

FIELD_CN = {
    'marketCap': '市值', 'pe': 'PE', 'fwdPe': '远期PE', 'peg': 'PEG',
    'revGrowth': '营收增速', 'grossMargin': '毛利率', 'fcfMargin': 'FCF利润率',
    'roe': 'ROE', 'peHist5y': '5年PE中枢',
    'epsRevision': 'EPS修正', 'ratingTrend': '评级趋势', 'ratingDispersion': '评级分歧',
    'aiExposure': 'AI敞口', 'aiRevPct': 'AI收入占比', 'aiRevGrowth': 'AI收入增速',
    'pricingPower': '定价权', 'notes': '备注', 'thesis': '投资逻辑',
    'consensus': '共识标签', 'ratingScore': '评级分', 'reports': '研报数', 'summary': '研报摘要',
}


def months_between(ym, asof):
    """'YYYY-MM' -> 距 asof 的整月数；解析失败返回 None（视为陈旧）。"""
    try:
        y, m = (int(x) for x in str(ym).split('-')[:2])
    except Exception:
        return None
    return (asof.year - y) * 12 + (asof.month - m)


def is_missing(v):
    return v is None or (isinstance(v, str) and not v.strip())


def p0_reasons(c):
    """硬财务/估值问题清单。"""
    out = []
    for f in P0_FIELDS:
        v = c.get(f)
        if f == 'peHist5y':
            # 无公开机械数据源，仅检查是否缺失
            if is_missing(v) or (isinstance(v, (int, float)) and v <= 0):
                out.append(f'{FIELD_CN[f]}缺失(无机械数据源,需人工核对)')
            continue
        if is_missing(v):
            out.append(f'{FIELD_CN[f]}缺失')
            continue
        if not isinstance(v, (int, float)):
            continue
        if f == 'marketCap' and v <= 0:
            out.append('市值<=0')
        elif f == 'pe' and v <= 0:
            out.append('PE<=0(疑亏损或未更新)')
        elif f == 'fcfMargin' and not (-100 <= v <= 100):
            out.append(f'FCF利润率越界({v})')
        elif f == 'roe' and not (-100 <= v <= 300):
            out.append(f'ROE越界({v})')
    return out


def p1_reasons(c):
    out = [f'{FIELD_CN[f]}缺失' for f in P1_FIELDS if is_missing(c.get(f))]
    r = c.get('research') or {}
    for f in RESEARCH_FIELDS:
        if is_missing(r.get(f)):
            out.append(f'research.{FIELD_CN[f]}缺失')
    if not (r.get('sources') or []):
        out.append('research.sources 缺失')
    return out


def p2_reasons(c):
    out = [f'{FIELD_CN[f]}缺失' for f in P2_FIELDS if is_missing(c.get(f))]
    if c.get('est') is True:
        out.append('est=true(基本面仍标估算)')
    out.extend(pe_claim_conflicts(c))
    return out


PE_CLAIM = re.compile(r'(?:PE|市盈率)\s*[~约]?\s*(\d+(?:\.\d+)?)')


def pe_claim_conflicts(c, tol=0.20):
    """叙事里写死的 PE 数字若已与当前 pe 偏离超过 tol，提示人工核对。
    机械刷新只改数字字段，不会改 notes/thesis/summary —— 这类"文中硬编码估值"
    是刷新后最容易变成假陈述的地方。"""
    cur = c.get('pe')
    if not isinstance(cur, (int, float)) or cur <= 0:
        return []
    txts = {
        'notes': c.get('notes') or '',
        'thesis': c.get('thesis') or '',
        'research.summary': (c.get('research') or {}).get('summary') or '',
    }
    out = []
    for name, t in txts.items():
        if not t:
            continue
        for m in PE_CLAIM.finditer(t):
            try:
                v = float(m.group(1))
            except Exception:
                continue
            if v <= 0:
                continue
            dev = abs(v - cur) / cur
            if dev > tol:
                out.append(f'{name} 写死 PE≈{v:g}，当前 {cur:g}（偏离 {dev * 100:.0f}%）-> 需人工改写')
    return out


def load_computed():
    try:
        with open(COMPUTED, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser(description='AI 产业链季报策展体检（只读）')
    ap.add_argument('--asof', default=None, help='基准日 YYYY-MM-DD（默认今天）')
    ap.add_argument('--stale-months', type=int, default=3, help='陈旧阈值（月），默认 3')
    ap.add_argument('--quiet', action='store_true', help='只写文件，不打印摘要')
    args = ap.parse_args()

    asof = (datetime.date.fromisoformat(args.asof) if args.asof
            else datetime.date.today())

    with open(CHAIN, encoding='utf-8') as f:
        chain = json.load(f)
    comp = load_computed()

    items = []
    for layer in chain.get('layers', []):
        for c in layer.get('companies', []):
            t = c.get('ticker') or c.get('key') or '?'
            mo = months_between(c.get('curatedDate'), asof)
            stale = (mo is None) or (mo > args.stale_months)

            p0 = p0_reasons(c)
            p1 = p1_reasons(c)
            p2 = p2_reasons(c)
            if stale:
                scope = '全部字段(含 P0/P1/P2)'
                p0 = p0 or [f'策展已 {mo if mo is not None else "?"} 个月未刷新 -> 按最新季报重估']
                p1 = p1 or [f'策展已 {mo if mo is not None else "?"} 个月未刷新 -> 按最新季报重估']
                p2 = p2 or [f'策展已 {mo if mo is not None else "?"} 个月未刷新 -> 季度复核']
            else:
                scope = '仅异常/缺失字段'

            k = c.get('key')
            pr = comp.get(k) if k else None
            last_d = pr.get('date') if isinstance(pr, dict) else None
            tf = (pr.get('tf') or {}) if isinstance(pr, dict) else {}

            items.append({
                'ticker': t,
                'key': k,
                'name': c.get('name'),
                'layer': layer.get('name'),
                'layerId': layer.get('id'),
                'curatedDate': c.get('curatedDate'),
                'monthsOld': mo,
                'stale': stale,
                'est': c.get('est'),
                'scope': scope,
                'p0': p0,
                'p1': p1,
                'p2': p2,
                'hasPrice': last_d is not None,
                'lastPriceDate': last_d,
                'chgM': tf.get('m'),
                'chgH6': tf.get('h6'),
            })

    # 排序：先陈旧、再 P0 条数多少、最后 ticker（保证确定性）
    items.sort(key=lambda x: (not x['stale'], -len(x['p0']), x['ticker']))

    n_stale = sum(1 for i in items if i['stale'])
    n_p0 = sum(1 for i in items if i['p0'])
    n_p1 = sum(1 for i in items if i['p1'])
    n_est = sum(1 for i in items if i['est'])
    n_noprice = sum(1 for i in items if not i['hasPrice'])

    payload = {
        'asOf': asof.isoformat(),
        'staleMonths': args.stale_months,
        'chainCuratedDate': chain.get('curatedDate'),
        'chainAsOf': chain.get('asOf'),
        'layers': [{'id': l.get('id'), 'name': l.get('name'),
                    'asOf': l.get('asOf'),
                    'monthsOld': months_between((l.get('asOf') or '')[:7], asof)}
                   for l in chain.get('layers', [])],
        'counts': {
            'companies': len(items), 'stale': n_stale,
            'p0': n_p0, 'p1': n_p1, 'estTrue': n_est, 'noPrice': n_noprice,
        },
        'items': items,
    }
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # ---------- Markdown ----------
    L = []
    A = L.append
    A('# AI 产业链 · 季报策展待办清单\n')
    A(f'- 基准日：**{asof.isoformat()}**（陈旧阈值 {args.stale_months} 个月）')
    A(f'- 覆盖公司：**{len(items)}** 家 ｜ 陈旧：**{n_stale}** 家 ｜ '
      f'P0 待刷新：**{n_p0}** 家 ｜ P1 待刷新：**{n_p1}** 家')
    A(f'- 链条整体 curatedDate：`{chain.get("curatedDate")}`')
    A(f'- 行情缺失（computed.json 无该 key）：**{n_noprice}** 家 ｜ '
      f'仍标估算（est=true）：**{n_est}** 家')
    A('')
    A('> 本清单由 `scripts/ai_curate_check.py` 只读生成，不修改任何源文件。')
    A('> 机械字段刷新：`python scripts/refresh_ai_financials.py`（Yahoo Finance 真实值，后缀 `--dry-run` 可预览）。')
    A('> 定性字段（AI 敞口/定价权/notes/thesis 等）无公开数据源，必须人工按季报复核。\n')

    if n_stale == 0:
        A('## ✅ 无需季度刷新\n')
        A(f'全部公司 curatedDate 均在 {args.stale_months} 个月内，仅需处理下列残留异常项。\n')

    A('## P0 · 硬财务与估值（可机械刷新）\n')
    A('| 代码 | 公司 | 层 | 策展月 | 逾期(月) | 问题 |')
    A('|---|---|---|---|---|---|')
    for i in items:
        if i['p0']:
            A('| `{}` | {} | {} | {} | {} | {} |'.format(
                i['ticker'], i['name'], i['layer'], i['curatedDate'],
                i['monthsOld'] if i['monthsOld'] is not None else '?',
                '；'.join(i['p0'])))
    if not any(i['p0'] for i in items):
        A('| — | — | — | — | — | 无 |')
    A('')

    A('## P1 · 研报共识（可机械刷新 + 摘要需人工）\n')
    A('| 代码 | 公司 | 策展月 | 问题 |')
    A('|---|---|---|---|')
    for i in items:
        if i['p1']:
            A('| `{}` | {} | {} | {} |'.format(
                i['ticker'], i['name'], i['curatedDate'], '；'.join(i['p1'])))
    if not any(i['p1'] for i in items):
        A('| — | — | — | 无 |')
    A('')

    A('## P2 · 定性字段（季度复核）\n')
    A('| 代码 | 公司 | 策展月 | 待复核 |')
    A('|---|---|---|---|')
    for i in items:
        if i['p2']:
            A('| `{}` | {} | {} | {} |'.format(
                i['ticker'], i['name'], i['curatedDate'], '；'.join(i['p2'])))
    if not any(i['p2'] for i in items):
        A('| — | — | — | 无 |')
    A('')

    A('## 附 · 行情对齐检查\n')
    A('| 代码 | 最新价日期 | 近1月% | 近半年% |')
    A('|---|---|---|---|')
    for i in items:
        A('| `{}` | {} | {} | {} |'.format(
            i['ticker'], i['lastPriceDate'] or '**缺**',
            '—' if i['chgM'] is None else round(i['chgM'], 1),
            '—' if i['chgH6'] is None else round(i['chgH6'], 1)))
    A('')

    with open(OUT_MD, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(L))

    if not args.quiet:
        print(f'[check] 基准日 {asof.isoformat()} | {len(items)} 家 | 陈旧 {n_stale} | '
              f'P0 {n_p0} | P1 {n_p1} | est=true {n_est} | 无行情 {n_noprice}')
        print(f'[out]   {OUT_MD}')
        print(f'[out]   {OUT_JSON}')
        for i in items[:12]:
            flags = '；'.join((i['p0'] + i['p1'])[:3])
            if flags:
                print(f'  - {i["ticker"]:11s} {i["name"]}  {flags}')


if __name__ == '__main__':
    main()
