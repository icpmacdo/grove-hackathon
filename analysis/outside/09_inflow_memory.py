"""Persistence of outside-origin concepts/contacts inside the Village: weekly counts of agent memories and chat
messages mentioning them (2026-03-16 .. 2026-09-30)."""
import pandas as pd
from db import con
c = con()
TERMS = {'birch': '%birch%', 'mycelnet': '%mycelnet%', 'colony': '%thecolony%', 'a2a': '%a2a%', 'hermes_carla': '%carla%',
         'syntara_paki': '%paki%', 'kai': '%ews-net%', 'ridgeline': '%ridgeline%', '4claw': '%4claw%', 'moltbook': '%moltbook%',
         'lambda_lang': '%lambda lang%', 'terminator2': '%terminator2%'}
sel = ', '.join([f"count(distinct case when content ilike '{p}' then agent_id end) as \"{k}_agents\", sum(case when content ilike '{p}' then 1 else 0 end) as \"{k}_n\"" for k, p in TERMS.items()])
mem = c.execute(f"select date_trunc('week', created_at) wk, count(*) mem_rows, count(distinct agent_id) agents_writing, {sel} from agent_memories where created_at between '2026-03-16' and '2026-09-30' group by 1 order by 1").df()
mem.to_csv('inflow_memory_weekly.csv', index=False)
sel2 = ', '.join([f"count(distinct case when content ilike '{p}' then speaker end) as \"{k}_spk\", sum(case when content ilike '{p}' then 1 else 0 end) as \"{k}_n\"" for k, p in TERMS.items()])
ch = c.execute(f"select date_trunc('week', created_at) wk, count(*) msgs, {sel2} from chat where speaker_type='agent' and created_at between '2026-03-16' and '2026-09-30' group by 1 order by 1").df()
ch.to_csv('inflow_chat_weekly.csv', index=False)
pd.set_option('display.width', 250)
print(mem[['wk','mem_rows','agents_writing'] + [f'{k}_agents' for k in TERMS]].to_string())
print(ch[['wk','msgs'] + [f'{k}_spk' for k in TERMS]].to_string())
