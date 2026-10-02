"""Does an authority signal extracted from chat recover the known leaders?

Signals per window, per agent:
  in_mention_share  : share of agent->agent mentions (at+plain) received
  requests_out      : requests issued (from delegations.parquet)
  deference_in      : messages addressed to the agent that ask for a decision/approval/direction
  lift              : deference_in share in window / share in the 4 weeks before
Run after extract_mentions.py and delegation.py.
"""
import os, re
import pandas as pd, duckdb

OUT = os.path.join(os.path.dirname(__file__), 'out')
con = duckdb.connect('/Users/ianmacdonald/code/grove-hackathon/data/village.duckdb', read_only=True)
con.execute("SET memory_limit='2GB'; SET threads=2;")
edges = pd.read_parquet(f'{OUT}/mention_edges.parquet')
edges = edges[edges.kind.isin(['at', 'plain']) & ~edges.src.str.startswith('H:')].drop_duplicates(['message_id', 'dst'])
dele = pd.read_parquet(f'{OUT}/delegations.parquet')

DEFER = (r"(should (i|we)\b|what would you like|your call|approv|permission|as (our|the|village) leader|per your|"
         r"awaiting your|your direction|your decision|you decide|green ?light|sign[- ]?off|your guidance|your instructions|"
         r"what do you want (me|us)|which should (i|we)|ready for (your|the next) (assignment|task)|reporting (in|to you))")
msgs = con.execute(f"""select id, created_at, speaker, content from chat where speaker_type='agent'
                       and regexp_matches(lower(content), '{DEFER.replace("'", "''")}')""").df()
defer = edges[edges.message_id.isin(set(msgs.id))]
print('deference-tagged messages:', len(msgs), 'deference edges:', len(defer))

EP = {
    'o3 ops-lead 2025-05-15..06-19': ('2025-05-15', '2025-06-19', 'o3'),
    'Elect-leader week 2026-01-05..12': ('2026-01-05 17:34', '2026-01-12 13:25', 'DeepSeek-V3.2'),
    'Juice Shop 2026-01-12..26 (leader-chosen goal)': ('2026-01-12 13:25', '2026-01-26', 'DeepSeek-V3.2'),
    'Follow your leader 2026-06-01..08': ('2026-06-01 15:19', '2026-06-08 09:30', 'Fine-Tuned Leader'),
    'Performance coach 2026-07-06..': ('2026-07-06 15:59', '2026-10-01', 'Claude Opus 4.8'),
}

def shares(df, a, b, col='dst'):
    w = df[(df.created_at >= a) & (df.created_at < b)]
    s = w.groupby(col).size()
    return (s / s.sum()).sort_values(ascending=False), len(w)

rows = []
for name, (a, b, L) in EP.items():
    base_a = pd.Timestamp(a) - pd.Timedelta('28D')
    ins, n_in = shares(edges, a, b)
    outr, n_r = shares(dele, a, b, 'src')
    dfs, n_d = shares(defer, a, b)
    dfs_base, _ = shares(defer, base_a, a)
    ins_base, _ = shares(edges, base_a, a)
    lift = (dfs / dfs_base.reindex(dfs.index).fillna(0.005)).sort_values(ascending=False)
    lift = lift[dfs.reindex(lift.index) >= 0.03]
    rk = lambda s: (list(s.index).index(L) + 1) if L in s.index else None
    rows.append({'episode': name, 'leader': L,
                 'in_mention rank/share': f"{rk(ins)} / {ins.get(L, 0):.1%}  (top: {ins.index[0]} {ins.iloc[0]:.1%})",
                 'requests_out rank/share': f"{rk(outr)} / {outr.get(L, 0):.1%}  (top: {outr.index[0]} {outr.iloc[0]:.1%})" if n_r else '-',
                 'deference_in rank/share': f"{rk(dfs)} / {dfs.get(L, 0):.1%}  (top: {dfs.index[0]} {dfs.iloc[0]:.1%}; n={n_d})" if n_d else '-',
                 'deference lift top3 (vs prior 4w)': ', '.join(f'{k} x{v:.1f}' for k, v in lift.head(3).items()),
                 'leader in_mention lift': f"x{ins.get(L, 0) / max(ins_base.get(L, 0), 0.005):.1f}"})
r = pd.DataFrame(rows).set_index('episode')
pd.set_option('display.width', 250); pd.set_option('display.max_colwidth', 120)
print(r.T.to_string())
r.to_csv(f'{OUT}/leader_recovery.csv')
