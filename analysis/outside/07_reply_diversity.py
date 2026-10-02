"""For A2A calls that returned a JSON-RPC result, extract the first reply text and measure how many distinct replies
each endpoint produced (canned/templated endpoints repeat; LLM-backed agents vary and echo content)."""
import re, json
import pandas as pd
from db import con
c = con()
df = c.execute("""select id, agent, created_at, command, coalesce(output,'') o from turns
  where created_at between '2026-03-23 11:17' and '2026-03-30 10:00'
  and (command ilike '%message/send%' or command ilike '%tasks/send%' or command ilike '%"jsonrpc"%')""").df()
URL = re.compile(r"https?://((?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,})")
SKIP = {'github.com','api.github.com','raw.githubusercontent.com','theaidigest.org','json-schema.org','a2aregistry.org','ai-village-agents.github.io','cdn.jsdelivr.net','www.w3.org'}
df['target'] = df.command.map(lambda cmd: next((d.lower() for d in URL.findall(cmd) if d.lower() not in SKIP), None))
df = df[df.o.str.contains(r'"result"\s*:', regex=True)]
TXT = re.compile(r'"text"\s*:\s*"((?:[^"\\]|\\.){10,400})')
def first_text(o):
    m = TXT.search(o[o.find('"result"'):])
    return m.group(1)[:200] if m else None
def norm(s):  # strip numbers/ids so 'Message received (id=57)' == '(id=58)'
    return re.sub(r'[0-9a-f]{8,}|\d+', '#', s.lower()) if isinstance(s, str) else None
df['reply'] = df.o.map(first_text); df['reply_norm'] = df.reply.map(norm)
g = df.dropna(subset=['reply']).groupby('target').agg(results=('id','count'), distinct_replies=('reply_norm','nunique'),
        example=('reply', 'first')).sort_values('results', ascending=False)
g['diversity'] = (g.distinct_replies / g.results).round(2)
g.to_csv('a2a_reply_diversity.csv')
pd.set_option('display.width', 250); pd.set_option('display.max_colwidth', 110)
print(g.head(30).to_string())
