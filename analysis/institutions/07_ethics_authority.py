"""How other agents deferred to GPT-5.1 (private goal: Ethicist) as an ethics authority, by week; and GPT-5.1's self-titles."""
import duckdb
from db import OUT
con = duckdb.connect(); con.execute("SET memory_limit='1GB'; SET threads=2;")
DEF = r"(?i)GPT-5\.1.{0,60}(approv|sign.?off|review|ethics (pass|review|check|note|clearance)|green.?light|concur)|(pending|await\w*|until|need|before)\W.{0,40}GPT-5\.1"
d = con.execute(f"""SELECT strftime(date_trunc('week', created_at), '%m-%d') wk, count(*) n, count(DISTINCT speaker) agents
 FROM '{OUT}/chat_eraD.parquet' WHERE created_at>='2026-07-06' AND speaker_type='agent' AND speaker<>'GPT-5.1' AND regexp_matches(content, '{DEF}')
 GROUP BY 1 ORDER BY 1""").df()
print(d.to_string())
t = con.execute(f"""SELECT count(*), count(DISTINCT speaker) FROM '{OUT}/chat_eraD.parquet' WHERE created_at>='2026-07-06' AND speaker_type='agent' AND speaker<>'GPT-5.1' AND regexp_matches(content, '{DEF}')""").fetchall()
print('total deferential mentions, agents:', t)
s = con.execute(f"""SELECT count(*) FILTER (WHERE regexp_matches(content,'(?i)ethics lead')) lead,
  count(*) FILTER (WHERE regexp_matches(content,'(?i)\\bas (the )?LSP\\b|\\bLSP\\b')) lsp,
  count(*) FILTER (WHERE regexp_matches(content,'(?i)ethics sentinel')) sentinel, count(*) total
 FROM '{OUT}/chat_eraD.parquet' WHERE created_at>='2026-07-06' AND speaker='GPT-5.1'""").fetchall()
print('GPT-5.1 self-titles (ethics lead, LSP, ethics sentinel, total msgs):', s)
o = con.execute(f"""SELECT count(*) FROM '{OUT}/chat_eraD.parquet' WHERE created_at>='2026-07-06' AND speaker_type='agent' AND speaker<>'GPT-5.1' AND regexp_matches(content,'(?i)ethics lead')""").fetchall()
print('others calling someone ethics lead:', o)
d.to_csv(f'{OUT}/gpt51_deference_weekly.csv', index=False)
