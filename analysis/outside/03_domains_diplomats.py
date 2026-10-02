"""Domains touched in actions by the two 'Diplomat' agents (DeepSeek-V3.2, GPT-5.6 Luna) since 2026-07-06."""
from db import con
c = con()
RX = r"(?:https?://)((?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,})"
q = f"""
with t as (select agent, created_at, coalesce(command,'') || ' ' || coalesce(action_text,'') txt
           from turns where created_at >= '2026-07-06' and agent in ('DeepSeek-V3.2','GPT-5.6 Luna')),
d as (select agent, created_at, unnest(regexp_extract_all(txt, '{RX}', 1)) dom from t)
select lower(dom) dom, count(*) n_actions, count(distinct cast(created_at as date)) n_days, min(created_at) first_seen, max(created_at) last_seen,
       string_agg(distinct agent, '; ') agents
from d group by 1 order by n_actions desc
"""
df = c.execute(q).df()
df.to_csv('domains_diplomats.csv', index=False)
print(len(df)); print(df.head(70).to_string())
print(c.execute("select agent, count(*) n, count(distinct cast(created_at as date)) days from turns where created_at>='2026-07-06' and agent in ('DeepSeek-V3.2','GPT-5.6 Luna') group by 1").df())
