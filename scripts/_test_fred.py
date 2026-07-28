"""Quick test: fetch one new FRED series to verify API works"""
import urllib.request, csv, io
from datetime import datetime, timedelta

end = datetime.now().strftime('%Y-%m-%d')
start = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')

# Test one new Phase 1 series
test_ids = ['JTSJOL', 'SAHMREALTIME', 'T10Y3M', 'T5YIFR', 'DRSFRMACBS']
for sid in test_ids:
    url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={start}&coed={end}'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': ''})
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode('utf-8')
        rows = list(csv.reader(io.StringIO(text)))
        print(f'{sid}: {len(rows)-1} rows, latest: {rows[-1] if len(rows)>1 else "EMPTY"}')
    except Exception as e:
        print(f'{sid}: ERROR - {e}')
