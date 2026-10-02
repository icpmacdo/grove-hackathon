"""How did an artifact's name reach a room? For each artifact slug (repo name), find its first mention in each room's agent
chat during the partition periods. For every room after the first one, classify the route by which the mentioning agent M
could have learned it:
  own      - M had written X (tooling) before the mention
  artifact - M had read X (tooling) in the 72h before, never wrote it, and had not posted in the origin room in 7d
  carried  - M posted in the origin room (where X was already mentioned) within the prior 7 days (agent moved rooms)
  read+carried - both of the above
  unexplained - none of these (GUI browsing, memory, search_history, humans ...)
Output: out/first_mentions.csv
"""
import os, re
import pandas as pd, duckdb

OUT = os.path.join(os.path.dirname(__file__), 'out')
con = duckdb.connect('/Users/ianmacdonald/code/grove-hackathon/data/village.duckdb', read_only=True)
con.execute("SET memory_limit='2GB'; SET threads=2;")
PERIODS = [('2026-03-02', '2026-03-14'), ('2026-03-16', '2026-06-22'), ('2026-08-03', '2026-08-29')]

ev = pd.read_parquet(f'{OUT}/artifact_events.parquet')
ev = ev[(ev.artifact != 'unknown') & (ev.created_at >= '2026-02-01')]
ev['slug'] = ev.artifact.str.split('/').str[-1]
# distinctive slugs only: contain a hyphen, >= 8 chars, map to one artifact
cnt = ev.groupby('slug').artifact.nunique()
slugs = sorted(s for s in cnt[cnt == 1].index if '-' in s and len(s) >= 8 and not s.startswith('id:'))
print('slugs', len(slugs))

res = []
for a, b in PERIODS:
    chat = con.execute(f"""select id, created_at, speaker agent, room, content from chat where speaker_type='agent'
                           and created_at >= '{a}' and created_at < '{b}' order by created_at""").df()
    tok = chat.content.str.lower().str.findall(r'[a-z0-9_]+(?:[-.][a-z0-9_]+)+')
    sl = set(slugs)
    ex = chat.assign(slug=tok.map(lambda xs: sorted(set(x for x in xs if x in sl)))).explode('slug').dropna(subset=['slug'])
    for s, hit in ex.groupby('slug'):
        if hit.room.nunique() < 2: continue
        firsts = hit.groupby('room').head(1).sort_values('created_at')
        origin = firsts.iloc[0]
        e = ev[ev.slug == s]
        for _, m in firsts.iloc[1:].iterrows():
            t, ag = m.created_at, m.agent
            mine = e[(e.agent == ag) & (e.created_at < t)]
            own = (mine.op == 'write').any()
            read = ((mine.op == 'read') & (mine.created_at > t - pd.Timedelta('72h'))).any()
            prev = chat[(chat.agent == ag) & (chat.created_at < t) & (chat.created_at > t - pd.Timedelta('7D'))]
            carried = (prev.room == origin.room).any() and origin.created_at < t
            route = 'own' if own else ('read+carried' if read and carried else 'artifact' if read else 'carried' if carried else 'unexplained')
            res.append(dict(slug=s, period=a, origin_room=origin.room, origin_t=origin.created_at, origin_agent=origin.agent,
                            room=m.room, t=t, agent=ag, msg_id=m.id, lag_h=round((t - origin.created_at).total_seconds() / 3600, 1),
                            route=route, quote=m.content[:200].replace('\n', ' ')))
df = pd.DataFrame(res)
df.to_csv(f'{OUT}/first_mentions.csv', index=False)
print(len(df), 'second-room first mentions'); print(df.route.value_counts().to_string())
print(df.groupby('period').route.value_counts().unstack(fill_value=0).to_string())
print(df.lag_h.describe().round(1).to_string())
