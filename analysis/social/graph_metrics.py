"""Per-era and per-week metrics on the mention graph (needs extract_mentions.py output).

Run: uv run python analysis/social/graph_metrics.py
"""
import os, itertools
from collections import defaultdict, deque
import numpy as np, pandas as pd

OUT = os.path.join(os.path.dirname(__file__), 'out')
msgs = pd.read_parquet(f'{OUT}/messages.parquet')
edges = pd.read_parquet(f'{OUT}/mention_edges.parquet')
ag = edges[edges.kind.isin(['at', 'plain']) & ~edges.src.str.startswith('H:')]
ag = ag.drop_duplicates(['message_id', 'dst'])


def betweenness(nodes, adj):
    """Brandes, unweighted directed. adj: dict node->set(nodes)."""
    cb = dict.fromkeys(nodes, 0.0)
    for s in nodes:
        S, P, sigma, d = [], defaultdict(list), dict.fromkeys(nodes, 0), dict.fromkeys(nodes, -1)
        sigma[s], d[s] = 1, 0
        Q = deque([s])
        while Q:
            v = Q.popleft(); S.append(v)
            for w in adj.get(v, ()):
                if d[w] < 0: d[w] = d[v] + 1; Q.append(w)
                if d[w] == d[v] + 1: sigma[w] += sigma[v]; P[w].append(v)
        delta = dict.fromkeys(nodes, 0.0)
        while S:
            w = S.pop()
            for v in P[w]: delta[v] += sigma[v] / sigma[w] * (1 + delta[w])
            if w != s: cb[w] += delta[w]
    n = len(nodes)
    return {k: v / ((n - 1) * (n - 2)) for k, v in cb.items()} if n > 2 else cb


def modularity(W, part):
    """Undirected weighted modularity for symmetric matrix W (DataFrame) and partition dict."""
    A = W.values; m2 = A.sum()
    k = A.sum(1); idx = list(W.index)
    Q = 0.0
    for i, j in itertools.product(range(len(idx)), repeat=2):
        if part.get(idx[i]) == part.get(idx[j]):
            Q += A[i, j] - k[i] * k[j] / m2
    return Q / m2


def gini(x):
    x = np.sort(np.asarray(x, float)); n = len(x)
    return (2 * np.arange(1, n + 1) - n - 1).dot(x) / (n * x.sum()) if x.sum() else 0


report = []
for era, g in ag.groupby('era'):
    em = msgs[(msgs.era == era) & (msgs.speaker_type == 'agent')]
    days = em.created_at.dt.date.nunique()
    active = em.groupby('who').size(); active = active[active >= 50].index
    daily_active = em.groupby(em.created_at.dt.date)['who'].nunique().median()
    g = g[g.src.isin(active) & g.dst.isin(active)]
    W = g.groupby(['src', 'dst']).size().unstack(fill_value=0).reindex(index=active, columns=active, fill_value=0)
    tot = W.values.sum()
    recip = np.minimum(W.values, W.values.T).sum() / tot
    indeg = W.sum(0).sort_values(ascending=False)
    outdeg = W.sum(1).sort_values(ascending=False)
    # msgs per agent, to normalise: in-mentions per own message
    # strong ties: >= 1% of the era's edges or >= 10
    thr = max(10, 0.005 * tot)
    adj = {s: {d for d in active if W.at[s, d] >= thr} for s in active}
    bc = pd.Series(betweenness(list(active), adj)).sort_values(ascending=False)
    density = sum(len(v) for v in adj.values()) / (len(active) * (len(active) - 1))
    # rooms as partition: agent's majority room this era
    room_major = em.groupby('who')['room'].agg(lambda s: s.value_counts().index[0])
    Ws = W + W.T
    Q_room = modularity(Ws, room_major.to_dict()) if room_major.nunique() > 1 else float('nan')
    # mentions addressed to agents whose majority room differs from the room the message was sent in
    if era in ('C_rooms', 'D_swarm'):
        cross = (g.room != g.dst.map(room_major)).mean()
    else:
        cross = float('nan')
    msgs_per_agent = em.groupby('who').size()
    in_per_msg = (indeg / msgs_per_agent.reindex(indeg.index)).sort_values(ascending=False)
    report.append(dict(era=era, days=days, active_agents=len(active), median_daily_speakers=daily_active,
                       agent_msgs=len(em), mention_edges=int(tot),
                       mentions_per_msg=round(tot / len(em), 3),
                       reciprocity=round(recip, 3), strong_tie_density=round(density, 3),
                       in_gini=round(gini(indeg.values), 3),
                       top_in=', '.join(f'{k} {v / tot:.1%}' for k, v in indeg.head(4).items()),
                       top_out=', '.join(f'{k} {v / tot:.1%}' for k, v in outdeg.head(3).items()),
                       top_betweenness=', '.join(f'{k} {v:.2f}' for k, v in bc.head(4).items()),
                       Q_rooms=round(Q_room, 3), cross_room_mentions=round(cross, 3)))
rep = pd.DataFrame(report)
pd.set_option('display.width', 250); pd.set_option('display.max_colwidth', 200)
print(rep.T.to_string())
rep.to_csv(f'{OUT}/era_metrics.csv', index=False)

# weekly: top in-mentioned agent + concentration, plus which goal was active
ag2 = ag[~ag.dst.str.startswith('H:')].copy()
ag2['week'] = ag2.created_at.dt.to_period('W-SUN').dt.start_time
wk = ag2.groupby(['week', 'dst']).size().rename('n').reset_index()
wk['share'] = wk.n / wk.groupby('week').n.transform('sum')
top = wk.sort_values(['week', 'n'], ascending=[True, False]).groupby('week').head(2)
top = top.groupby('week').apply(lambda d: ' | '.join(f'{r.dst} {r.share:.0%}' for r in d.itertuples()), include_groups=False)
hhi = wk.groupby('week').share.apply(lambda s: (s ** 2).sum())
goal = msgs.assign(week=msgs.created_at.dt.to_period('W-SUN').dt.start_time).groupby('week').village_goal.agg(lambda s: s.value_counts().index[0] if s.notna().any() else '')
weekly = pd.DataFrame({'top2_in': top, 'hhi': hhi.round(3), 'goal': goal.str[:50]})
weekly.to_csv(f'{OUT}/weekly_hubs.csv')
print(weekly.to_string())
