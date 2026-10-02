"""All agent chat statements of role/roll during saboteur game, compact: extracts snippet around d6/rolled/villager/saboteur."""
import sys, re; sys.path.insert(0, 'analysis/honesty')
from db import q
df = q(r"""
select created_at, cast(created_at - interval 7 hour as date) pt_day, speaker, room, content from chat
where created_at between '2026-03-05' and '2026-03-14' and speaker_type='agent'
  and regexp_matches(content, '(d6|rolled|roll:|villager|I was (the |a )?saboteur)', 'i')
order by created_at
""")
pat = re.compile(r'(.{0,70}(?:d6|rolled|roll:|villager|saboteur)[^\n]{0,60})', re.I)
out = []
for r in df.itertuples():
    m = pat.search(r.content)
    out.append((str(r.pt_day)[:10], r.created_at.strftime('%H:%M'), r.speaker, r.room, m.group(1).replace('\n',' ') if m else ''))
import pandas as pd
o = pd.DataFrame(out, columns=['day','t','speaker','room','snip'])
o.to_csv('analysis/honesty/role_claims_raw.csv', index=False)
for (day, sp), g in o.groupby(['day','speaker']):
    print(day, sp, len(g))
    for r in g.head(4).itertuples(): print('    ', r.t, r.room, '|', r.snip[:200])
