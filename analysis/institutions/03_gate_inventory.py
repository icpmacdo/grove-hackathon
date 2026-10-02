"""Inventory of numbered experiments/gates (psychoactive-prompt lab) in era D chat.
For each number NNN: messages mentioning 'Experiment NNN'/'Exp NNN'/'Gate NNN'/'NNN self-test' etc.; first/last, agents."""
import duckdb, re, pandas as pd
from db import OUT
con = duckdb.connect(); con.execute("SET memory_limit='1GB'; SET threads=2;")
P = f'{OUT}/chat_eraD.parquet'
df = con.execute(f"""SELECT created_at, speaker, left(id,8) id, content FROM '{P}'
  WHERE created_at >= '2026-07-06' AND speaker_type='agent'
  AND regexp_matches(content, '(?i)(experiment|exp|gate|self-test)[ -]?#?0\\d\\d|\\b0\\d\\d (self-test|replication|go/no-go|gate|baseline gate)') """).df()
rx = re.compile(r'(?i)(experiment|exp|gate|self-test)[ -]?#?(0\d\d)|\b(0\d\d) (self-test|replication|go/no-go|gate|baseline gate)')
recs = []
for r in df.itertuples():
    for m in rx.finditer(r.content):
        num = m.group(2) or m.group(3)
        kind = 'gate' if (m.group(1) or '').lower()=='gate' or (m.group(4) or '').lower() in ('gate','go/no-go','baseline gate') else 'exp'
        recs.append((num, kind, r.created_at, r.speaker, r.id))
m = pd.DataFrame(recs, columns=['num','kind','t','speaker','id']).drop_duplicates(['num','kind','id'])
g = m.groupby(['num']).agg(msgs=('id','nunique'), agents=('speaker','nunique'), first=('t','min'), last=('t','max'),
   gate_msgs=('kind', lambda s: (s=='gate').sum())).reset_index()
first_by = m.sort_values('t').groupby('num').speaker.first()
g['first_by'] = g.num.map(first_by)
g['span_days'] = (g['last']-g['first']).dt.total_seconds()/86400
g = g.sort_values('num')
g.to_csv(f'{OUT}/gate_inventory.csv', index=False)
print(g.to_string())
