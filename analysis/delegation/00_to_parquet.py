import duckdb
D='/Users/ianmacdonald/code/grove-hackathon/data/'
O='/Users/ianmacdonald/code/grove-hackathon/analysis/delegation/'
con=duckdb.connect()
con.execute("SET memory_limit='2GB'; SET threads=2;")
con.execute(f"""
COPY (
 SELECT id, agent_id, sdk_session_id, message_type, message_subtype,
        CAST(created_at AS TIMESTAMP) AS created_at,
        content->>'parent_tool_use_id' AS parent_tool_use_id,
        content->>'uuid' AS uuid,
        content->>'session_id' AS content_session_id,
        CAST(content AS VARCHAR) AS content
 FROM read_json('{D}claude_code_messages.jsonl.gz', format='newline_delimited',
   columns={{id:'VARCHAR',agent_id:'VARCHAR',sdk_session_id:'VARCHAR',message_uuid:'VARCHAR',message_type:'VARCHAR',message_subtype:'VARCHAR',content:'JSON',created_at:'VARCHAR'}})
) TO '{O}cc_messages.parquet' (FORMAT PARQUET)
""")
con.execute(f"""
COPY (SELECT * FROM read_json('{D}claude_code_sessions.jsonl.gz', format='newline_delimited')) TO '{O}cc_sessions.parquet' (FORMAT PARQUET)
""")
print(con.execute(f"select message_type, count(*), count(parent_tool_use_id), min(created_at), max(created_at) from '{O}cc_messages.parquet' group by 1").fetchall())
