"""Agent <-> artifact bipartite graph per era; hubs. Run after 01_extract_events.py.
Outputs: out/bipartite_edges.csv (era, agent, artifact, writes, reads, first, last), out/hubs_by_era.csv, prints summary.
"""
import os
import numpy as np, pandas as pd

OUT = os.path.join(os.path.dirname(__file__), 'out')
ev = pd.read_parquet(f'{OUT}/artifact_events.parquet')
ev = ev[ev.artifact != 'unknown'].copy()
bins = pd.to_datetime(['2000-01-01', '2026-01-01', '2026-02-25', '2026-07-06', '2030-01-01'])
ev['era'] = pd.cut(ev.created_at, bins, labels=['A_2025', 'B_jan-feb26', 'C_rooms', 'D_swarm'], right=False).astype(str)

e = (ev.groupby(['era', 'agent', 'artifact'])
       .agg(writes=('op', lambda s: (s == 'write').sum()), reads=('op', lambda s: (s == 'read').sum()),
            first=('created_at', 'min'), last=('created_at', 'max')).reset_index())
e.to_csv(f'{OUT}/bipartite_edges.csv', index=False)

rows = []
for era, g in e.groupby('era'):
    art = g.groupby('artifact').agg(writers=('writes', lambda s: (s > 0).sum()), touchers=('agent', 'nunique'),
                                    writes=('writes', 'sum'), reads=('reads', 'sum'))
    # readers who never wrote it in this era
    nonw = g[(g.writes == 0) & (g.reads > 0)].groupby('artifact').agg(pure_readers=('agent', 'nunique'))
    art = art.join(nonw).fillna({'pure_readers': 0})
    shared = art[(art.writers >= 2) | ((art.writers >= 1) & (art.pure_readers >= 1))]
    agents = g.agent.nunique()
    # concentration: share of all agent-artifact edges landing on top-5 artifacts by touchers
    top = art.sort_values(['touchers', 'writes'], ascending=False)
    print(f"\n=== {era}: events={int(art.writes.sum()+art.reads.sum())} writes={int(art.writes.sum())} reads={int(art.reads.sum())} "
          f"agents={agents} artifacts={len(art)} shared={len(shared)} multi-writer={int((art.writers>=2).sum())} "
          f"median touchers={art.touchers.median():.0f}")
    print(f"   artifacts touched by >= half the agents: {int((art.touchers >= agents/2).sum())}")
    print(top.head(12).to_string())
    for a, r in top.head(25).iterrows():
        rows.append(dict(era=era, artifact=a, **r.to_dict(), era_agents=agents))
pd.DataFrame(rows).to_csv(f'{OUT}/hubs_by_era.csv', index=False)

# self vs other reads: of read events, how many target an artifact the reader has never written (ever, before the read)
ev = ev.sort_values('created_at')
fw = ev[ev.op == 'write'].groupby(['agent', 'artifact']).created_at.min().rename('first_own_write')
r = ev[ev.op == 'read'].join(fw, on=['agent', 'artifact'])
r['own'] = r.first_own_write.notna() & (r.first_own_write <= r.created_at)
anyw = ev[ev.op == 'write'].groupby('artifact').agent.nunique()
r['has_writer'] = r.artifact.map(anyw).fillna(0) > 0
print('\nread events: own-artifact share by era')
print(r.groupby('era').agg(reads=('own', 'size'), own_share=('own', 'mean'), known_writer_share=('has_writer', 'mean')).round(3).to_string())
print('\nread verbs on others\' artifacts (era C+D):')
print(r[~r.own & r.has_writer & r.era.isin(['C_rooms', 'D_swarm'])].verb.value_counts().to_string())
