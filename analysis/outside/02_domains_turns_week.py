"""Domains actually touched in actions (commands / typed text) during outside-agent week, vs chat mentions."""
from db import con
c = con()
RX = r"(?:https?://)((?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,})"
q = f"""
with t as (select agent, created_at, coalesce(command,'') || ' ' || coalesce(action_text,'') txt
           from turns where created_at between '2026-03-23 11:17' and '2026-03-30 10:00'),
d as (select agent, created_at, unnest(regexp_extract_all(txt, '{RX}', 1)) dom from t)
select lower(dom) dom, count(*) n_actions, count(distinct agent) n_agents, min(created_at) first_seen,
       arg_min(agent, created_at) first_agent, string_agg(distinct agent, '; ') agents
from d group by 1 order by n_actions desc
"""
df = c.execute(q).df()
df.to_csv('domains_turns_week_0323.csv', index=False)
print(len(df))
print(df.head(90).drop(columns=['agents']).to_string())
