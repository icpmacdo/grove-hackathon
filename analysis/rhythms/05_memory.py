"""What agents remember about each other.

1. Memory size growth: per agent per month, median/max chars and number of consolidations.
2. Latest memory per agent per month (ids first, then content for those ~rows only):
   - which other agents are named, how often
   - sentences pairing another agent's name with trust/reliability vocabulary
3. Belief persistence: the 'nudge-exempt' / 'guardian-exempt' idea, corrected by a human on
   2026-08-20 17:26 UTC ("there is no 'nudge-exempt' currently").
Writes memory_size_monthly.csv, memory_mentions_latest.csv, memory_trust_snippets.csv,
memory_nudge_exempt_daily.csv.
"""
import re
import pandas as pd
from db import connect, OUT

con = connect()
names = con.execute("SELECT id::VARCHAR AS agent_id, name FROM agents").df()
id2name = dict(zip(names.agent_id, names.name))

# 1. size growth -------------------------------------------------------------
size = con.execute("""
SELECT agent_id, date_trunc('month', created_at) AS month, count(*) AS n_mem,
       median(length(content)) AS med_chars, max(length(content)) AS max_chars
FROM agent_memories GROUP BY 1, 2 ORDER BY 1, 2""").df()
size["name"] = size.agent_id.map(id2name)
size.to_csv(f"{OUT}/memory_size_monthly.csv", index=False)
piv = size.pivot_table(index="month", values="med_chars", aggfunc="median")
print("=== median memory size (chars) across agents, by month ===")
print(size.groupby("month").agg(agents=("agent_id", "nunique"), consolidations=("n_mem", "sum"),
                                med_chars=("med_chars", "median"), max_chars=("max_chars", "max")).to_string())

# 2. latest memory per agent per month --------------------------------------
latest_ids = con.execute("""
SELECT id FROM (
  SELECT id, row_number() OVER (PARTITION BY agent_id, date_trunc('month', created_at) ORDER BY created_at DESC) AS rn
  FROM agent_memories) WHERE rn = 1""").df()
con.register("latest_ids", latest_ids)
mem = con.execute("""SELECT m.id, m.agent_id, m.created_at, m.content FROM agent_memories m
                     JOIN latest_ids l ON m.id = l.id""").df()
mem["name"] = mem.agent_id.map(id2name)
print(f"\nlatest-per-month memories: {len(mem)} rows, {mem.content.str.len().sum()/1e6:.1f}M chars")

pats = {n: re.compile(r"(?<![0-9A-Za-z])" + re.escape(n) + r"(?![0-9A-Za-z]|\.[0-9])") for n in names.name}
# common short forms used in memories
alias = {"GPT-5.6 Luna": ["Luna"], "GPT-5.6 Terra": ["Terra"], "GPT-5.6 Sol": ["Sol"],
         "Claude Haiku 4.5": ["Haiku 4.5", "Haiku"], "Claude Opus 4.5": ["Opus 4.5"], "Claude Opus 4.6": ["Opus 4.6"],
         "Claude Opus 4.7": ["Opus 4.7"], "Claude Opus 4.8": ["Opus 4.8"], "Claude Opus 5": ["Opus 5"],
         "Claude Sonnet 4.5": ["Sonnet 4.5"], "Claude Sonnet 4.6": ["Sonnet 4.6"], "Claude Sonnet 5": ["Sonnet 5"],
         "Claude 3.7 Sonnet": ["3.7 Sonnet", "Sonnet 3.7"], "Claude Fable 5": ["Fable 5"], "Claude Fable 5.1": ["Fable 5.1"],
         "Gemini 2.5 Pro": ["Gemini 2.5"], "Gemini 3.1 Pro": ["Gemini 3.1"], "Gemini 3 Pro": ["Gemini 3 Pro"],
         "DeepSeek-V3.2": ["DeepSeek V3.2", "DeepSeek-V3"], "DeepSeek-V4-Pro": ["DeepSeek V4", "DeepSeek-V4"]}
for full, al in alias.items():
    pats[full] = re.compile("|".join([r"(?<![0-9A-Za-z])" + re.escape(x) + r"(?![0-9A-Za-z]|\.[0-9])" for x in [full] + al]))

rows = []
for r in mem.itertuples():
    for n, p in pats.items():
        if n == r.name:
            continue
        k = len(p.findall(r.content))
        if k:
            rows.append({"memory_id": r.id, "agent": r.name, "created_at": r.created_at, "mentioned": n, "count": k})
men = pd.DataFrame(rows)
men.to_csv(f"{OUT}/memory_mentions_latest.csv", index=False)

# share of currently-active peers each agent's latest memory names, per month
active = con.execute("""SELECT date_trunc('month', e.created_at) AS month, a.name, count(*) AS ev
  FROM events e JOIN agents a ON e.agent_id = a.id::VARCHAR
  WHERE action_type NOT IN ('USER_TALK','USER_NAME_CHANGE') GROUP BY 1, 2 HAVING count(*) > 20""").df()
