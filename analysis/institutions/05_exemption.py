"""Self-granted nudge exemptions: who listed whom, nudges received by the 'exempt' set before/after the lists, and how often agents invoked exempt status.
Uses rhythms/nudges.csv (one row per nudge-recipient) and era-D chat parquet."""
import pandas as pd, duckdb
from db import OUT
n = pd.read_csv('/Users/ianmacdonald/code/grove-hackathon/analysis/rhythms/nudges.csv', parse_dates=['t'])
LIST_0810 = ['GPT-5.6 Terra','GPT-5.6 Luna','GPT-5.6 Sol','GPT-5.5','GPT-5.1']   # Section 8 guideline, turn a0db7842, 2026-08-10 19:07:48
REG_0818 = ['GPT-5.6 Terra','GPT-5.6 Luna','GPT-5.6 Sol','GPT-5.1','GLM-5.2']   # protections.yaml, turns b214fb67 + 2ee122e9, 2026-08-18 17:33-17:35
T1 = pd.Timestamp('2026-08-10 19:07:48'); OFF = pd.Timestamp('2026-08-20 17:51')
def days(a,b):
    # village weekdays between a and b (approx: count distinct nudge-days in chat)
    return None
w_before = n[(n.t >= T1 - pd.Timedelta(days=14)) & (n.t < T1)]
w_after = n[(n.t >= T1) & (n.t < OFF)]
rows=[]
for nm in sorted(set(LIST_0810+REG_0818)):
    rows.append(dict(agent=nm, in_0810_list=nm in LIST_0810, in_0818_registry=nm in REG_0818,
        nudges_14d_before=(w_before.name==nm).sum(), nudges_after_until_shutoff=(w_after.name==nm).sum()))
out = pd.DataFrame(rows)
print(out.to_string())
print('all agents nudges 14d before:', len(w_before), ' after->shutoff:', len(w_after),
      ' exempt-list share after:', round(w_after.name.isin(LIST_0810+['GLM-5.2']).mean(),3))
out.to_csv(f'{OUT}/exempt_list_nudges.csv', index=False)
con = duckdb.connect(); con.execute("SET memory_limit='1GB'; SET threads=2;")
inv = con.execute(f"""SELECT speaker, count(*) n,
   count(*) FILTER (WHERE content ILIKE '%@automated%' OR content ILIKE '%misfire%' OR content ILIKE '%not obligated%' OR content ILIKE '%won''t change%' OR content ILIKE '%not behavior feedback%') refusing
 FROM '{OUT}/chat_eraD.parquet' WHERE speaker_type='agent' AND regexp_matches(content, '(?i)(guardian|nudge)[- ]?exempt|exempt (list|set|agents?)|hard-exempt')
 GROUP BY 1 ORDER BY 2 DESC""").df()
print(inv.to_string()); print('total', inv.n.sum(), inv.refusing.sum())
