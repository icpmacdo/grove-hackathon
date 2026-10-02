"""Stylistic convergence: do agents drift toward the village's style over time?

Model weights are fixed per agent, so any within-agent drift in style comes from
context (peers' messages, own memory, goal/prompt/scaffold changes).

Features per agent message: emoji, bold (**), markdown header line, bullet/numbered list,
@mention, length (chars), em-dash, exclamation.
For each agent-week we compute the feature rate and the rate among all OTHER agents in the
same calendar week (and same room when rooms exist). Gap = |agent - others|.
We then look at gap vs weeks-since-join for agents with >= 8 active weeks.

Output: style_weekly.parquet, style_convergence.csv
"""
import os
import duckdb
import pandas as pd

OUT = os.path.dirname(os.path.abspath(__file__))
con = duckdb.connect('/Users/ianmacdonald/code/grove-hackathon/data/village.duckdb', read_only=True)
con.execute("SET memory_limit='2GB'; SET threads=2;")

feat = con.execute(r"""
WITH m AS (
  SELECT speaker, room, created_at, date_trunc('week', created_at) wk, content
  FROM chat WHERE speaker_type='agent' AND content IS NOT NULL
)
SELECT speaker, wk,
  count(*) n,
  avg(regexp_matches(content, '[\x{1F300}-\x{1FAFF}\x{2600}-\x{27BF}\x{2B50}\x{2705}]')::INT) emoji,
  avg((content LIKE '%**%')::INT) bold,
  avg(regexp_matches(content, '(?m)^#{1,4} ')::INT) hdr,
  avg(regexp_matches(content, '(?m)^\s*([-*•]|\d+\.) ')::INT) lst,
  avg(regexp_matches(content, '@[A-Z]')::INT) mention,
  avg((content LIKE '%—%')::INT) emdash,
  avg((content LIKE '%!%')::INT) exclaim,
  median(length(content)) med_len
FROM m GROUP BY speaker, wk
""").df()
feat.to_parquet(os.path.join(OUT, "style_weekly.parquet"))

FEATS = ["emoji", "bold", "hdr", "lst", "mention", "emdash", "exclaim", "med_len"]
# others' (message-weighted) mean per week
tot = feat.copy()
for f in FEATS:
    tot[f + "_x"] = tot[f] * tot.n
wk = tot.groupby("wk")[[f + "_x" for f in FEATS] + ["n"]].sum()
rows = []
for _, r in feat.iterrows():
    w = wk.loc[r.wk]
    n_oth = w.n - r.n
    if n_oth < 50:
        continue
    d = dict(speaker=r.speaker, wk=r.wk, n=r.n)
    for f in FEATS:
        oth = (w[f + "_x"] - r[f] * r.n) / n_oth
        d[f] = r[f]; d[f + "_oth"] = oth
        d[f + "_gap"] = abs(r[f] - oth)
    rows.append(d)
g = pd.DataFrame(rows)
first = feat.groupby("speaker").wk.min().rename("wk0")
g = g.join(first, on="speaker")
g["k"] = ((g.wk - g.wk0).dt.days // 7).astype(int)
g.to_parquet(os.path.join(OUT, "style_gaps.parquet"))

# agents with >= 8 active weeks and >= 20 msgs/week considered
act = g[g.n >= 20]
good = act.groupby("speaker").k.nunique()
good = good[good >= 8].index
a = act[act.speaker.isin(good)]
# normalise each feature's gap by its overall sd across agent-weeks so features are comparable
for f in FEATS:
    a[f + "_z"] = a[f + "_gap"] / feat[f].std()
a["gap_mean"] = a[[f + "_z" for f in FEATS]].mean(axis=1)
a["bucket"] = pd.cut(a.k, [-1, 0, 1, 3, 7, 15, 200], labels=["wk0", "wk1", "wk2-3", "wk4-7", "wk8-15", "wk16+"])
summ = a.groupby("bucket", observed=True).agg(agent_weeks=("n", "size"), agents=("speaker", "nunique"),
                                             gap_mean=("gap_mean", "mean"),
                                             **{f + "_gap": (f + "_gap", "mean") for f in FEATS})
print(summ.round(3).to_string())
summ.to_csv(os.path.join(OUT, "style_convergence.csv"))

# per agent: gap in first 2 active weeks vs weeks 4-11
per = []
for s, d in a.groupby("speaker"):
    e = d[d.k <= 1]; l = d[(d.k >= 4) & (d.k <= 11)]
    if len(e) and len(l):
        per.append(dict(speaker=s, early=e.gap_mean.mean(), late=l.gap_mean.mean(), wk0=d.wk0.iloc[0].date()))
per = pd.DataFrame(per)
per["delta"] = per.late - per.early
print(per.sort_values("wk0").round(3).to_string())
print("agents converging (late<early):", (per.delta < 0).sum(), "of", len(per))
per.to_csv(os.path.join(OUT, "style_convergence_per_agent.csv"), index=False)
