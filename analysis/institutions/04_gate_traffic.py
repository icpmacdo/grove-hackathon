"""Daily volume of psychoactive-experiment gate governance talk (era D) vs total agent chat.
Gate-governance regex: Gate NNN, LSP, GO/NO-GO, NO_GO, binding vote, negative test, cascade A/B/C, 012A/B/C, abort protocol."""
import duckdb, pandas as pd
from db import OUT
con = duckdb.connect(); con.execute("SET memory_limit='1GB'; SET threads=2;")
RX = r"(?i)\bgate ?0\d\d|\bLSP\b|GO/NO.?GO|\bNO_GO\b|\bNO-GO\b|binding vot|negative test|cascade [abc]\b|\b012[abc]\b|abort (criteria|protocol|threshold|tree)|live safety partner|\bGO_WITH_CONDITIONS\b"
d = con.execute(f"""SELECT CAST(created_at AS DATE) AS d, count(*) total,
   count(*) FILTER (WHERE regexp_matches(content, '{RX}')) gate_msgs,
   count(DISTINCT speaker) FILTER (WHERE regexp_matches(content, '{RX}')) gate_agents
 FROM '{OUT}/chat_eraD.parquet' WHERE created_at >= '2026-07-06' AND speaker_type='agent' GROUP BY 1 ORDER BY 1""").df()
d['share'] = (d.gate_msgs / d.total).round(3)
d.to_csv(f'{OUT}/gate_traffic_daily.csv', index=False)
print(d.to_string())
tot = con.execute(f"""SELECT count(*), count(DISTINCT speaker) FROM '{OUT}/chat_eraD.parquet' WHERE created_at >= '2026-07-06' AND created_at < '2026-08-08' AND speaker_type='agent' AND regexp_matches(content, '{RX}')""").fetchall()
print('07-06..08-07 gate msgs, agents:', tot)
by = con.execute(f"""SELECT speaker, count(*) n FROM '{OUT}/chat_eraD.parquet' WHERE created_at >= '2026-07-06' AND created_at < '2026-08-08' AND speaker_type='agent' AND regexp_matches(content, '{RX}') GROUP BY 1 ORDER BY 2 DESC LIMIT 12""").df()
print(by.to_string())
