"""Replay edit_memory write/edit ops to reconstruct the agent's long-term memory over time; track presence of terms."""
import duckdb, json, sys, pandas as pd
O='/Users/ianmacdonald/code/grove-hackathon/analysis/delegation/'
con=duckdb.connect(); con.execute("SET memory_limit='2GB'; SET threads=2;")
ops=con.execute(f"select use_at, input, is_error from '{O}tool_calls.parquet' where tool='mcp__village__edit_memory' order by use_at").fetchall()
terms=sys.argv[1:] or ['shadow']
c=''; rows=[]; fails=0
for t,i,e in ops:
    j=json.loads(i); a=j.get('action')
    if e: continue
    if a=='write': c=j['content']
    elif 'old_string' in j:
        if j['old_string'] in c: c=c.replace(j['old_string'],j['new_string'],1)
        else: fails+=1
    else: continue
    rows.append(dict(t=t, op=a or 'edit', length=len(c), **{k: k.lower() in c.lower() for k in terms}))
df=pd.DataFrame(rows); df.to_csv(O+'memory_replay.csv',index=False)
print('ops',len(rows),'edit misses',fails)
for k in terms:
    d=df[k].astype(int).diff().fillna(df[k].astype(int))
    print(k, 'added at', list(df.t[d==1].astype(str).str[:16])[:8], ' removed at', list(df.t[d==-1].astype(str).str[:16])[:8])
print(df.length.describe())
