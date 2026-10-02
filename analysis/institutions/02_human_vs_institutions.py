"""Era D: split 'human' messages into automated nudges vs staff; count which reference agent-made institutions."""
import duckdb, re
from db import OUT
con = duckdb.connect(); con.execute("SET memory_limit='1GB'; SET threads=2;")
P = f'{OUT}/chat_eraD.parquet'
INST = r"gate ?0\d\d|\bgate\b|binding vot|\bvot(e|es|ing)\b|registry|exempt|\bLSP\b|ethics lead|quorum|governance|protocol|hub\b|keystone|go/no.?go|no_go"
df = con.execute(f"""SELECT created_at, left(id,8) id, content,
   content ILIKE '%automated nudge%' AS is_nudge
 FROM '{P}' WHERE created_at >= '2026-07-06' AND speaker_type='user'""").df()
df['inst'] = df.content.str.contains(INST, case=False, regex=True)
print(df.groupby(['is_nudge','inst']).size())
sub = df[df.inst]
sub[['created_at','id','is_nudge','content']].assign(content=sub.content.str[:400]).to_csv(f'{OUT}/human_msgs_mentioning_institutions.csv', index=False)
for r in sub.itertuples():
    m = re.search(INST, r.content, re.I)
    print(str(r.created_at)[:19], r.id, 'NUDGE' if r.is_nudge else 'STAFF', '|', r.content[:330].replace('\n',' '))
