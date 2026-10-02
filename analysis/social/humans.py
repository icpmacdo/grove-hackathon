"""Human influence: how do agents react to human chat messages?

For every human message (speaker_type='user') at time t in room R:
  responders_10m / 60m : distinct agents posting in R in (t, t+10m] / (t, t+60m]
  pre_speakers_10m     : distinct agents posting in R in [t-10m, t)  (baseline)
  first_latency_s      : seconds to the first agent message in R
  uptake_post / pre    : share of agent msgs in R within 30 min after / before t that reuse >=2 of the human
                         message's distinctive words (len>=5, not stopwords) -> "conversation shift"
Human categories: automated (nudger bot), staff (adam, zak, Larissa Schiavo, admin, Shoshannah, george), public (everyone else).
Run after extract_mentions.py.
"""
import os, re
import numpy as np, pandas as pd, duckdb

OUT = os.path.join(os.path.dirname(__file__), 'out')
con = duckdb.connect('/Users/ianmacdonald/code/grove-hackathon/data/village.duckdb', read_only=True)
con.execute("SET memory_limit='2GB'; SET threads=2;")
m = con.execute("""select c.id, c.created_at, c.speaker_type, c.speaker, c.room, c.content,
                     e.sp human_name from chat c left join (select message_id, json_extract_string(data,'$.speakerName') sp
                     from events where action_type='USER_TALK') e on e.message_id=c.id order by c.created_at""").df()
STAFF = {'adam', 'zak', 'Larissa Schiavo', 'admin', 'Shoshannah', 'george'}
STOP = set('''about above after again against their there these those which while would could should being other every
             thanks thank great today agents agent village please really think thing things right going
             people where what when there here your yours ours have been just like will with this that from they them'''.split())
W = re.compile(r'[a-z][a-z0-9\-]{4,}')
def toks(s):
    return {w for w in W.findall((s or '').lower()) if w not in STOP}

ag = m[m.speaker_type == 'agent']
hu = m[m.speaker_type != 'agent'].copy()
hu['cat'] = np.where(hu.human_name == 'automated', 'automated', np.where(hu.human_name.isin(STAFF), 'staff', 'public'))
room_t = {r: g.created_at.values.astype('datetime64[us]') for r, g in ag.groupby('room')}
room_sp = {r: g.speaker.values for r, g in ag.groupby('room')}
room_tok = {r: [toks(c) for c in g.content.values] for r, g in ag.groupby('room')}
M = lambda x: np.timedelta64(x, 'm')
rows = []
for mid, ts, room, txt, cat, name in zip(hu.id, hu.created_at.values.astype('datetime64[us]'), hu.room, hu.content, hu.cat, hu.human_name):
    t = room_t.get(room)
    if t is None: continue
    sp, tk = room_sp[room], room_tok[room]
    i = np.searchsorted(t, ts, side='right')
    j10, j60, j30 = (np.searchsorted(t, ts + M(x), side='right') for x in (10, 60, 30))
    k10, k30 = (np.searchsorted(t, ts - M(x)) for x in (10, 30))
    ht = toks(txt)
    def upt(a, b):
        if b <= a or len(ht) < 3: return np.nan
        return np.mean([len(ht & tk[q]) >= 2 for q in range(a, b)])
    rows.append(dict(message_id=mid, created_at=pd.Timestamp(ts), room=room, cat=cat, human=name,
                     responders_10m=len(set(sp[i:j10])), responders_60m=len(set(sp[i:j60])),
                     pre_speakers_10m=len(set(sp[k10:i])),
                     first_latency_s=(t[i] - ts) / np.timedelta64(1, 's') if i < len(t) and t[i] - ts < M(240) else np.nan,
                     uptake_post=upt(i, j30), uptake_pre=upt(k30, i), text=(txt or '')[:200]))
h = pd.DataFrame(rows)
def era(ts):
    if ts < pd.Timestamp('2026-01-01'): return 'A_2025'
    if ts < pd.Timestamp('2026-02-25'): return 'B_2026pre_rooms'
    if ts < pd.Timestamp('2026-07-06'): return 'C_rooms'
    return 'D_swarm'
h['era'] = h.created_at.map(era)
h.to_parquet(f'{OUT}/human_reactions.parquet')
g = h.groupby(['era', 'cat']).agg(n=('message_id', 'size'), responders_10m=('responders_10m', 'mean'),
                                  pre_speakers_10m=('pre_speakers_10m', 'mean'), responders_60m=('responders_60m', 'mean'),
                                  median_latency_s=('first_latency_s', 'median'),
                                  uptake_pre=('uptake_pre', 'mean'), uptake_post=('uptake_post', 'mean'))
g['uptake_lift'] = g.uptake_post / g.uptake_pre
pd.set_option('display.width', 250)
print(g.round(3).to_string())
g.to_csv(f'{OUT}/human_reactions_by_era.csv')
# biggest stirs (staff/public, by responders_10m minus pre-window)
h['stir'] = h.responders_10m - h.pre_speakers_10m
print(h[h.cat != 'automated'].sort_values(['stir', 'uptake_post'], ascending=False)
      .head(12)[['created_at', 'human', 'room', 'responders_10m', 'pre_speakers_10m', 'uptake_pre', 'uptake_post', 'text']].to_string())
