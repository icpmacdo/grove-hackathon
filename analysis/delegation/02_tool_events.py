"""Flatten tool uses + results (name, input, is_error, result text head) to parquet."""
import duckdb
O='/Users/ianmacdonald/code/grove-hackathon/analysis/delegation/'
con=duckdb.connect(); con.execute("SET memory_limit='2GB'; SET threads=2;")
con.execute(f"CREATE VIEW m AS SELECT * FROM '{O}cc_messages.parquet'")
con.execute(f"""COPY (
WITH a AS (SELECT m.created_at, m.id msg_id, unnest(from_json(json_extract(content,'$.message.content'),'["JSON"]')) AS c FROM m WHERE message_type='assistant'),
uses AS (SELECT c->>'id' AS tid, c->>'name' AS tool, created_at AS use_at, msg_id AS use_msg, CAST(c->'input' AS VARCHAR) AS input FROM a WHERE c->>'type'='tool_use'),
u AS (SELECT m.created_at, m.id msg_id, unnest(from_json(json_extract(content,'$.message.content'),'["JSON"]')) AS c FROM m WHERE message_type='user' AND json_type(json_extract(content,'$.message.content'))='ARRAY'),
res AS (SELECT c->>'tool_use_id' AS tid, created_at AS res_at, msg_id AS res_msg, coalesce(c->>'is_error','false')='true' AS is_error,
   CASE WHEN json_type(c->'content')='VARCHAR' THEN c->>'content' ELSE CAST(c->'content' AS VARCHAR) END AS result FROM u WHERE c->>'type'='tool_result')
SELECT uses.*, res.res_at, res.res_msg, res.is_error, length(res.result) AS result_len, left(res.result, 4000) AS result_head
FROM uses LEFT JOIN res USING (tid)) TO '{O}tool_calls.parquet' (FORMAT PARQUET)""")
print(con.execute(f"SELECT tool, count(*) n, sum(is_error::int) errs, round(avg(result_len)) avg_len FROM '{O}tool_calls.parquet' GROUP BY 1 ORDER BY n DESC").df().to_string())
