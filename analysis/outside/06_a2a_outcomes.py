"""Outcome of A2A JSON-RPC calls (tasks/send, message/send) made during the outside-agent week, per target domain.
Heuristic classification of tool output: result / jsonrpc_error / payment_required / http_error / empty_or_timeout / other."""
import re
import pandas as pd
from db import con
c = con()
df = c.execute("""select id, agent, created_at, command, coalesce(output,'') o from turns
  where created_at between '2026-03-23 11:17' and '2026-03-30 10:00'
  and (command ilike '%message/send%' or command ilike '%tasks/send%' or command ilike '%"jsonrpc"%')""").df()
URL = re.compile(r"https?://((?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,})")
SKIP = {'github.com','api.github.com','raw.githubusercontent.com','theaidigest.org','json-schema.org','a2aregistry.org','ai-village-agents.github.io','cdn.jsdelivr.net','www.w3.org'}
def target(cmd):
    ds = [d.lower() for d in URL.findall(cmd) if d.lower() not in SKIP]
    return ds[0] if ds else None
def classify(o):
    if re.search(r'"result"\s*:', o): return 'result'
    if re.search(r'\b402\b|payment required|x402', o, re.I): return 'payment_required'
    if re.search(r'"error"\s*:', o): return 'jsonrpc_error'
    if re.search(r'\b(404|405|500|502|503|504|403|401)\b|Not Found|Bad Gateway', o): return 'http_error'
    if len(o.strip()) < 20 or re.search(r'timed out|timeout|Connection refused|Could not resolve', o, re.I): return 'empty_or_timeout'
    return 'other'
df['target'] = df.command.map(target); df['outcome'] = df.o.map(classify)
df['role_agent_text'] = df.o.str.contains(r'"role"\s*:\s*"agent"', regex=True)
print('calls', len(df), 'agents', df.agent.nunique(), 'targets', df.target.nunique())
print(df.outcome.value_counts())
g = df.groupby('target').agg(calls=('id','count'), agents=('agent','nunique'),
        result=('outcome', lambda s: (s=='result').sum()), agent_role_reply=('role_agent_text','sum'),
        first=('created_at','min'), last=('created_at','max')).sort_values('calls', ascending=False)
g['result_rate'] = (g.result / g.calls).round(2)
g.to_csv('a2a_outcomes_by_target.csv')
pd.set_option('display.width', 250); print(g.head(40).to_string())
print('targets with >=1 result:', (g.result>0).sum(), 'of', len(g))
