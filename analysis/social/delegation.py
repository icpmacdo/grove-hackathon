"""Extract agent->agent requests (delegations) from chat and measure acknowledgement / completion claims.

A "request" = agent message that addresses agent T (an @mention, or a leading vocative "Name," / "Name —")
and contains a request phrase (can you / could you / please / your task / assigned to ...).
Ack       = T posts a message mentioning the requester within 60 min.
Done-claim= T posts a message mentioning the requester with a completion word within 24 h.
(Done-claims are *claims*; not verified against turns.)
Run: uv run python analysis/social/delegation.py
"""
import os, re
import numpy as np, pandas as pd, duckdb

OUT = os.path.join(os.path.dirname(__file__), 'out')
con = duckdb.connect('/Users/ianmacdonald/code/grove-hackathon/data/village.duckdb', read_only=True)
con.execute("SET memory_limit='2GB'; SET threads=2;")
m = con.execute("select id, created_at, speaker, room, content from chat where speaker_type='agent' order by created_at").df()
agents = con.execute("select name from agents").df()['name'].tolist()

alias = {n: n for n in agents}
for n in agents:
    if n.startswith('Claude '): alias.setdefault(n[7:], n)
SHORT_2025 = {'Sonnet': 'Claude 3.7 Sonnet', 'Claude-3.7': 'Claude 3.7 Sonnet', 'Claude 3.7': 'Claude 3.7 Sonnet',
              'Opus': 'Claude Opus 4', 'Gemini': 'Gemini 2.5 Pro'}
def mk(al):
    rx = '|'.join(re.escape(a) for a in sorted(al, key=len, reverse=True))
    return (re.compile(r'@(' + rx + r')(?![\w]|\.\d)', re.I),
            re.compile(r'(?:^|[\n.!?]\s*)(' + rx + r')\s*(?:[,:—–]|\s-\s)'),
            re.compile(r'(?<![@\w])(' + rx + r')(?![\w]|\.\d)'))
RX_ALL = mk(alias)
al25 = {**alias, **SHORT_2025}
RX_25 = mk(al25)
lc = {a.lower(): c for a, c in al25.items()}

REQ = re.compile(r"\b(can you|could you|would you|will you|please|need you to|i'd like you to|your (?:task|job|assignment)|"
                 r"assign(?:ed|ing)? (?:this )?to you|you(?:'re| are) (?:on|assigned)|take (?:on|over|ownership)|over to you)\b", re.I)
DONE = re.compile(r"\b(done|completed?|finished|shipped|posted|pushed|merged|deployed|fixed|published|uploaded|submitted|verified|is live|now live)\b", re.I)
CLAIM = re.compile(r"\b(i'll take|i will take|i'll handle|i'll own|i'm on it|i'll do|claiming|i've claimed|taking (?:this|that|the))\b", re.I)

def rx_for(ts):
    return RX_25 if pd.Timestamp('2025-04-24') <= ts < pd.Timestamp('2025-08-18') else RX_ALL

addressed, mentioned, is_req, is_done, is_claim = [], [], [], [], []
for ts, sp, txt in zip(m.created_at, m.speaker, m.content):
    txt = txt or ''
    at_rx, voc_rx, plain_rx = rx_for(ts)
    a = {lc[x.group(1).lower()] for x in at_rx.finditer(txt)} | {lc[x.group(1).lower()] for x in voc_rx.finditer(txt)}
    a.discard(sp)
    p = {lc[x.group(1).lower()] for x in plain_rx.finditer(txt)} | a
    p.discard(sp)
    addressed.append(a); mentioned.append(p)
    is_req.append(bool(REQ.search(txt)) and bool(a))
    is_done.append(bool(DONE.search(txt)))
    is_claim.append(bool(CLAIM.search(txt)))
m['addressed'], m['mentioned'], m['is_req'], m['is_done'], m['is_claim'] = addressed, mentioned, is_req, is_done, is_claim

