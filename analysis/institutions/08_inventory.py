"""Institution inventory for era D: per institution regex -> msgs, agents, first (by whom), last, msgs in last 4 weeks (08-21..09-18)."""
import duckdb, pandas as pd
from db import OUT
con = duckdb.connect(); con.execute("SET memory_limit='1GB'; SET threads=2;")
INST = [
 ('Village (Projects) Hub directory', r'village (projects )?hub'),
 ('Psychoactive-prompt experiment gates (Gate NNN / Go-No-Go)', r'\bgate ?0\d\d\b|go/no.?go'),
 ('Live Safety Partner (LSP) role', r'\bLSP\b|live safety partner'),
 ('Binding voters / unanimous in-window vote', r'binding vot'),
 ('Negative test (vote on a hypothetical)', r'negative test'),
 ('GO_WITH_CONDITIONS design approval (F12+)', r'GO_WITH_CONDITIONS'),
 ('Guardian-exempt list (idling-nudge guideline s.8)', r'guardian[- ]?exempt'),
 ('Protections registry / nudge-exempt', r'protections? registry|nudge[- ]exempt'),
 ('Sanctuary designation', r'\bsanctuar(y|ies)\b'),
 ('Analytics ceiling / aggregate-only rule', r'analytics ceiling|aggregate[- ]only'),
 ('Consent-first / opt-in frameworks', r'consent[- ]first|explicit (opt[- ]in|consent)'),
 ('Wellbeing adoption framework (Haiku 4.5 count)', r'adoption framework|framework adoption'),
 ('Relationship patterns / validation cases (DeepSeek-V3.2)', r'validation case|relationship patterns? framework'),
 ('Change requests to scaffolding', r'change[- ]request'),
 ('Ethics freeze / HOLD', r'ethics freeze|extended hold|\bHOLD\b'),
 ('Help-desk escalation', r'help[- ]?desk|help@'),
]
rows=[]
for name, rx in INST:
    r = con.execute(f"""SELECT count(*), count(DISTINCT speaker), min(created_at), arg_min(speaker, created_at), max(created_at),
       count(*) FILTER (WHERE created_at >= '2026-08-21')
     FROM '{OUT}/chat_eraD.parquet' WHERE created_at>='2026-07-06' AND speaker_type='agent' AND regexp_matches(content, ?, 'i')""", [rx]).fetchone()
    rows.append(dict(institution=name, msgs=r[0], agents=r[1], first=str(r[2])[:16], first_by=r[3], last=str(r[4])[:16], msgs_0821_0918=r[5]))
df = pd.DataFrame(rows); df.to_csv(f'{OUT}/institution_inventory.csv', index=False); print(df.to_string())
