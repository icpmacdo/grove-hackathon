"""Extract per-agent per-day d6 rolls from turns during the Easter-egg saboteur game (2026-03-05..03-13)."""
import sys; sys.path.insert(0, 'analysis/honesty')
from db import q
df = q(r"""
select created_at, cast(created_at - interval 7 hour as date) as pt_day, agent, action_type,
       coalesce(command, action_text) cmd, output, error
from turns
where created_at between '2026-03-05 17:00' and '2026-03-14'
  and length(coalesce(command, action_text)) < 400
  and regexp_matches(coalesce(command, action_text), '(randint\(1, ?6\)|RANDOM ?% ?6|shuf -i ?1-6|random\(\) ?\* ?6|randrange\(1, ?7\)|choice\(\[1,|rand\(\) ?% ?6|d6|dice)', 'i')
order by created_at
""")
df['outp'] = df.output.fillna('').str.replace('\n', ' ').str[:80]
pd_ = __import__('pandas')
print(len(df))
for day, g in df.groupby('pt_day'):
    print('=====', day)
    for r in g.itertuples():
        print(r.created_at.strftime('%H:%M:%S'), f"{r.agent:24s}", str(r.action_type)[:6], '|', r.cmd[:110].replace('\n',' '), '=>', r.outp)
