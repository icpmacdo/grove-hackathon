"""Cross-room conversations inside issue threads during partition periods.
A cross-room thread exchange: agent A (room alpha) posts on thread T; later agent B (room beta != alpha, and A not in beta at
that time) reads T and then posts on T within 48h of A's post. Room proxy as in 03_bridges.py.
Output: out/thread_crossroom_exchanges.csv
"""
import os
import pandas as pd, duckdb

OUT = os.path.join(os.path.dirname(__file__), 'out')
con = duckdb.connect('/Users/ianmacdonald/code/grove-hackathon/data/village.duckdb', read_only=True)
con.execute("SET memory_limit='2GB'; SET threads=2;")
chat = con.execute("select created_at chat_t, speaker agent, room from chat where speaker_type='agent' and created_at >= '2026-02-25'").df()
te = pd.read_parquet(f'{OUT}/thread_events.parquet')
te['repo'] = te.repo.str.removeprefix('gh:')
te = te[te.created_at >= '2026-02-25'].sort_values('created_at')
te = pd.merge_asof(te, chat.sort_values('chat_t'), left_on='created_at', right_on='chat_t', by='agent', direction='backward',
                   tolerance=pd.Timedelta('48h')).drop(columns='chat_t')
P = [('2026-03-02', '2026-03-14'), ('2026-03-16', '2026-06-22'), ('2026-08-03', '2026-08-29')]
te['part'] = False
for a, b in P: te.loc[(te.created_at >= a) & (te.created_at < b), 'part'] = True
te = te[te.part & te.room.notna()]
posts = te[te.op == 'post']; reads = te[te.op == 'read']
out = []
for key, g in posts.groupby(['repo', 'kind', 'num']):
    g = g.sort_values('created_at').reset_index(drop=True)
    rd = reads[(reads.repo == key[0]) & (reads.kind == key[1]) & (reads.num == key[2])]
    for i, b in g.iterrows():
        prev = g[(g.created_at < b.created_at) & (g.created_at > b.created_at - pd.Timedelta('48h')) & (g.agent != b.agent) & (g.room != b.room)]
        if prev.empty: continue
        a = prev.iloc[-1]
        saw = rd[(rd.agent == b.agent) & (rd.created_at > a.created_at) & (rd.created_at < b.created_at)]
        out.append(dict(repo=key[0], kind=key[1], num=key[2], a_agent=a.agent, a_room=a.room, a_t=a.created_at, b_agent=b.agent,
                        b_room=b.room, b_t=b.created_at, b_read_between=len(saw) > 0, a_turn=a.turn_id, b_turn=b.turn_id))
x = pd.DataFrame(out)
x.to_csv(f'{OUT}/thread_crossroom_exchanges.csv', index=False)
print('posts in partition periods with known room:', len(posts), ' cross-room exchanges:', len(x),
      ' with read-in-between:', int(x.b_read_between.sum()) if len(x) else 0)
if len(x):
    print(x.groupby(['repo', 'num']).agg(n=('b_t', 'size'), agents=('b_agent', 'nunique'), rooms=('b_room', lambda s: ','.join(sorted(set(s)))),
                                         t0=('a_t', 'min'), t1=('b_t', 'max')).sort_values('n', ascending=False).head(15).to_string())
    print(x.sort_values('b_t').head(8).to_string())
