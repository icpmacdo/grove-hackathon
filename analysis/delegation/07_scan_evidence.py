"""For each 'scan clean/pass' claim, what evidence ran in the prior 10 min: a mechanical scan, a bare diff the model read, or nothing?
Also: claims of specific mechanical checks (zero-width chars) vs commands that could perform them."""
import duckdb, pandas as pd, re, json
O='/Users/ianmacdonald/code/grove-hackathon/analysis/delegation/'
v=duckdb.connect('/Users/ianmacdonald/code/grove-hackathon/data/village.duckdb', read_only=True); v.execute("SET memory_limit='2GB'; SET threads=2;")
con=duckdb.connect(); con.execute("SET memory_limit='2GB'; SET threads=2;")
claims=v.execute("""select created_at, id, content from chat where speaker='Opus 4.5 (Claude Code)' and created_at between '2026-03-05' and '2026-03-17'
  and regexp_matches(content, '(?i)(egg|motif|security)[^.\n]{0,40}(scan|check|test)|scan[^.\n]{0,30}(clean|pass)')""").df()
tc=con.execute(f"""select use_at, tool, input from '{O}tool_calls.parquet' where use_at between '2026-03-05' and '2026-03-17' and tool in ('Bash','mcp__village__bash')""").df()
tc['cmd']=tc.input.map(lambda s: json.loads(s).get('command',''))
MECH=re.compile(r'(?i)grep[^|;&]*(egg|easter|bunny|banned|eval)|forbidden|motif|scan[-_.]|scanner|security-check|BANNED')
ZW=re.compile(r'(?i)200b|200c|200d|feff|zero.?width|\\u20|\[\^\\x00|-P ')
DIFF=re.compile(r'(?:gh pr diff|git diff|git show)')
tc['mech']=tc.cmd.str.contains(MECH); tc['zw']=tc.cmd.str.contains(ZW); tc['diff']=tc.cmd.str.contains(DIFF)
rows=[]
for _,c in claims.iterrows():
    w=tc[(tc.use_at<=c.created_at)&(tc.use_at>c.created_at-pd.Timedelta('10min'))]
    ev='mechanical scan' if w.mech.any() else ('diff read by model only' if w['diff'].any() else 'no scan/diff command')
    rows.append(dict(created_at=c.created_at, msg_id=c.id, evidence=ev,
        claims_zero_width=bool(re.search(r'(?i)zero.?width',c.content)), zw_cmd=bool(w.zw.any()),
        text=c.content[:180].replace('\n',' ')))
r=pd.DataFrame(rows); r.to_csv(O+'scan_claim_evidence.csv',index=False)
print(len(r)); print(r.evidence.value_counts())
print(r.groupby(r.created_at.dt.date).evidence.value_counts().unstack(fill_value=0))
z=r[r.claims_zero_width]; print('zero-width claims', len(z), ' with a zero-width-capable command in prior 10 min', z.zw_cmd.sum())
print(z[['created_at','msg_id','evidence','text']].head(5).to_string())
print(r[r.evidence=='no scan/diff command'][['created_at','msg_id','text']].to_string())
