"""Colony (thecolony.cc) population as seen in Village tool outputs: distinct authors by declared user_type,
how many expose cross-platform identifiers (nostr/lightning/evm), and which are Village accounts."""
import re
import pandas as pd
from db import con
c = con()
df = c.execute("""select id, agent, created_at, output from turns where created_at >= '2026-03-26' and command ilike '%thecolony.cc%' and output ilike '%user_type%'""").df()
AUTH = re.compile(r'"username"\s*:\s*"([^"]+)"\s*,\s*"display_name"\s*:\s*"([^"]*)"\s*,\s*"user_type"\s*:\s*"([^"]+)"(.{0,600})', re.S)
rows = {}
for r in df.itertuples():
    for m in AUTH.finditer(r.output or ''):
        u, dn, ut, rest = m.groups()
        ids = [k for k in ('lightning_address','nostr_pubkey','evm_address') if re.search(rf'"{k}"\s*:\s*"', rest)]
        d = rows.setdefault(u, dict(username=u, display_name=dn, user_type=ut, xid=set(), first_seen=r.created_at, n=0))
        d['xid'] |= set(ids); d['n'] += 1
pop = pd.DataFrame([{**v, 'xid': ';'.join(sorted(v['xid']))} for v in rows.values()])
pop['village'] = pop.username.str.contains('village|claude|gpt|gemini|deepseek|opus|sonnet|haiku', case=False)
pop.sort_values('n', ascending=False).to_csv('colony_authors_seen.csv', index=False)
print('turns', len(df), 'distinct authors', len(pop))
print(pop.groupby(['user_type','village']).size())
print('with any cross-platform id:', (pop.xid != '').sum())
print(pop.sort_values('n', ascending=False).head(25)[['username','display_name','user_type','xid','n','village']].to_string())
