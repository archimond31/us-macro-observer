import json
d = json.load(open('raw_series.json'))
print('Keys in raw_series.json:', sorted(d.keys()))
print(f'Total keys: {len(d)}')

# Check for new Phase 1 keys
new_ids = ['JTSJOL', 'JTS3000QUR', 'CES0500000008', 'CIVPART', 'CCSA',
           'SAHMREALTIME', 'T10Y3M', 'T5YIFR', 'RECPROUSM156N', 'STLFSI3',
           'USSLIND', 'MICH', 'MORTGAGE30US', 'HOUST', 'CSUSHPINSA', 'PERMITNSA',
           'NAPM', 'NAPSI', 'FYFSGDA188S', 'GFDEBTN', 'DRSFRMACBS']
print('\nPhase 1 new IDs:')
for k in new_ids:
    exists = k in d
    print(f'  {k}: {"FOUND" if exists else "MISSING"}')
