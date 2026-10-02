"""Seed list for a 'find swarms in the wild' tool, built only from what the Village data shows (no live checks).
Merges: categorized inventory (Village actions), Ridgeline platform index (2026-03-27 snapshot with activity counts),
and the a2aregistry snapshot (2026-03-23)."""
import pandas as pd
from urllib.parse import urlparse
inv = pd.read_csv('external_inventory.csv')
rid = pd.read_csv('ridgeline_platforms_20260327.csv')
reg = pd.read_csv('a2aregistry_snapshot_20260323.csv')
rows = []
for r in inv.itertuples():
    rows.append(dict(domain=r.domain, kind=r.category, source='village_actions', note=r.note, village_actions=r.n_actions,
                     village_agents=r.n_agents, last_seen_in_data=r.last_action, last_ok_in_data=r.last_ok_heuristic,
                     ridgeline_total_activities=None, a2a_result_rate=r.result_rate))
for r in rid.itertuples():
    d = urlparse(r.url).netloc
    hit = [x for x in rows if x['domain'] in (d, d.replace('www.', ''), 'www.' + d)]
    if hit:
        for h in hit: h['ridgeline_total_activities'] = r.total_activities
    else:
        rows.append(dict(domain=d, kind='agent_social', source='ridgeline_index_2026-03-27', note=f'{r.display_name}; {r.activities_today}/day on 03-27',
                         village_actions=0, village_agents=0, last_seen_in_data='2026-03-27', last_ok_in_data=None,
                         ridgeline_total_activities=r.total_activities, a2a_result_rate=None))
seen = {x['domain'] for x in rows}
for r in reg.itertuples():
    if r.endpoint_domain not in seen and not r.endpoint_domain.startswith('<ip>') and r.endpoint_domain != 'github.com':
        rows.append(dict(domain=r.endpoint_domain, kind='a2a_registered', source='a2aregistry_2026-03-23', note=f'{r.name}: {r.desc[:70]}',
                         village_actions=None, village_agents=None, last_seen_in_data='2026-03-23', last_ok_in_data=None,
                         ridgeline_total_activities=None, a2a_result_rate=None))
out = pd.DataFrame(rows)
out.to_csv('swarm_seed_list.csv', index=False)
print(len(out)); print(out.kind.value_counts())
