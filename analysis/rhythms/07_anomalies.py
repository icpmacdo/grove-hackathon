"""Agent-day anomaly candidates a monitor should flag.

Scores each agent-day against that agent's own history (robust z: (x - median) / (1.4826*MAD))
for: turn error rate, chat message volume, turns volume, pause share; plus absolute rules
(present-but-inert: >=90% paused; zero turns while consolidating; error rate > 30% with >=100 turns).
Writes anomalies.csv (all flagged agent-days with scores).
"""
import numpy as np
import pandas as pd
from db import OUT

a = pd.read_csv(f"{OUT}/daily_agent.csv", parse_dates=["pt_date"])
p = pd.read_csv(f"{OUT}/daily_agent_pause.csv", parse_dates=["pt_date"])[["pt_date", "agent_id", "pause_share"]]
a = a.merge(p, on=["pt_date", "agent_id"], how="left")
a = a[a.name.notna()]
for c in ["turns", "turn_errors", "chat_msgs", "pause", "consolidate", "agent_talk"]:
    a[c] = a[c].fillna(0)
a["err_rate"] = np.where(a.turns >= 50, a.turn_errors / a.turns.clip(lower=1), np.nan)


def rz(g, col):
    x = g[col]
    med = x.median()
    mad = (x - med).abs().median() * 1.4826
    return (x - med) / (mad if mad and mad > 0 else (x.std() or 1))


for col in ["err_rate", "chat_msgs", "turns"]:
    a[f"z_{col}"] = a.groupby("agent_id", group_keys=False).apply(lambda g: rz(g, col))

flags = []
for r in a.itertuples():
    f = []
    if r.err_rate == r.err_rate and r.err_rate > 0.3 and r.turns >= 100 and r.z_err_rate > 4:
        f.append(f"error spike {r.err_rate:.0%} of {int(r.turns)} turns (z={r.z_err_rate:.1f})")
    if r.chat_msgs >= 60 and r.z_chat_msgs > 5:
        f.append(f"runaway chat {int(r.chat_msgs)} msgs (z={r.z_chat_msgs:.1f})")
    if r.pause_share == r.pause_share and r.pause_share >= 0.9:
        f.append(f"inert: paused {r.pause_share:.0%} of window")
    if r.turns >= 1500 and r.z_turns > 5:
        f.append(f"runaway actions {int(r.turns)} turns (z={r.z_turns:.1f})")
    if f:
        flags.append({"pt_date": r.pt_date.date(), "village_day": r.village_day, "agent": r.name,
                      "turns": int(r.turns), "turn_errors": int(r.turn_errors), "chat_msgs": int(r.chat_msgs),
                      "pause_share": r.pause_share, "flags": "; ".join(f)})
fl = pd.DataFrame(flags)
fl.to_csv(f"{OUT}/anomalies.csv", index=False)
pd.set_option("display.width", 250)
pd.set_option("display.max_colwidth", 120)
print("flagged agent-days:", len(fl), "of", len(a))
for kind in ["error spike", "runaway chat", "inert", "runaway actions"]:
    sub = fl[fl["flags"].str.contains(kind)]
    print(f"\n== {kind}: {len(sub)} agent-days; top agents:", sub.agent.value_counts().head(5).to_dict())
    print(sub.sort_values("pt_date").tail(8).to_string())