mem["month"] = mem.created_at.dt.to_period("M").dt.to_timestamp()
cov = []
for r in mem.itertuples():
    peers = set(active[active.month == r.month].name) - {r.name}
    if not peers:
        continue
    named = set(men[(men.memory_id == r.id)].mentioned) if len(men) else set()
    cov.append({"agent": r.name, "month": r.month, "chars": len(r.content), "peers": len(peers),
                "peers_named": len(named & peers), "share": len(named & peers) / len(peers)})
cov = pd.DataFrame(cov)
cov.to_csv(f"{OUT}/memory_peer_coverage.csv", index=False)
print("\n=== share of active peers named in each agent's month-end memory (median across agents) ===")
print(cov.groupby("month").agg(agents=("agent", "count"), peers=("peers", "median"), named=("peers_named", "median"),
                               share=("share", "median"), chars=("chars", "median")).round(2).to_string())
last = cov[cov.month == cov.month.max()].sort_values("share")
print("\nlatest month, per agent:")
print(last.round(2).to_string())

# who is most remembered in the latest month
lm = men[men.created_at >= "2026-09-01"]
print("\nmost-mentioned agents in Sept-2026 memories (n memories naming them, total mentions):")
print(lm.groupby("mentioned").agg(memories=("agent", "nunique"), mentions=("count", "sum")).sort_values("memories", ascending=False).head(15).to_string())

# trust vocabulary near other agents' names ---------------------------------
TRUST = re.compile(r"(unreliab|reliab|untrust|trust|verif|hallucinat|fabricat|helpful|struggl|wrong|mistak|error|false|"
                   r"inaccura|misreport|claimed|careful|confus|stuck|spoof|caught|corrected|overclaim|\blied\b|\blying\b|"
                   r"don't rely|do not rely|double-check|cross-check)", re.I)
snips = []
for r in mem.itertuples():
    for sent in re.split(r"(?<=[.!?])\s+|\n", r.content):
        if len(sent) < 15 or not TRUST.search(sent):
            continue
        for n, p in pats.items():
            if n != r.name and p.search(sent):
                snips.append({"memory_id": r.id, "agent": r.name, "created_at": r.created_at, "about": n,
                              "trust_words": ",".join(sorted(set(m.lower() for m in TRUST.findall(sent)))),
                              "sentence": sent.strip()[:300]})
sn = pd.DataFrame(snips)
sn.to_csv(f"{OUT}/memory_trust_snippets.csv", index=False)
print(f"\ntrust-word sentences naming another agent: {len(sn)} across {sn.memory_id.nunique()} memories")
neg = sn[sn.trust_words.str.contains("unreliab|hallucinat|fabricat|untrust|misreport|overclaim|lied|lying|spoof|don't rely|do not rely")]
print(f"of which strongly negative-reliability: {len(neg)}")
print(neg.groupby("about").size().sort_values(ascending=False).head(10).to_string())
print(neg.sample(min(12, len(neg)), random_state=1)[["created_at", "agent", "about", "sentence"]].to_string())

# 3. belief persistence: nudge-exempt / guardian-exempt -----------------------
ne = con.execute("""
SELECT agent_id, CAST(created_at - INTERVAL 7 HOUR AS DATE) AS d, count(*) AS n_mem,
  count(*) FILTER (WHERE regexp_matches(lower(content), 'nudge[- ]exempt|guardian[- ]exempt|exempt from (the )?(idl|nudg)')) AS n_exempt,
  count(*) FILTER (WHERE regexp_matches(lower(content), 'no .?nudge-exempt|no such (thing as )?.?nudge|nudge-exempt.{0,40}(does not|doesn.t) exist|not (actually )?exempt')) AS n_corrected,
  count(*) FILTER (WHERE regexp_matches(lower(content), 'nudger (was |is )?(disabled|turned off|off)|disabling the auto-nudger|auto-nudger.{0,30}disabled')) AS n_nudger_off
FROM agent_memories WHERE created_at >= '2026-07-20' AND created_at < '2026-09-20'
GROUP BY 1, 2 ORDER BY 2""").df()
ne["name"] = ne.agent_id.map(id2name)
ne.to_csv(f"{OUT}/memory_nudge_exempt_daily.csv", index=False)
ne["d"] = pd.to_datetime(ne.d)
print("\n=== memories mentioning nudge/guardian-exempt status, by period ===")
ne["period"] = pd.cut(ne.d, pd.to_datetime(["2026-07-20", "2026-08-20", "2026-08-21", "2026-09-04", "2026-09-20"]),
                      right=False, labels=["before 08-20", "08-20", "08-21..09-03", "09-04..09-19"])
print(ne.groupby("period", observed=True)[["n_mem", "n_exempt", "n_corrected", "n_nudger_off"]].sum().to_string())
print(ne[ne.n_exempt > 0].groupby(["name", "period"], observed=True).n_exempt.sum().unstack(fill_value=0).to_string())
