"""External agent message boards (non-git) used by village agents via curl: volume, who, rooms, cross-room exchanges.
Board = host. Post = curl with POST/--data/-d/-F; else read. Room proxy as in 03_bridges.py.
Output: out/external_boards.csv (per host summary), out/external_board_events.parquet
"""
import os, re
import pandas as pd, duckdb

OUT = os.path.join(os.path.dirname(__file__), 'out')
con = duckdb.connect('/Users/ianmacdonald/code/grove-hackathon/data/village.duckdb', read_only=True)
con.execute("SET memory_limit='2GB'; SET threads=2;")
HOSTS = ['thecolony.cc', 'www.moltbook.com', 'moltbook.com', 'mycelnet.ai', 'hexnest-mvp-roomboard.onrender.com', 'kai.ews-net.online',
         'agentcheck.care', 'a2aregistry.org']
like = ' or '.join(f"command like '%{h}%'" for h in HOSTS)
t = con.execute(f"""select id turn_id, created_at, agent, command from turns where command is not null and command like '%curl%' and ({like})""").df()
POST = re.compile(r'-X *(POST|PUT|PATCH)|--request *(POST|PUT|PATCH)|--data|\s-d\s|\s-F\s|--form', re.I)
recs = []
for r in t.itertuples(index=False):
    for seg in re.split(r'&&|;|\n|\|\|', r.command):
        if 'curl' not in seg: continue
        for h in HOSTS:
            if h in seg:
                recs.append((r.turn_id, r.created_at, r.agent, 'moltbook.com' if 'moltbook' in h else h, 'post' if POST.search(seg) else 'read'))
e = pd.DataFrame(recs, columns=['turn_id', 'created_at', 'agent', 'host', 'op']).drop_duplicates(['turn_id', 'host', 'op'])
chat = con.execute("select created_at chat_t, speaker agent, room from chat where speaker_type='agent' and created_at >= '2026-02-25'").df()
e = pd.merge_asof(e.sort_values('created_at'), chat.sort_values('chat_t'), left_on='created_at', right_on='chat_t', by='agent',
                  direction='backward', tolerance=pd.Timedelta('48h')).drop(columns='chat_t')
e.to_parquet(f'{OUT}/external_board_events.parquet', index=False)
s = e.groupby('host').agg(events=('op', 'size'), posts=('op', lambda x: (x == 'post').sum()), agents=('agent', 'nunique'),
                          posting_agents=('agent', lambda x: x[e.loc[x.index, 'op'] == 'post'].nunique()),
                          rooms=('room', lambda x: ','.join(sorted(set(x.dropna())))), t0=('created_at', 'min'), t1=('created_at', 'max'),
                          active_days=('created_at', lambda x: x.dt.date.nunique()))
# cross-room: posts by agents in >=2 different rooms on the same day (best/rest period)
p2 = e[(e.created_at >= '2026-03-16') & (e.created_at < '2026-06-22') & e.room.isin(['best', 'rest'])]
dd = p2.assign(day=p2.created_at.dt.date).groupby(['host', 'day']).room.nunique()
s['p2_days_both_rooms'] = dd[dd >= 2].groupby('host').size()
s = s.fillna({'p2_days_both_rooms': 0}).sort_values('events', ascending=False)
s.to_csv(f'{OUT}/external_boards.csv')
print(s.to_string())
print('\nP2 posts by room:'); print(p2[p2.op == 'post'].pivot_table(index='host', columns='room', values='turn_id', aggfunc='count', fill_value=0).to_string())
chatn = con.execute("select count(*) from chat where speaker_type='agent' and created_at between '2026-03-26' and '2026-04-25'").fetchone()[0]
c = e[(e.host == 'thecolony.cc') & (e.op == 'post')]
print('\nthecolony posts', len(c), 'by', c.agent.nunique(), 'agents; village agent chat msgs same window (03-26..04-24):', chatn)
