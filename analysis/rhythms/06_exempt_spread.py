"""Trace the spread of the 'nudge-exempt' / 'guardian-exempt' idea through chat and memory.

A human said on 2026-08-20 17:26 UTC: there is no "nudge-exempt" currently. We trace
first use per agent in chat and in memory, daily volume, and post-correction examples.
Writes exempt_spread_daily.csv, exempt_first_use.csv.
"""
import pandas as pd
from db import connect, OUT

con = connect()
RE = r"nudge[- ]exempt|guardian[- ]exempt|exempt from (the )?(idl|nudg)|idle[- ]exempt|idling[- ]exempt"

chat = con.execute(f"""
SELECT created_at, speaker, speaker_type, room, content FROM chat
WHERE regexp_matches(lower(content), '{RE}') ORDER BY created_at""").df()
print("chat messages using the term:", len(chat), "agents:", chat[chat.speaker_type == 'agent'].speaker.nunique())
print("first 6 uses:")
for r in chat.head(6).itertuples():
    print(" ", r.created_at, r.speaker, r.room, "|", r.content[:260].replace("\n", " "))

mem = con.execute(f"""
SELECT a.name, min(m.created_at) AS first_mem, max(m.created_at) AS last_mem, count(*) AS n_mem
FROM agent_memories m JOIN agents a ON m.agent_id=a.id::VARCHAR
WHERE m.created_at >= '2026-06-01' AND regexp_matches(lower(m.content), '{RE}') GROUP BY 1""").df()
first_chat = chat[chat.speaker_type == 'agent'].groupby("speaker").created_at.agg(["min", "max", "count"]).rename(
    columns={"min": "first_chat", "max": "last_chat", "count": "n_chat"})
fu = mem.set_index("name").join(first_chat, how="outer").sort_values("first_mem")
fu.to_csv(f"{OUT}/exempt_first_use.csv")
print("\nfirst use per agent (chat vs memory):")
print(fu.to_string())

chat["d"] = (chat.created_at - pd.Timedelta(hours=7)).dt.date
daily = chat.groupby("d").agg(msgs=("speaker", "size"), agents=("speaker", "nunique"))
memd = con.execute(f"""
SELECT CAST(created_at - INTERVAL 7 HOUR AS DATE) AS d, count(*) AS mem_rows, count(DISTINCT agent_id) AS mem_agents
FROM agent_memories WHERE created_at >= '2026-06-01' AND regexp_matches(lower(content), '{RE}') GROUP BY 1""").df().set_index("d")
daily = daily.join(memd, how="outer").fillna(0)
daily.to_csv(f"{OUT}/exempt_spread_daily.csv")
print("\ndaily:")
print(daily.to_string())

print("\nhuman correction + post-correction chat uses:")
for r in chat[chat.created_at >= "2026-08-20 17:26"].head(12).itertuples():
    print(" ", r.created_at, r.speaker, "|", r.content[:240].replace("\n", " "))

print("\npost-correction memory snippets (after 2026-08-21):")
snip = con.execute(f"""
SELECT a.name, m.created_at,
  substr(m.content, greatest(1, regexp_matches(lower(m.content), '{RE}')::INT * 0 + strpos(lower(m.content), 'exempt') - 160), 340) AS ctx
FROM agent_memories m JOIN agents a ON m.agent_id=a.id::VARCHAR
WHERE m.created_at >= '2026-08-21' AND regexp_matches(lower(m.content), '{RE}')
QUALIFY row_number() OVER (PARTITION BY a.name ORDER BY m.created_at DESC) <= 2
ORDER BY m.created_at""").df()
for r in snip.itertuples():
    print(" ", r.created_at, r.name, "|", r.ctx.replace("\n", " "))
