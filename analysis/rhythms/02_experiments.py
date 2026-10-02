"""Before/after comparisons around scaffolding changes (natural experiments).

Per village day we compute:
  - agent chat msgs per active-agent-hour (active hours = first..last agent event)
  - idle actions (WAIT+PAUSE) per active-agent-hour
  - median agent message length
  - cross-agent mention rate: share of agent msgs that name another agent (full name, len>=5,
    or @-prefixed short name)
  - @-mention rate (msg contains '@' + some agent name)
  - nudges
Then compare N village days before vs N after each change (change day excluded).
Writes daily_social.csv and experiments.csv.
"""
import pandas as pd
from db import connect, OUT

con = connect()

# name-boundary regexes so '@Claude Opus 4' does not match '@Claude Opus 4.5', 'GPT-5' not 'GPT-5.1'
con.execute(r"""CREATE TEMP TABLE an AS SELECT id::VARCHAR AS id, name,
  '(^|[^0-9A-Za-z])' || regexp_escape(name) || '($|[^0-9A-Za-z.]|\.[^0-9])' AS re_name,
  '@' || regexp_escape(name) || '($|[^0-9A-Za-z.]|\.[^0-9])' AS re_at
FROM agents""")

social = con.execute("""
WITH m AS (
  SELECT c.id, CAST(c.created_at - INTERVAL 7 HOUR AS DATE) AS pt_date, c.agent_speaker_id, c.room,
         length(c.content) AS len,
         max(CASE WHEN a.id <> c.agent_speaker_id AND (
                   (length(a.name) >= 5 AND regexp_matches(c.content, a.re_name))
                   OR regexp_matches(c.content, a.re_at)) THEN 1 ELSE 0 END) AS mentions_other,
         max(CASE WHEN a.id <> c.agent_speaker_id AND regexp_matches(c.content, a.re_at) THEN 1 ELSE 0 END) AS at_mention,
         count(DISTINCT CASE WHEN a.id <> c.agent_speaker_id AND (
                   (length(a.name) >= 5 AND regexp_matches(c.content, a.re_name))
                   OR regexp_matches(c.content, a.re_at)) THEN a.id END) AS n_named
  FROM chat c CROSS JOIN an a
  WHERE c.speaker_type = 'agent'
  GROUP BY 1, 2, 3, 4, 5)
SELECT pt_date, count(*) AS agent_msgs, avg(mentions_other) AS mention_rate,
       avg(at_mention) AS at_mention_rate, avg(n_named) AS names_per_msg,
       count(DISTINCT room) AS rooms_used
FROM m GROUP BY 1 ORDER BY 1
""").df()
social.to_csv(f"{OUT}/daily_social.csv", index=False)

s = pd.read_csv(f"{OUT}/daily_swarm.csv", parse_dates=["pt_date", "first_event", "last_event"])
social["pt_date"] = pd.to_datetime(social["pt_date"])
d = s.merge(social[["pt_date", "mention_rate", "at_mention_rate", "names_per_msg", "rooms_used"]], on="pt_date", how="left")
# sanity: active_hours from agent events can be distorted by stray late events; clip to [1, 12]
d["hours"] = d["active_hours"].clip(1, 12)
d["agent_hours"] = d["active_agents"] * d["hours"]
d["msgs_per_agent_hr"] = d["agent_msgs"] / d["agent_hours"]
d["swarm_msgs_per_hr"] = d["agent_msgs"] / d["hours"]
d["idle_per_agent_hr"] = (d["wait"].fillna(0) + d["pause"].fillna(0)) / d["agent_hours"]
d["turns_per_agent_hr"] = d["turns"] / d["agent_hours"]
d["err_rate"] = d["turn_errors"] / d["turns"]
d["human_msgs_per_day"] = d["human_msgs"]
d = d[d["active_agents"] >= 2]
d.to_csv(f"{OUT}/daily_metrics.csv", index=False)

CHANGES = [
    ("2025-09-05", "search_history tool"),
    ("2026-02-10", "auto-nudger bot"),
    ("2026-02-25", "chat rooms v1"),
    ("2026-03-24", "perma-computer-use"),
    ("2026-04-14", "outreach approval"),
    ("2026-05-28", "'keep messages short' prompt"),
    ("2026-06-29", "8h hours expansion"),
    ("2026-07-03", "private per-agent goals"),
]
METRICS = ["active_agents", "hours", "msgs_per_agent_hr", "swarm_msgs_per_hr", "idle_per_agent_hr",
           "agent_msg_len_median", "mention_rate", "at_mention_rate", "turns_per_agent_hr", "err_rate",
           "nudge_msgs", "human_msgs", "search_history", "consolidate"]
rows = []
for N in (5, 10):
    for date, label in CHANGES:
        dt = pd.Timestamp(date)
        before = d[d.pt_date < dt].tail(N)
        after = d[d.pt_date > dt].head(N)
        row = {"change": label, "date": date, "N": N,
               "before_span": f"{before.pt_date.min().date()}..{before.pt_date.max().date()}",
               "after_span": f"{after.pt_date.min().date()}..{after.pt_date.max().date()}",
               "goals_before": " | ".join(before.village_goal.dropna().unique())[:160],
               "goals_after": " | ".join(after.village_goal.dropna().unique())[:160]}
        for m in METRICS:
            row[f"{m}_before"] = before[m].mean()
            row[f"{m}_after"] = after[m].mean()
        rows.append(row)
ex = pd.DataFrame(rows)
ex.to_csv(f"{OUT}/experiments.csv", index=False)
pd.set_option("display.width", 250)
for N in (5, 10):
    e = ex[ex.N == N]
    print(f"\n==== N={N} village days each side ====")
    for m in METRICS:
        print(f"{m:22s}", "  ".join(f"{r.change[:14]:>14s}: {r[m+'_before']:.3g}->{r[m+'_after']:.3g}" for _, r in e.iterrows()))
print()
print(ex[ex.N == 5][["change", "before_span", "after_span", "goals_before", "goals_after"]].to_string())
