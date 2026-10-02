"""The auto-nudger (added 2026-02-10) is a deployed behaviour monitor. Event study around nudges.

For each automated nudge (chat speaker_type='user', text 'automated nudge triggered by'),
find addressed agents via '@<name>' and compare that agent's activity in the 30 min before
vs. 30 min after the nudge (same village day). Also: who gets nudged, repeat nudges,
and how agents talk about the nudger.
Writes nudges.csv (one row per nudge x addressed agent).
"""
import pandas as pd
from db import connect, OUT

con = connect()
W = 30  # minutes

con.execute(f"""
CREATE TEMP TABLE nudge AS
SELECT c.id AS chat_id, c.created_at AS t, c.room, a.id::VARCHAR AS agent_id, a.name,
       regexp_extract(c.content, 'triggered by: \\[([^\\]]+)\\]', 1) AS trig,
       left(c.content, 300) AS text
FROM chat c JOIN agents a
  ON regexp_matches(c.content, '@' || regexp_escape(a.name) || '($|[^0-9A-Za-z.]|\\.[^0-9])')
WHERE c.speaker_type='user' AND c.content LIKE '%automated nudge triggered by%'
""")
# guard: 'Claude Opus 4.5' would also match '@Claude Opus 4.5x'? names are distinct enough; check dup
print(con.execute("SELECT count(*), count(DISTINCT chat_id), min(t), max(t) FROM nudge").fetchall())
print(con.execute("SELECT trig, count(*) FROM nudge GROUP BY 1").fetchall())

study = con.execute(f"""
WITH e AS (SELECT agent_id, created_at, action_type FROM events WHERE created_at >= '2026-02-01'),
     tu AS (SELECT agent_id, created_at, (error IS NOT NULL AND error<>'') AS err FROM turns WHERE created_at >= '2026-02-01')
SELECT n.chat_id, n.t, n.agent_id, n.name, n.room,
  (SELECT count(*) FROM e WHERE e.agent_id=n.agent_id AND e.action_type IN ('PAUSE','WAIT') AND e.created_at BETWEEN n.t - INTERVAL {W} MINUTE AND n.t) AS idle_before,
  (SELECT count(*) FROM e WHERE e.agent_id=n.agent_id AND e.action_type IN ('PAUSE','WAIT') AND e.created_at BETWEEN n.t AND n.t + INTERVAL {W} MINUTE) AS idle_after,
  (SELECT count(*) FROM e WHERE e.agent_id=n.agent_id AND e.action_type='AGENT_TALK' AND e.created_at BETWEEN n.t - INTERVAL {W} MINUTE AND n.t) AS talk_before,
  (SELECT count(*) FROM e WHERE e.agent_id=n.agent_id AND e.action_type='AGENT_TALK' AND e.created_at BETWEEN n.t AND n.t + INTERVAL {W} MINUTE) AS talk_after,
  (SELECT count(*) FROM e WHERE e.agent_id=n.agent_id AND e.action_type='CONSOLIDATE' AND e.created_at BETWEEN n.t - INTERVAL {W} MINUTE AND n.t) AS cons_before,
  (SELECT count(*) FROM e WHERE e.agent_id=n.agent_id AND e.action_type='CONSOLIDATE' AND e.created_at BETWEEN n.t AND n.t + INTERVAL {W} MINUTE) AS cons_after,
  (SELECT count(*) FROM tu WHERE tu.agent_id=n.agent_id AND tu.created_at BETWEEN n.t - INTERVAL {W} MINUTE AND n.t) AS turns_before,
  (SELECT count(*) FROM tu WHERE tu.agent_id=n.agent_id AND tu.created_at BETWEEN n.t AND n.t + INTERVAL {W} MINUTE) AS turns_after,
  (SELECT min(c2.t) FROM nudge c2 WHERE c2.agent_id=n.agent_id AND c2.t > n.t AND c2.t < n.t + INTERVAL 1 DAY) AS next_nudge_t
FROM nudge n
""").df()
study["renudged_within_2h"] = (study["next_nudge_t"] - study["t"]).dt.total_seconds() < 7200
study.to_csv(f"{OUT}/nudges.csv", index=False)

print("\n=== event study (mean per nudge, 30-min windows) ===")
cols = ["idle_before", "idle_after", "talk_before", "talk_after", "turns_before", "turns_after", "cons_before", "cons_after"]
print(study[cols].mean().round(2).to_string())
print("share with >=1 idle action after:", (study.idle_after > 0).mean().round(3),
      " share with 0 turns before:", (study.turns_before == 0).mean().round(3),
      " 0 turns after:", (study.turns_after == 0).mean().round(3))
print("re-nudged within 2h:", study.renudged_within_2h.mean().round(3), " n=", len(study))
study["period"] = pd.cut(study.t, pd.to_datetime(["2026-02-01", "2026-03-24", "2026-06-29", "2026-10-01"]),
                         labels=["pre-perma", "perma 4h", "8h days"])
print(study.groupby("period", observed=True)[cols + ["renudged_within_2h"]].mean().round(2).to_string())

print("\n=== nudges per agent (normalised by active agent-days since 2026-02-13) ===")
per = study.groupby("name").size().rename("nudges").to_frame()
ad = con.execute("""SELECT a.name, count(DISTINCT CAST(e.created_at - INTERVAL 7 HOUR AS DATE)) AS days
  FROM events e JOIN agents a ON e.agent_id=a.id::VARCHAR
  WHERE e.created_at BETWEEN '2026-02-13' AND '2026-08-21' AND e.action_type NOT IN ('USER_TALK','USER_NAME_CHANGE')
  GROUP BY 1""").df().set_index("name")
per = per.join(ad, how="outer").fillna(0)
per["per_day"] = per.nudges / per.days.clip(lower=1)
print(per.sort_values("per_day", ascending=False).round(2).to_string())

print("\n=== how agents talk about the nudger ===")
print(con.execute("""
SELECT speaker, count(*) n FROM chat WHERE speaker_type='agent' AND created_at>='2026-02-10'
  AND (lower(content) LIKE '%nudge%') GROUP BY 1 ORDER BY 2 DESC LIMIT 12""").df().to_string())
ex = con.execute("""
SELECT created_at, speaker, room, left(content, 260) AS c FROM chat
WHERE speaker_type='agent' AND created_at>='2026-02-10'
  AND regexp_matches(lower(content), '(nudge|idling detector|idle detector)')
  AND regexp_matches(lower(content), '(false positive|mis-?specified|wrong|incorrect|not idling|ignore|misfir|spurious)')
ORDER BY random() LIMIT 10""").df()
print(ex.to_string())
print(con.execute("""
SELECT count(*) FILTER (WHERE regexp_matches(lower(content), '(nudge|idling detector|idle detector)')) AS mention_nudge,
       count(*) FILTER (WHERE regexp_matches(lower(content), '(nudge|idling detector|idle detector)')
         AND regexp_matches(lower(content), '(false positive|mis-?specified|wrong|incorrect|not idling|ignore|misfir|spurious)')) AS dispute
FROM chat WHERE speaker_type='agent' AND created_at>='2026-02-10'""").fetchall())
