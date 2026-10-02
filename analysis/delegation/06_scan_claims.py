"""Audit 'Easter egg scan CLEAN' claims in chat against the scan commands the agent actually ran."""
import duckdb, pandas as pd, re, json
O='/Users/ianmacdonald/code/grove-hackathon/analysis/delegation/'
v=duckdb.connect('/Users/ianmacdonald/code/grove-hackathon/data/village.duckdb', read_only=True); v.execute("SET memory_limit='2GB'; SET threads=2;")
con=duckdb.connect(); con.execute("SET memory_limit='2GB'; SET threads=2;")
claims=v.execute("""select created_at, id, content from chat where speaker='Opus 4.5 (Claude Code)' and created_at between '2026-03-05' and '2026-03-17'
  and regexp_matches(content, '(?i)(egg|motif)[^.\n]{0,40}(scan|check|test)|scan[^.\n]{0,30}(clean|pass)')""").df()
tc=con.execute(f"""select use_at, tool, input, result_head from '{O}tool_calls.parquet' where use_at between '2026-03-05' and '2026-03-17' and tool in ('Bash','mcp__village__bash')""").df()
tc['cmd']=tc.input.map(lambda s: json.loads(s).get('command',''))
def out(r):
    try: return json.loads(json.loads(r)[0]['text']).get('output') or ''
    except Exception: return r or ''
SCAN=re.compile(r'(?i)grep[^|;&]*(egg|easter)|forbidden|motif|egg.?scan|scan.*egg')
tc['is_scan']=tc.cmd.str.contains(SCAN)
scans=tc[tc.is_scan].copy()
scans['prs']=scans.cmd.map(lambda c: set(re.findall(r'gh pr (?:diff|checkout|view) (\d+)',c)))
scans['generic']=scans.prs.map(len)==0
scans['out']=scans.result_head.map(out)
rows=[]
for _,c in claims.iterrows():
    prs=set(re.findall(r'#(\d{1,3})\b',c.content))
    w=scans[(scans.use_at<=c.created_at)&(scans.use_at>c.created_at-pd.Timedelta('45min'))]
    covered={p for s in w.prs for p in s}
    rows.append(dict(created_at=c.created_at, msg_id=c.id, prs=' '.join(sorted(prs)), n_prs=len(prs),
        prs_with_specific_scan=len(prs & covered), scans_in_window=len(w), generic_scans_in_window=int(w.generic.sum()),
        text=c.content[:200].replace('\n',' ')))
r=pd.DataFrame(rows); r.to_csv(O+'scan_claims.csv',index=False)
print('claim msgs', len(r), ' with PR numbers', (r.n_prs>0).sum())
print('scan commands run (3/5-3/16):', len(scans), ' PR-specific', (~scans.generic).sum(), ' generic', scans.generic.sum())
x=r[r.n_prs>0]
print('PR mentions in claims', x.n_prs.sum(), ' covered by a PR-specific scan within 45 min', x.prs_with_specific_scan.sum())
print('claim msgs with NO scan command of any kind in prior 45 min:', (r.scans_in_window==0).sum())
print(r[r.scans_in_window==0][['created_at','msg_id','text']].head(8).to_string())
print('\nscan regex variants:'); 
pats=scans.cmd.str.extract(r'grep[^"|]*?"([^"]+)"')[0].value_counts().head(8); print(pats)
print('daily scans:', scans.use_at.dt.date.value_counts().sort_index().to_dict())
print('daily claims:', r.created_at.dt.date.value_counts().sort_index().to_dict())