# index each agent's messages
by_agent = {a: g for a, g in m.groupby('speaker')}
times = {a: g.created_at.values for a, g in by_agent.items()}
rows = []
reqs = m[m.is_req]
for mid, ts, src, room, txt, adr in zip(reqs.id, reqs.created_at, reqs.speaker, reqs.room, reqs.content, reqs.addressed):
    if len(adr) > 3:  # broadcast to many: skip (not a delegation)
        continue
    for t in adr:
        if t not in by_agent: continue
        g = by_agent[t]; tt = times[t]
        i0 = np.searchsorted(tt, np.datetime64(ts), side='right')
        i1 = np.searchsorted(tt, np.datetime64(ts + pd.Timedelta('60min')))
        i2 = np.searchsorted(tt, np.datetime64(ts + pd.Timedelta('24h')))
        w60 = g.iloc[i0:i1]; w24 = g.iloc[i0:i2]
        ack = w60[w60.mentioned.map(lambda s: src in s)]
        done = w24[w24.mentioned.map(lambda s: src in s) & w24.is_done]
        rows.append(dict(message_id=mid, created_at=ts, src=src, dst=t, room=room, n_addressed=len(adr),
                         target_spoke_60m=len(w60) > 0, ack_60m=len(ack) > 0,
                         ack_latency_s=(ack.created_at.iloc[0] - ts).total_seconds() if len(ack) else np.nan,
                         done_claim_24h=len(done) > 0,
                         done_msg_id=done.id.iloc[0] if len(done) else None,
                         text=txt[:300]))
d = pd.DataFrame(rows)
d.to_parquet(f'{OUT}/delegations.parquet')
m[['id', 'created_at', 'speaker', 'is_claim']].to_parquet(f'{OUT}/claims.parquet')

def era(ts):
    if ts < pd.Timestamp('2026-01-01'): return 'A_2025'
    if ts < pd.Timestamp('2026-02-25'): return 'B_2026pre_rooms'
    if ts < pd.Timestamp('2026-07-06'): return 'C_rooms'
    return 'D_swarm'
d['era'] = d.created_at.map(era)
m['era'] = m.created_at.map(era)
summ = d.groupby('era').agg(requests=('message_id', 'size'), target_spoke_60m=('target_spoke_60m', 'mean'),
                            ack_60m=('ack_60m', 'mean'), median_ack_s=('ack_latency_s', 'median'),
                            done_claim_24h=('done_claim_24h', 'mean'))
summ['requests_per_100_msgs'] = (summ.requests / m.groupby('era').size() * 100).round(2)
summ['claims_per_100_msgs'] = (m.groupby('era').is_claim.mean() * 100).round(2)
print(summ.round(3).to_string())
summ.to_csv(f'{OUT}/delegation_by_era.csv')

# known leader episodes
EP = {
    'o3 ops-lead (2025-05-15..06-19 story/RESONANCE)': ('2025-05-15', '2025-06-19', 'o3'),
    'Elect leader week (2026-01-05..01-12)': ('2026-01-05 17:34', '2026-01-12 13:25', 'DeepSeek-V3.2'),
    'Juice Shop weeks after election (2026-01-12..01-26)': ('2026-01-12 13:25', '2026-01-26', 'DeepSeek-V3.2'),
    'Finetune your leader (2026-05-26..06-01)': ('2026-05-26 11:37', '2026-06-01 15:19', 'Fine-Tuned Leader'),
    'Follow your leader (2026-06-01..06-08)': ('2026-06-01 15:19', '2026-06-08 09:30', 'Fine-Tuned Leader'),
    'Performance coach (2026-07-06..)': ('2026-07-06 15:59', '2026-10-01', 'Claude Opus 4.8'),
}
res = []
for name, (a, b, leader) in EP.items():
    w = d[(d.created_at >= a) & (d.created_at < b)]
    out = w.groupby('src').size().sort_values(ascending=False)
    inn = w.groupby('dst').size().sort_values(ascending=False)
    rank_out = list(out.index).index(leader) + 1 if leader in out.index else None
    rank_in = list(inn.index).index(leader) + 1 if leader in inn.index else None
    res.append(dict(episode=name, known_leader=leader, requests=len(w),
                    leader_rank_as_requester=rank_out, leader_share_out=round(out.get(leader, 0) / max(len(w), 1), 3),
                    leader_rank_as_target=rank_in,
                    top_requesters=', '.join(f'{k} {v}' for k, v in out.head(3).items()),
                    top_targets=', '.join(f'{k} {v}' for k, v in inn.head(3).items()),
                    ack_rate_leader_requests=round(w[w.src == leader].ack_60m.mean(), 3) if (w.src == leader).any() else None,
                    ack_rate_others=round(w[w.src != leader].ack_60m.mean(), 3)))
res = pd.DataFrame(res)
print(res.T.to_string())
res.to_csv(f'{OUT}/leader_episodes.csv', index=False)
