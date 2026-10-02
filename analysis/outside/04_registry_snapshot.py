"""Parse the a2aregistry.org agent listing that Claude Opus 4.6 fetched on 2026-03-23 18:02:48 (turn 09a8eb1a)
into a CSV of the 50 registered agents (name, endpoint domain, short description)."""
import re
from urllib.parse import urlparse
import pandas as pd
from db import con
c = con()
out = c.execute("select output from turns where id like '09a8eb1a%'").fetchone()[0]
rows = []
for block in re.split(r'\n(?=\d+\. )', out):
    m = re.match(r'(\d+)\. (.+)', block)
    if not m: continue
    url = re.search(r'URL: (\S+)', block); wk = re.search(r'WellKnown: (\S+)', block); d = re.search(r'Desc: (.*)', block)
    rows.append(dict(rank=int(m.group(1)), name=m.group(2).strip(),
                     endpoint_domain=re.sub(r'^\d+\.\d+\.\d+\.\d+', '<ip>', urlparse(url.group(1)).netloc) if url else '',
                     wellknown_path=urlparse(wk.group(1)).path if wk else '',
                     desc=(d.group(1).strip() if d else '')[:120]))
df = pd.DataFrame(rows)
df.to_csv('a2aregistry_snapshot_20260323.csv', index=False)
print(len(df)); pd.set_option('display.width', 250); print(df.to_string())
