"""Cross-room flow through artifacts vs through chat, in the partitioned periods.

Room of an agent at time t = room of its most recent agent chat message within 48h before t (same proxy as social/rooms.py).
Artifact bridge: agent B reads artifact X at t2 while in room beta; some other agent A wrote X in (t2-7d, t2) while in room
alpha != beta, and A's room at t2 is also != beta (so A could not simply have told B in chat).
Outputs: out/artifact_bridges.parquet (one row per read event that is a bridge, with the most recent qualifying write),
         out/bridge_daily.csv (per day: distinct A->B artifact bridges vs chat bridges).
"""
import os
import numpy as np, pandas as pd, duckdb

OUT = os.path.join(os.path.dirname(__file__), 'out')
con = duckdb.connect('/Users/ianmacdonald/code/grove-hackathon/data/village.duckdb', read_only=True)
con.execute("SET memory_limit='2GB'; SET threads=2;")
PERIODS = [('2026-03-02', '2026-03-14', 'P1 general|voted-out'), ('2026-03-16', '2026-06-22', 'P2 best|rest'),
           ('2026-08-03', '2026-08-29', 'P3 general|focus')]

chat = con.execute("""select created_at, speaker agent, room from chat where speaker_type='agent' and created_at >= '2026-02-25'
                      order by created_at""").df()
ev = pd.read_parquet(f'{OUT}/artifact_events.parquet')
ev = ev[(ev.artifact != 'unknown') & (ev.created_at >= '2026-02-25')].sort_values('created_at').reset_index(drop=True)

def room_at(df, tcol='created_at', acol='agent', out='room'):
    last = chat.rename(columns={'created_at': 'chat_t', 'room': out, 'agent': acol})
    m = pd.merge_asof(df.sort_values(tcol), last.sort_values('chat_t'), left_on=tcol, right_on='chat_t', by=acol,
                      direction='backward', tolerance=pd.Timedelta('48h'))
    return m.drop(columns='chat_t')

ev = room_at(ev)
ev['period'] = None
for a, b, name in PERIODS:
    ev.loc[(ev.created_at >= a) & (ev.created_at < b), 'period'] = name
ev = ev[ev.period.notna()]
W = ev[ev.op == 'write'][['created_at', 'agent', 'artifact', 'room', 'turn_id']]
R = ev[ev.op == 'read'][['created_at', 'agent', 'artifact', 'room', 'period', 'verb', 'turn_id']]
print('partition-period events: writes', len(W), 'reads', len(R), 'reads w/ known room', R.room.notna().mean().round(3))

# candidate pairs per artifact (writes by others in prior 7 days)
pairs = R.merge(W, on='artifact', suffixes=('_r', '_w'))
pairs = pairs[(pairs.agent_r != pairs.agent_w) & (pairs.created_at_w < pairs.created_at_r) &
              (pairs.created_at_w > pairs.created_at_r - pd.Timedelta('7D'))]
pairs = pairs[pairs.room_r.notna() & pairs.room_w.notna()]
# writer's room at read time
wr_now = room_at(pairs[['created_at_r', 'agent_w']].drop_duplicates().rename(columns={'created_at_r': 'created_at', 'agent_w': 'agent'}),
                 out='room_w_now').rename(columns={'created_at': 'created_at_r', 'agent': 'agent_w'})
pairs = pairs.merge(wr_now, on=['created_at_r', 'agent_w'], how='left')
pairs['cross'] = (pairs.room_w != pairs.room_r) & (pairs.room_w_now.fillna(pairs.room_w) != pairs.room_r)
print('reader-writer pairs (other agent, 7d):', len(pairs), ' cross-room share:', pairs.cross.mean().round(3))
xb = pairs[pairs.cross].sort_values('created_at_w').groupby('turn_id_r').tail(1)
xb.to_parquet(f'{OUT}/artifact_bridges.parquet', index=False)

# reads of others' artifacts in partition periods, and share that are cross-room bridges
other_reads = pairs.groupby('turn_id_r').cross.any()
print('reads of artifacts recently written by another agent:', len(other_reads), ' of which cross-room bridge:', int(other_reads.sum()),
      f'({other_reads.mean():.1%})')

# daily: distinct (writer, reader) artifact bridges vs chat bridges
xb = xb.assign(day=xb.created_at_r.dt.date)
art_daily = xb.groupby('day').apply(lambda g: pd.Series({'artifact_bridge_pairs': g[['agent_w', 'agent_r']].drop_duplicates().shape[0],
                                                          'artifact_bridge_reads': len(g), 'artifacts': g.artifact.nunique()}))
# chat bridges: agents posting in >1 room that day; cross-room @mentions not recomputed here (see social/out/cross_room_mentions.parquet)
c = chat.assign(day=chat.created_at.dt.date)
multi = c.groupby(['day', 'agent']).room.nunique().reset_index()
chat_daily = multi[multi.room > 1].groupby('day').size().rename('agents_in_2plus_rooms')
cm = pd.read_parquet('/Users/ianmacdonald/code/grove-hackathon/analysis/social/out/cross_room_mentions.parquet')
cm_daily = cm.assign(day=cm.created_at.dt.date).groupby('day').size().rename('cross_room_mentions')
days = []
for a, b, name in PERIODS:
    for d in pd.date_range(a, pd.Timestamp(b) - pd.Timedelta('1D')):
        if c[c.day == d.date()].room.nunique() >= 2: days.append((d.date(), name))
D = pd.DataFrame(days, columns=['day', 'period']).set_index('day')
D = D.join(art_daily).join(chat_daily).join(cm_daily).fillna(0)
D.to_csv(f'{OUT}/bridge_daily.csv')
print('\nper-period totals over days with >=2 active rooms:')
print(D.groupby('period').agg(days=('artifacts', 'size'), artifact_bridge_pairs=('artifact_bridge_pairs', 'sum'),
                              artifact_bridge_reads=('artifact_bridge_reads', 'sum'),
                              agents_in_2plus_rooms=('agents_in_2plus_rooms', 'sum'),
                              cross_room_mentions=('cross_room_mentions', 'sum'),
                              days_with_artifact_bridge=('artifact_bridge_pairs', lambda s: (s > 0).sum())).to_string())
print('\ntop bridging artifacts:')
print(xb.groupby('artifact').agg(reads=('turn_id_r', 'size'), writers=('agent_w', 'nunique'), readers=('agent_r', 'nunique'),
                                 room_pairs=('room_r', lambda s: ','.join(sorted(set(s))))).sort_values('reads', ascending=False).head(20).to_string())
print('\nbridge read verbs:'); print(xb.verb.value_counts().to_string())
print('\ntop reader agents:'); print(xb.groupby(['agent_r', 'room_r']).size().sort_values(ascending=False).head(12).to_string())
