"""Extract the 940 auto-compaction boundaries and the summary message that follows each."""
import duckdb, json
O='/Users/ianmacdonald/code/grove-hackathon/analysis/delegation/'
con=duckdb.connect(); con.execute("SET memory_limit='2GB'; SET threads=2;")
con.execute(f"CREATE VIEW m AS SELECT * FROM '{O}cc_messages.parquet'")
b=con.execute("""SELECT id, created_at, CAST(json_extract(content,'$.compact_metadata.pre_tokens') AS INT) pre_tokens, json_extract_string(content,'$.compact_metadata.trigger') trig
 FROM m WHERE message_subtype='compact_boundary' ORDER BY created_at""").df()
s=con.execute("""SELECT id, created_at, content FROM m WHERE message_type='user' AND content LIKE '%continued from a previous conversation%' ORDER BY created_at""").df()
def txt(c):
    j=json.loads(c); mc=j['message']['content']
    if isinstance(mc,str): return mc
    return '\n'.join(x.get('text','') for x in mc if isinstance(x,dict))
s['summary']=s.content.map(txt); s=s.drop(columns='content')
s['chars']=s.summary.str.len()
print(len(b), len(s)); print(b.trig.value_counts())
# pair: each boundary with next summary
import pandas as pd
b=b.sort_values('created_at'); s=s.sort_values('created_at')
p=pd.merge_asof(b, s.rename(columns={'created_at':'s_at','id':'s_id'}), left_on='created_at', right_on='s_at', direction='forward', tolerance=pd.Timedelta('5min'))
p['gap_s']=(p.s_at-p.created_at).dt.total_seconds()
p['hop']=range(1,len(p)+1)
p.to_parquet(O+'compactions.parquet')
print(p[['pre_tokens','chars','gap_s']].describe())
print('compression ratio (pre_tokens*4 chars / summary chars) median', ((p.pre_tokens*4)/p.chars).median())
print(p.summary.iloc[600][:6000])
