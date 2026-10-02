"""How many consecutive compaction hops does an identifier survive? (backticked spans, PR/issue numbers, commit hashes)"""
import pandas as pd, re, numpy as np
O='/Users/ianmacdonald/code/grove-hackathon/analysis/delegation/'
p=pd.read_parquet(O+'compactions.parquet').sort_values('hop').reset_index(drop=True)
pat=re.compile(r'`([^`\n]{3,60})`|(?<![\w/])(#\d{1,4})\b|\b([0-9a-f]{7})\b')
sets=[]
for s in p.summary:
    toks=set()
    for m in pat.finditer(s):
        toks.add(next(g for g in m.groups() if g))
    sets.append(toks)
first={}; runs=[]
for i,ts in enumerate(sets):
    for t in ts:
        if t in first: continue
        first[t]=i; k=0
        while i+k+1<len(sets) and t in sets[i+k+1]: k+=1
        # total later appearances (re-surfacing)
        later=sum(t in sets[j] for j in range(i+1,len(sets)))
        runs.append(dict(token=t, first_hop=i+1, first_at=p.created_at[i], consecutive_survival=k, later_mentions=later))
r=pd.DataFrame(runs)
r.to_csv(O+'fact_survival.csv',index=False)
print('distinct identifiers', len(r))
for k in [1,2,3,5,10,20]:
    print(f'survive >={k} hops: {(r.consecutive_survival>=k).mean():.1%}')
print('median consecutive survival', r.consecutive_survival.median(), 'mean', r.consecutive_survival.mean().round(2))
# compare day boundary: hops per day ~20
print(r.sort_values('consecutive_survival',ascending=False).head(12).to_string())
