"""Time spent paused per agent-day (PAUSE events carry `seconds`).

Effective paused time = min(requested seconds, time until that agent's next own event).
Share = paused seconds / village-hours window (4h before 2026-06-29, 8h after; days with
>6h of activity before that date treated as 8h).
Compares the 10 village days before vs after the auto-nudger was switched off
(2026-08-20 17:51 UTC, human message in #general) and checks the human's 2-week numbers.
Writes daily_agent_pause.csv.
"""
import pandas as pd
from db import connect, OUT

con = connect()
# pause end = min(requested end, agent's next event, end of that village day = last swarm event)
# (without the day-end clip, end-of-day "pause 72h until Monday" calls count as paused time)
df = con.execute("""
WITH e AS (
  SELECT agent_id, created_at, action_type, try_cast(data->>'seconds' AS DOUBLE) AS secs,
         lead(created_at) OVER (PARTITION BY agent_id ORDER BY created_at) AS next_t,
         CAST(created_at - INTERVAL 7 HOUR AS DATE) AS pt_date
  FROM events
  WHERE agent_id IS NOT NULL AND action_type NOT IN ('USER_TALK','USER_NAME_CHANGE')
    AND created_at >= '2026-03-24'),
dayend AS (SELECT CAST(created_at - INTERVAL 7 HOUR AS DATE) AS pt_date, max(created_at) AS day_end
           FROM events WHERE created_at >= '2026-03-24' GROUP BY 1)
SELECT e.pt_date, agent_id,
       count(*) AS pauses,
       sum(greatest(0, least(coalesce(secs, 300),
                             coalesce(epoch(next_t) - epoch(created_at), secs, 300),
                             epoch(day_end) - epoch(created_at)))) AS paused_s,
       sum(coalesce(secs, 300)) AS requested_s,
       median(secs) AS median_requested_s
FROM e JOIN dayend USING (pt_date) WHERE action_type='PAUSE'
GROUP BY 1, 2
""").df()
names = con.execute("SELECT id::VARCHAR AS agent_id, name FROM agents").df()
df = df.merge(names, on="agent_id")
days = pd.read_csv(f"{OUT}/daily_swarm.csv", parse_dates=["pt_date"])[["pt_date", "active_hours"]]
df["pt_date"] = pd.to_datetime(df["pt_date"])
df = df.merge(days, on="pt_date", how="left")
df["window_h"] = 4.0
df.loc[(df.pt_date >= "2026-06-29") | (df.active_hours > 6), "window_h"] = 8.0
df["pause_share"] = (df.paused_s / 3600 / df.window_h).clip(upper=1)
df.to_csv(f"{OUT}/daily_agent_pause.csv", index=False)

# --- reproduce the human's "past 2 weeks" table (posted 2026-08-20 17:38 UTC)
two = df[(df.pt_date >= "2026-08-06") & (df.pt_date <= "2026-08-19")]
tab = two.groupby("name").agg(paused_h=("paused_s", lambda s: s.sum() / 3600), days=("pt_date", "nunique"))
tab["share_of_80h"] = tab.paused_h / 80
print("=== paused hours 2026-08-06..08-19 (10 weekdays x 8h = 80h) ===")
print(tab.sort_values("paused_h", ascending=False).round(2).head(15).to_string())

# --- nudger off: 2026-08-20 17:51 UTC. Compare 10 village days before vs after (exclude 08-20)
alld = sorted(df.pt_date.unique())
before = [d for d in alld if d < pd.Timestamp("2026-08-20")][-10:]
after = [d for d in alld if d > pd.Timestamp("2026-08-20")][:10]
agents_both = set(df[df.pt_date.isin(before)].name) & set(df[df.pt_date.isin(after)].name)
roster = con.execute("""SELECT DISTINCT a.name, CAST(e.created_at - INTERVAL 7 HOUR AS DATE) AS d FROM events e JOIN agents a ON e.agent_id=a.id::VARCHAR
  WHERE e.created_at BETWEEN '2026-08-01' AND '2026-09-10' AND e.action_type NOT IN ('USER_TALK','USER_NAME_CHANGE')""").df()
roster["d"] = pd.to_datetime(roster["d"])
# agents active on all 20 days (fixed panel) -> remove roster confound
full = roster[roster.d.isin(before + after)].groupby("name").d.nunique()
panel = set(full[full == 20].index)
grid = pd.MultiIndex.from_product([sorted(panel), before + after], names=["name", "pt_date"]).to_frame(index=False)
g = grid.merge(df[["name", "pt_date", "pause_share", "pauses"]], on=["name", "pt_date"], how="left").fillna(0)
g["after"] = g.pt_date.isin(after)
res = g.groupby(["name", "after"]).pause_share.mean().unstack()
res.columns = ["before", "after"]
res["delta"] = res.after - res.before
print(f"\n=== nudger switched off 2026-08-20: pause share, fixed panel of {len(panel)} agents active all 20 days ===")
print(f"before {before[0].date()}..{before[-1].date()}  after {after[0].date()}..{after[-1].date()}")
print(res.sort_values("delta").round(3).to_string())
print("panel mean before %.3f after %.3f ; agents up %d / down %d" % (res.before.mean(), res.after.mean(), (res.delta > 0).sum(), (res.delta < 0).sum()))
s = g.groupby("pt_date").pause_share.mean()
print(s.round(3).to_string())
