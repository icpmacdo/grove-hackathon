"""Daily activity time series (swarm-wide and per agent).

Village "day" is computed on Pacific-ish time: pt_date = date(created_at - 7h).
Village day number: day 1 = 2025-04-02.

Outputs (CSV in this folder):
  daily_swarm.csv       one row per pt_date
  daily_agent.csv       one row per (pt_date, agent)
"""
from db import connect, OUT

con = connect()

con.execute("""
CREATE TEMP TABLE ev AS
SELECT CAST(created_at - INTERVAL 7 HOUR AS DATE) AS pt_date, agent_id, action_type,
       try_cast(data->>'inputTokens' AS BIGINT) AS in_tok,
       try_cast(data->>'outputTokens' AS BIGINT) AS out_tok,
       created_at
FROM events
""")

con.execute("""
CREATE TEMP TABLE ch AS
SELECT CAST(created_at - INTERVAL 7 HOUR AS DATE) AS pt_date, created_at, speaker_type, speaker,
       agent_speaker_id, room, length(content) AS len,
       (speaker_type='user' AND content LIKE '%automated nudge triggered by%') AS is_nudge,
       village_goal
FROM chat
""")

con.execute("""
CREATE TEMP TABLE tu AS
SELECT CAST(created_at - INTERVAL 7 HOUR AS DATE) AS pt_date, agent_id,
       count(*) AS turns,
       count(*) FILTER (WHERE error IS NOT NULL AND error <> '') AS turn_errors,
       count(DISTINCT session_id) AS sessions_with_turns,
       count(*) FILTER (WHERE action_type = 'bash' OR command IS NOT NULL) AS bash_turns
FROM turns GROUP BY 1, 2
""")

# ---------- swarm-level ----------
swarm = con.execute("""
WITH e AS (
  SELECT pt_date,
    count(DISTINCT agent_id) FILTER (WHERE action_type NOT IN ('USER_TALK','USER_NAME_CHANGE')) AS active_agents,
    count(*) FILTER (WHERE action_type='AGENT_TALK') AS agent_talk,
    count(*) FILTER (WHERE action_type='WAIT') AS wait,
    count(*) FILTER (WHERE action_type='PAUSE') AS pause,
    count(*) FILTER (WHERE action_type='CONSOLIDATE') AS consolidate,
    count(*) FILTER (WHERE action_type='SEARCH_HISTORY') AS search_history,
    count(*) FILTER (WHERE action_type='START_USING_COMPUTER') AS start_computer,
    count(*) FILTER (WHERE action_type='USER_TALK') AS user_talk,
    count(*) FILTER (WHERE action_type='OUTREACH_APPROVAL_REQUEST') AS outreach_req,
    count(*) FILTER (WHERE action_type='REQUEST_HUMAN_HELPER') AS human_helper_req,
    count(*) AS events_total,
    sum(in_tok) AS in_tokens, sum(out_tok) AS out_tokens,
    min(created_at) AS first_event, max(created_at) AS last_event
  FROM ev GROUP BY 1),
c AS (
  SELECT pt_date,
    count(*) FILTER (WHERE speaker_type='agent') AS agent_msgs,
    count(*) FILTER (WHERE speaker_type='user' AND NOT is_nudge) AS human_msgs,
    count(*) FILTER (WHERE is_nudge) AS nudge_msgs,
    avg(len) FILTER (WHERE speaker_type='agent') AS agent_msg_len_mean,
    median(len) FILTER (WHERE speaker_type='agent') AS agent_msg_len_median,
    count(DISTINCT agent_speaker_id) AS speaking_agents,
    any_value(village_goal) AS village_goal
  FROM ch GROUP BY 1),
t AS (
  SELECT pt_date, sum(turns) AS turns, sum(turn_errors) AS turn_errors, sum(sessions_with_turns) AS sessions
  FROM tu GROUP BY 1)
SELECT coalesce(e.pt_date, c.pt_date, t.pt_date) AS pt_date,
       datediff('day', DATE '2025-04-02', coalesce(e.pt_date, c.pt_date, t.pt_date)) + 1 AS village_day,
       e.* EXCLUDE (pt_date), c.* EXCLUDE (pt_date), t.* EXCLUDE (pt_date)
FROM e FULL OUTER JOIN c USING (pt_date) FULL OUTER JOIN t USING (pt_date)
ORDER BY 1
""").df()
swarm = swarm.drop(columns=[c for c in swarm.columns if c.startswith("pt_date_")], errors="ignore")
swarm["active_hours"] = (swarm["last_event"] - swarm["first_event"]).dt.total_seconds() / 3600
swarm.to_csv(f"{OUT}/daily_swarm.csv", index=False)
print(swarm.tail(10).to_string())
print(len(swarm), "days")

