"""Rooms (since 2026-02-25): do @mentions reach agents who are in another room (and so cannot see them)?

Proxy for the target's current room = room of the target's most recent chat message (within 48h before the mention).
Ack = target mentions the sender within 60 min (any room).
Run after extract_mentions.py.
"""
import os
import numpy as np, pandas as pd

OUT = os.path.join(os.path.dirname(__file__), 'out')
msgs = pd.read_parquet(f'{OUT}/messages.parquet')
edges = pd.read_parquet(f'{OUT}/mention_edges.parquet')
am = msgs[(msgs.speaker_type == 'agent') & (msgs.created_at >= '2026-02-25')].sort_values('created_at')
e = edges[(edges.kind == 'at') & (edges.created_at >= '2026-02-25') & ~edges.src.str.startswith('H:')
          & ~edges.dst.str.startswith('H:')].sort_values('created_at').copy()

# target's last room before the mention
last = am[['created_at', 'who', 'room']].rename(columns={'who': 'dst', 'room': 'dst_room', 'created_at': 'dst_last'})
e = pd.merge_asof(e, last.sort_values('dst_last'), left_on='created_at', right_on='dst_last', by='dst',
                  direction='backward', tolerance=pd.Timedelta('48h'))
e['known'] = e.dst_room.notna()
e['cross'] = e.known & (e.dst_room != e.room)

# ack: dst mentions src within 60 min
ed_all = edges[edges.kind.isin(['at', 'plain'])][['created_at', 'src', 'dst']].sort_values('created_at')
ack = []
idx = {k: g.created_at.values.astype('datetime64[us]') for k, g in ed_all.groupby(['src', 'dst'])}
for ts, s, d in zip(e.created_at.values.astype('datetime64[us]'), e.src, e.dst):
    t = idx.get((d, s))
    if t is None: ack.append(False); continue
    i = np.searchsorted(t, ts, side='right')
    ack.append(i < len(t) and t[i] <= ts + np.timedelta64(60, 'm'))
e['ack_60m'] = ack
e['era'] = np.where(e.created_at < pd.Timestamp('2026-07-06'), 'C_rooms', 'D_swarm')
e['month'] = e.created_at.dt.to_period('M')
s = e[e.known].groupby('era').agg(at_mentions=('cross', 'size'), cross_room_share=('cross', 'mean'))
s['ack_same_room'] = e[e.known & ~e.cross].groupby('era').ack_60m.mean()
s['ack_cross_room'] = e[e.cross].groupby('era').ack_60m.mean()
print(s.round(3).to_string())
print(e[e.known].groupby('month').agg(n=('cross', 'size'), cross=('cross', 'mean')).round(3).to_string())
print(e[e.cross].groupby(['room', 'dst_room']).size().sort_values(ascending=False).head(10))
e[e.cross][['message_id', 'created_at', 'src', 'dst', 'room', 'dst_room', 'ack_60m']].to_parquet(f'{OUT}/cross_room_mentions.parquet')
s.to_csv(f'{OUT}/rooms_summary.csv')
