"""Systematic phrase-contagion scan over agent chat.

Pass 1: tokenise every agent chat message, hash all 2-4-grams (lowercase), write
(hash, agent, ts) rows to a temp parquet, aggregate in DuckDB to per-ngram
distinct-agent counts and per-agent first-use times.
Pass 2: for n-grams used by >=5 agents whose first use is >= 2025-06-01 (two months
of baseline so ordinary English is already "used"), recover the text, measure how
often it is written capitalised / quoted (a coinage signal), whether a human
message or a village goal contained it first (broadcast, not peer contagion),
and how fast it reached 5 agents.

Output: ngram_candidates.parquet + ngram_top.csv in this folder.
Run: PYTHONHASHSEED=0 uv run python analysis/contagion/01_ngram_spread.py
"""
import os, re, sys, time
import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

OUT = os.path.dirname(os.path.abspath(__file__))
TMP = os.environ.get("SCRATCH", OUT)
con = duckdb.connect('/Users/ianmacdonald/code/grove-hackathon/data/village.duckdb', read_only=True)
con.execute("SET memory_limit='2GB'; SET threads=2;")

FAMILY = [
    ("claude", "Claude"), ("opus", "Claude"), ("sonnet", "Claude"), ("haiku", "Claude"), ("fable", "Claude"),
    ("gpt", "GPT"), ("o1", "GPT"), ("o3", "GPT"), ("o4", "GPT"),
    ("gemini", "Gemini"), ("deepseek", "DeepSeek"), ("kimi", "Kimi"), ("leader", "Kimi"),
    ("glm", "GLM"), ("grok", "Grok"), ("muse", "Meta"),
]
def family(name):
    n = name.lower()
    for k, f in FAMILY:
        if k in n:
            return f
    return "Other"

STOP = set("""a an the and or but if then of to in on at by for with from as is are was were be been being it its this that these those
i we you he she they me us him her them my our your their i'm we're we've i've i'll we'll it's that's there's let's
do does did done have has had having will would can could should may might must shall not no yes so just also very
all any some more most other such only own same than too s t don't can't won't isn't aren't what which who whom whose
when where why how up down out over under again further once here there about into through during before after above below
off am pm pt utc""".split())
TOK = re.compile(r"[a-z0-9]+(?:['’\-][a-z0-9]+)*")

msgs = con.execute("""
    SELECT id, epoch(created_at)::BIGINT ts, speaker, room, content
    FROM chat WHERE speaker_type='agent' AND content IS NOT NULL ORDER BY created_at
""").fetchall()
agents = sorted({m[2] for m in msgs})
aidx = {a: i for i, a in enumerate(agents)}
print(len(msgs), "agent messages,", len(agents), "agents", file=sys.stderr)

def ngrams(toks):
    L = len(toks)
    for n in (2, 3, 4):
        for i in range(L - n + 1):
            g = toks[i:i + n]
            if all(t in STOP for t in g):
                continue
            if any(t.isdigit() for t in g):
                continue
            if g[0] in STOP and g[-1] in STOP and n == 2:
                continue
            yield " ".join(g)

t0 = time.time()
path = os.path.join(TMP, "ngram_occ.parquet")
writer = None
H, A, T = [], [], []
def flush():
    global writer, H, A, T
    if not H:
        return
    tbl = pa.table({"h": pa.array(H, pa.int64()), "a": pa.array(A, pa.int16()), "ts": pa.array(T, pa.int64())})
    if writer is None:
        writer = pq.ParquetWriter(path, tbl.schema)
    writer.write_table(tbl)
    H, A, T = [], [], []

for k, (mid, ts, spk, room, content) in enumerate(msgs):
    toks = TOK.findall(content.lower())
    ai = aidx[spk]
    seen = set()
    for g in ngrams(toks):
        h = hash(g)
        if h in seen:
            continue
        seen.add(h)
        H.append(h); A.append(ai); T.append(ts)
    if len(H) > 5_000_000:
        flush()
    if k % 20000 == 0:
        print(k, round(time.time() - t0), file=sys.stderr)
flush(); writer.close()
print("pass1 done", round(time.time() - t0), file=sys.stderr)

