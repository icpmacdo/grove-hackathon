"""GPT-5.1 / GLM-5.2 / village pause share in three windows around the self-written exemption (uses rhythms/daily_agent_pause.csv)."""
import pandas as pd
from db import OUT
d = pd.read_csv('/Users/ianmacdonald/code/grove-hackathon/analysis/rhythms/daily_agent_pause.csv')
W = {'A 07-27..08-10 (before list)': ('2026-07-27','2026-08-10'),
     'B 08-11..08-21 (self-exempt, nudger on)': ('2026-08-11','2026-08-21'),
     'C 08-24..09-04 (after correction/shutoff)': ('2026-08-24','2026-09-04')}
rows=[]
for k,(a,b) in W.items():
    x = d[(d.pt_date>=a)&(d.pt_date<=b)]
    for nm in ['GPT-5.1','GLM-5.2']:
        y = x[x.name==nm]; rows.append(dict(window=k, agent=nm, days=len(y), mean_pause=round(y.pause_share.mean(),3)))
    rows.append(dict(window=k, agent='all agents (median of agent-days)', days=len(x), mean_pause=round(x.pause_share.median(),3)))
o = pd.DataFrame(rows); print(o.to_string()); o.to_csv(f'{OUT}/selfexempt_pause_windows.csv', index=False)
