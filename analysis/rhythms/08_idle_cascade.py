"""Idle contagion test. The developer (2026-08-20 17:04 UTC) said the nudger was built because
'one agent would start ... saying it was just waiting for the end of day ... Once one agent started
doing this, all the rest would follow'.

Measure, per village day, the time each agent *stops doing computer work* for the rest of the day
(last turn), restricted to agents present until the end (have events in the last 15 min).
'Early quitters' = last turn >= 30 min before day end. Cascade signature: quit times cluster
within a day more tightly than a null that shuffles each agent's quit offset across days.
Also counts chat messages announcing end-of-day waiting.
Era A: 2025-09-01..2026-02-09 (pre-nudger, 4h/3h days). Era B: 2026-02-13..2026-03-23 (nudger, pre-perma).
"""
import numpy as np
import pandas as pd
from db import connect, OUT

con = connect()
df = con.execute("""
WITH t AS (SELECT agent_id, CAST(created_at - INTERVAL 7 HOUR AS DATE) AS d, max(created_at) AS last_turn
           FROM turns WHERE created_at BETWEEN '2025-09-01' AND '2026-03-24' GROUP BY 1, 2),
e AS (SELECT agent_id, CAST(created_at - INTERVAL 7 HOUR AS DATE) AS d, max(created_at) AS last_ev
      FROM events WHERE created_at BETWEEN '2025-09-01' AND '2026-03-24' AND agent_id IS NOT NULL
        AND action_type NOT IN ('USER_TALK','USER_NAME_CHANGE') GROUP BY 1, 2),
day AS (SELECT CAST(created_at - INTERVAL 7 HOUR AS DATE) AS d, max(created_at) AS day_end, min(created_at) AS day_start
        FROM events WHERE created_at BETWEEN '2025-09-01' AND '2026-03-24' GROUP BY 1)
SELECT e.agent_id, e.d, t.last_turn, e.last_ev, day.day_end, day.day_start
FROM e JOIN day USING (d) LEFT JOIN t USING (agent_id, d)
""").df()
df = df[(df.day_end - df.last_ev).dt.total_seconds() < 15 * 60]  # present at end of day
df["quit_min_before_end"] = (df.day_end - df.last_turn).dt.total_seconds() / 60
df = df[df.last_turn.notna()]
df["era"] = np.where(df.d < pd.Timestamp("2026-02-10"), "A pre-nudger", "B nudger")

rng = np.random.default_rng(0)
for era, g in df.groupby("era"):
    g = g[g.groupby("d").agent_id.transform("count") >= 5]
    early = (g.quit_min_before_end >= 30)
    # within-day dispersion of quit offsets (only early quitters), observed vs shuffled-null
    def disp(x):
        x = x[x.quit_min_before_end >= 30]
        return x.groupby("d").quit_min_before_end.std().dropna()
    obs = disp(g).mean()
    # share of days where >= half of present agents quit early (mass early quitting)
    frac = g.assign(early=early).groupby("d").early.mean()
    nulls, null_mass = [], []
    for _ in range(300):
        s = g.copy()
        s["quit_min_before_end"] = s.groupby("agent_id").quit_min_before_end.transform(lambda v: rng.permutation(v.values))
        nulls.append(disp(s).mean())
        null_mass.append((s.assign(early=s.quit_min_before_end >= 30).groupby("d").early.mean() >= 0.5).mean())
    print(f"{era}: days={g.d.nunique()} agent-days={len(g)} early-quit share={early.mean():.2f}")
    print(f"   within-day SD of early quit times: observed {obs:.1f} min vs shuffled {np.mean(nulls):.1f} "
          f"(p={np.mean(np.array(nulls) <= obs):.3f})")
    print(f"   days where >=50% of agents quit >=30 min early: observed {(frac >= 0.5).mean():.2f} vs shuffled {np.mean(null_mass):.2f} "
          f"(p={np.mean(np.array(null_mass) >= (frac >= 0.5).mean()):.3f})")
df.to_csv(f"{OUT}/quit_times.csv", index=False)

eod = con.execute("""
SELECT CAST(created_at - INTERVAL 7 HOUR AS DATE) AS d, count(*) AS n, count(DISTINCT speaker) AS agents
FROM chat WHERE speaker_type='agent' AND created_at BETWEEN '2025-09-01' AND '2026-03-24'
  AND regexp_matches(lower(content), '(waiting (for|until) (the )?end of (the )?(day|session)|until end of day|for the remainder of (the )?(day|session)|standing by until)')
GROUP BY 1""").df()
eod["era"] = np.where(pd.to_datetime(eod.d) < pd.Timestamp("2026-02-10"), "A", "B")
print("\n'waiting for end of day' chat messages per day:")
print(eod.groupby("era").agg(days_with=("d", "count"), msgs=("n", "sum"), mean_agents=("agents", "mean")).to_string())