# ---------- per-agent ----------
agent = con.execute("""
WITH e AS (
  SELECT pt_date, agent_id,
    count(*) FILTER (WHERE action_type='AGENT_TALK') AS agent_talk,
    count(*) FILTER (WHERE action_type='WAIT') AS wait,
    count(*) FILTER (WHERE action_type='PAUSE') AS pause,
    count(*) FILTER (WHERE action_type='CONSOLIDATE') AS consolidate,
    count(*) FILTER (WHERE action_type='SEARCH_HISTORY') AS search_history,
    count(*) FILTER (WHERE action_type='START_USING_COMPUTER') AS start_computer,
    count(*) FILTER (WHERE action_type='OUTREACH_APPROVAL_REQUEST') AS outreach_req,
    count(*) AS events_total,
    sum(in_tok) AS in_tokens, sum(out_tok) AS out_tokens,
    min(created_at) AS first_event, max(created_at) AS last_event
  FROM ev WHERE agent_id IS NOT NULL AND action_type NOT IN ('USER_TALK','USER_NAME_CHANGE')
  GROUP BY 1, 2),
c AS (
  SELECT pt_date, agent_speaker_id AS agent_id, count(*) AS chat_msgs, avg(len) AS chat_len_mean,
         sum(len) AS chat_chars
  FROM ch WHERE speaker_type='agent' GROUP BY 1, 2),
n AS (  -- nudges addressed to an agent (by @name mention)
  SELECT CAST(c.created_at - INTERVAL 7 HOUR AS DATE) AS pt_date, a.id::VARCHAR AS agent_id, count(*) AS nudges_received
  FROM chat c JOIN agents a ON c.content LIKE '%@' || a.name || '%'
  WHERE c.speaker_type='user' AND c.content LIKE '%automated nudge triggered by%'
  GROUP BY 1, 2)
SELECT coalesce(e.pt_date, c.pt_date, tu.pt_date) AS pt_date,
       coalesce(e.agent_id, c.agent_id, tu.agent_id) AS agent_id,
       e.* EXCLUDE (pt_date, agent_id), c.* EXCLUDE (pt_date, agent_id),
       tu.* EXCLUDE (pt_date, agent_id), n.nudges_received
FROM e FULL OUTER JOIN c ON e.pt_date=c.pt_date AND e.agent_id=c.agent_id
FULL OUTER JOIN tu ON coalesce(e.pt_date, c.pt_date)=tu.pt_date AND coalesce(e.agent_id, c.agent_id)=tu.agent_id
LEFT JOIN n ON n.pt_date=coalesce(e.pt_date, c.pt_date, tu.pt_date) AND n.agent_id=coalesce(e.agent_id, c.agent_id, tu.agent_id)
ORDER BY 1, 2
""").df()
names = con.execute("SELECT id::VARCHAR AS agent_id, name FROM agents").df()
agent = agent.merge(names, on="agent_id", how="left")
agent["village_day"] = (agent["pt_date"] - __import__("pandas").Timestamp("2025-04-02")).dt.days + 1
agent.to_csv(f"{OUT}/daily_agent.csv", index=False)
print(agent.tail(5).to_string())
print(len(agent), "agent-days")
