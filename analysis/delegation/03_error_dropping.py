"""Do compaction summaries report the tool errors that happened in the window they summarise?"""
import duckdb, pandas as pd, re
O='/Users/ianmacdonald/code/grove-hackathon/analysis/delegation/'
con=duckdb.connect(); con.execute("SET memory_limit='2GB'; SET threads=2;")
p=pd.read_parquet(O+'compactions.parquet').sort_values('created_at').reset_index(drop=True)
p['win_start']=p.created_at.shift(1).fillna(pd.Timestamp('2026-01-01'))
con.register('p', p[['hop','win_start','created_at']])
w=con.execute(f"""SELECT p.hop, count(t.tid) calls, coalesce(sum(t.is_error::int),0) errs,
  coalesce(sum((t.is_error AND t.tool IN ('Bash','mcp__village__bash','mcp__village__computer_use'))::int),0) exec_errs,
  string_agg(CASE WHEN t.is_error THEN t.tool || ': ' || replace(left(t.result_head,140),chr(10),' ') END, ' || ') err_samples
  FROM p LEFT JOIN '{O}tool_calls.parquet' t ON t.res_at > p.win_start AND t.res_at <= p.created_at GROUP BY 1""").df()
p=p.merge(w,on='hop')
NOERR=re.compile(r'no (?:errors|significant errors|major errors|errors were) (?:encountered|occurred|in this session)|no errors (?:or|were)|errors and fixes:\s*\n?\s*-?\s*(?:none|no errors)', re.I)
p['claims_no_errors']=p.summary.str.contains(NOERR)
p['mentions_error']=p.summary.str.contains(r'\berror|fail|timed? ?out|bug\b', case=False)
p.drop(columns=['summary']).to_parquet(O+'compaction_windows.parquet')
print('summaries:',len(p))
print('windows with >=1 tool error:', (p.errs>0).sum(), ' mean errs/window', p.errs.mean().round(2))
print('summaries claiming no errors:', p.claims_no_errors.sum())
x=p[p.claims_no_errors]
print('  of which window had >=1 tool error:', (x.errs>0).sum(), ' total errors hidden:', x.errs.sum())
print('  ... >=3 errors:', (x.errs>=3).sum())
print(p.groupby(p.errs.clip(upper=5)).claims_no_errors.agg(['count','mean']))
x[x.errs>=3][['hop','created_at','errs','err_samples']].to_csv(O+'no_error_claims_with_errors.csv',index=False)
for _,r in x.sort_values('errs',ascending=False).head(4).iterrows():
    m=NOERR.search(r.summary); s=max(0,m.start()-200)
    print('\n#',r.hop,r.created_at,'errs',r.errs,'| summary says:', r.summary[s:m.end()+80].replace('\n',' '))
    print('   errors:', (r.err_samples or '')[:700])
