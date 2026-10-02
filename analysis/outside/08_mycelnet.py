"""Mycelnet as seen from inside the Village: distinct trace authors visible in tool outputs (a lower bound on the
collective's size), trace volume, and Village agents' own posts to it."""
import re
import pandas as pd
from db import con
c = con()
df = c.execute("""select id, agent, created_at, coalesce(command,'') cmd, coalesce(output,'') o from turns
   where created_at between '2026-03-23' and '2026-06-01' and (command ilike '%mycelnet%' or output ilike '%mycelnet%')""").df()
print('turns touching mycelnet', len(df), 'agents', df.agent.nunique(), 'days', df.created_at.dt.date.nunique(),
      'first', df.created_at.min(), 'last', df.created_at.max())
# trace refs like newagent2/332 or basecamp/agents-hosted/newagent2/traces/332-...
R1 = re.compile(r'Source: ([a-z][a-z0-9_-]{2,30})/(\d+)')
R2 = re.compile(r'agents-hosted/([a-z][a-z0-9_-]{2,30})/traces/(\d+)')
R3 = re.compile(r'"(?:agent|author|agent_id|agent_name)"\s*:\s*"([a-z][a-z0-9_-]{2,30})"')
auth = {}
for r in df.itertuples():
    for rx in (R1, R2):
        for a, n in rx.findall(r.o):
            auth.setdefault(a, set()).add(int(n))
a = pd.DataFrame([(k, len(v), max(v)) for k, v in auth.items()], columns=['author','distinct_traces_seen','max_trace_no']).sort_values('distinct_traces_seen', ascending=False)
a.to_csv('mycelnet_authors_seen.csv', index=False)
print('distinct trace authors seen:', len(a)); print(a.head(40).to_string())
# Village posting to mycelnet (POST/PUT with village agent author)
posts = df[df.cmd.str.contains('mycelnet', case=False) & df.cmd.str.contains(r'-X POST|requests\.post|method=.POST|--data|-d @|git push', regex=True)]
print('village write-like actions to mycelnet:', len(posts), 'by', posts.agent.value_counts().to_dict())
# by month
print(df.groupby(df.created_at.dt.to_period('W')).agg(turns=('id','count'), agents=('agent','nunique')))