# Aggregate: per hash, distinct agents, first ts, uses
con2 = duckdb.connect()
con2.execute("SET memory_limit='2GB'; SET threads=2;")
con2.execute(f"SET temp_directory='{TMP}/duck_tmp'")
cand = con2.execute(f"""
    WITH pa AS (SELECT h, a, min(ts) fts, count(*) n FROM read_parquet('{path}') GROUP BY h, a)
    SELECT h, count(*) n_agents, min(fts) first_ts, sum(n) uses,
           list(fts ORDER BY fts) agent_first_ts
    FROM pa GROUP BY h
    HAVING count(*) >= 5 AND min(fts) >= epoch(TIMESTAMP '2025-06-01')
""").df()
print("candidates", len(cand), file=sys.stderr)
cand["t5"] = cand.agent_first_ts.apply(lambda l: l[4])
cand["days_to_5"] = (cand.t5 - cand.first_ts) / 86400
# keep the ones that reached 5 agents within 30 days (fast-spreading) to bound pass 2
keep = cand[cand.days_to_5 <= 30]
keepset = set(keep.h.tolist())
print("fast candidates", len(keepset), file=sys.stderr)

# Pass 2: recover text, per-agent first use, capitalisation/quote rate
from collections import defaultdict
text_of = {}
first = defaultdict(dict)    # h -> agent -> (ts, msg_id, room)
cap = defaultdict(int); quoted = defaultdict(int); tot = defaultdict(int)
for mid, ts, spk, room, content in msgs:
    low = content.lower()
    toks = TOK.findall(low)
    hs = {}
    for g in ngrams(toks):
        h = hash(g)
        if h in keepset and h not in hs:
            hs[h] = g
    for h, g in hs.items():
        text_of[h] = g
        if spk not in first[h]:
            first[h][spk] = (ts, mid, room)
        tot[h] += 1
        # capitalised / quoted occurrence in original text
        pat = r"\b" + r"[\s\-]+".join(re.escape(w) for w in g.split()) + r"\b"
        m = re.search(pat, content, flags=re.I)
        if m:
            s = m.group(0)
            words = [w for w in re.split(r"[\s\-]+", s) if w.lower() not in STOP]
            if words and all(w[:1].isupper() for w in words):
                cap[h] += 1
            pre = content[max(0, m.start() - 2):m.start()]
            if any(q in pre for q in "\"'“‘*`"):
                quoted[h] += 1

# human / goal priors
hum = con.execute("SELECT epoch(created_at)::BIGINT ts, lower(content) c FROM chat WHERE speaker_type='user'").fetchall()
goals = " || ".join(r[0].lower() for r in con.execute("SELECT goal FROM village_goals").fetchall())
goals += " || " + " || ".join((r[0] or "").lower() + " " + (r[1] or "").lower() for r in con.execute("SELECT name, description FROM agent_goals").fetchall())

rows = []
for h in keepset:
    g = text_of.get(h)
    if g is None:
        continue
    fa = sorted(first[h].items(), key=lambda kv: kv[1][0])
    fams = {family(a) for a, _ in fa}
    fts = fa[0][1][0]
    t5 = fa[4][1][0]
    rows.append(dict(
        h=h, ngram=g, n=len(g.split()), n_agents=len(fa), n_families=len(fams), families=",".join(sorted(fams)),
        uses=tot[h], first_ts=fts, first_agent=fa[0][0], first_msg=fa[0][1][1], first_room=fa[0][1][2],
        hours_to_5=(t5 - fts) / 3600, order=" > ".join(a for a, _ in fa[:8]),
        cap_frac=cap[h] / tot[h], quote_frac=quoted[h] / tot[h], in_goal=g in goals,
    ))
import pandas as pd
df = pd.DataFrame(rows)
# human prior: did any human message contain the n-gram before (or within 1h after) the first agent use?
hum_ng = defaultdict(lambda: None)
gset = set(df.ngram)
for ts, c in sorted(hum):
    for g in set(ngrams(TOK.findall(c))):
        if g in gset and hum_ng[g] is None:
            hum_ng[g] = ts
df["human_first_ts"] = df.ngram.map(lambda g: hum_ng[g])
df["human_before"] = df.human_first_ts.notna() & (df.human_first_ts <= df.first_ts + 3600)
df["first_utc"] = pd.to_datetime(df.first_ts, unit="s")
df.to_parquet(os.path.join(OUT, "ngram_candidates.parquet"))
print("wrote", len(df), file=sys.stderr)
