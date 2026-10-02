"""Frame/belief contagion table: for hand-picked interpretive terms (coined frames, claims,
and one correction), measure spread in chat AND in agents' private memories.

chat: coiner, first use, #agents, #families, hours to 5th agent, last use, uses
memory: #agents whose memory snapshot contains the term, memory-only adopters (term in
memory but agent never said it in chat), first memory time, longest per-agent retention
(last snapshot containing term - first snapshot containing it).

Output: frames_table.csv, frames_memory_firsts.csv
"""
import os
import duckdb
import pandas as pd

OUT = os.path.dirname(os.path.abspath(__file__))
con = duckdb.connect('/Users/ianmacdonald/code/grove-hackathon/data/village.duckdb', read_only=True)
con.execute("SET memory_limit='2GB'; SET threads=2;")

TERMS = [
    "divergent reality", "schrödinger's cli", "illusion of green", "false completion",
    "hostile environment", "activation protocol", "temporal bleed", "geological clock",
    "bridge architecture", "empty quadrant", "constraint embodiment", "existential attractor",
    "the watch is unbroken", "propagation gap", "weekend pause", "cdn propagation",
]
FAM = """CASE WHEN regexp_matches(lower(s), 'claude|opus|sonnet|haiku|fable') THEN 'Claude'
  WHEN regexp_matches(lower(s), 'gpt|^o[134]') THEN 'GPT' WHEN lower(s) LIKE '%gemini%' THEN 'Gemini'
  WHEN lower(s) LIKE '%deepseek%' THEN 'DeepSeek' WHEN regexp_matches(lower(s), 'kimi|leader') THEN 'Kimi'
  WHEN lower(s) LIKE '%glm%' THEN 'GLM' WHEN lower(s) LIKE '%grok%' THEN 'Grok' ELSE 'Other' END"""

alt = "|".join(t.replace("'", "''") for t in TERMS)
chat = con.execute(f"""
  SELECT t term, speaker s, created_at, room FROM (
    SELECT unnest(list_distinct(regexp_extract_all(lower(content), '{alt}'))) t, speaker, created_at, room
    FROM chat WHERE speaker_type='agent' AND regexp_matches(lower(content), '{alt}'))
""").df()
chat["fam"] = con.execute(f"SELECT {FAM} FROM (SELECT unnest($1) s)", [chat.s.tolist()]).df().iloc[:, 0].values

mem = con.execute(f"""
  SELECT a.name s, m.created_at, unnest(list_distinct(regexp_extract_all(lower(m.content), '{alt}'))) term
  FROM agent_memories m JOIN agents a ON a.id = m.agent_id
  WHERE m.created_at >= '2025-11-01' AND regexp_matches(lower(m.content), '{alt}')
""").df()

rows, firsts = [], []
for t in TERMS:
    c = chat[chat.term == t].sort_values("created_at")
    m = mem[mem.term == t]
    if c.empty and m.empty:
        continue
    fa = c.groupby("s").created_at.min().sort_values()
    t5 = (fa.iloc[4] - fa.iloc[0]).total_seconds() / 3600 if len(fa) >= 5 else None
    mg = m.groupby("s").created_at.agg(["min", "max", "count"])
    chat_agents = set(fa.index)
    mem_agents = set(mg.index)
    retention = (mg["max"] - mg["min"]).dt.total_seconds() / 86400 if len(mg) else pd.Series(dtype=float)
    rows.append(dict(
        term=t,
        coiner=fa.index[0] if len(fa) else None,
        first_chat=fa.iloc[0] if len(fa) else None,
        chat_agents=len(chat_agents),
        families=",".join(sorted(set(c.fam))),
        hours_to_5=round(t5, 2) if t5 is not None else None,
        chat_uses=len(c),
        last_chat=c.created_at.max() if len(c) else None,
        rooms=",".join(sorted(set(c.room))),
        mem_agents=len(mem_agents),
        mem_only_agents=len(mem_agents - chat_agents),
        mem_only=", ".join(sorted(mem_agents - chat_agents)),
        first_mem=m.created_at.min() if len(m) else None,
        mem_snapshots=len(m),
        max_retention_days=round(retention.max(), 1) if len(retention) else None,
        median_retention_days=round(retention.median(), 1) if len(retention) else None,
        last_mem=m.created_at.max() if len(m) else None,
    ))
    for s, r in mg.iterrows():
        firsts.append(dict(term=t, agent=s, first_mem=r["min"], last_mem=r["max"], snapshots=r["count"],
                           first_chat=fa.get(s)))
df = pd.DataFrame(rows)
df.to_csv(os.path.join(OUT, "frames_table.csv"), index=False)
pd.DataFrame(firsts).sort_values(["term", "first_mem"]).to_csv(os.path.join(OUT, "frames_memory_firsts.csv"), index=False)
pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 60)
print(df.drop(columns=["mem_only"]).to_string())
