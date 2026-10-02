"""Extract era-D chat (2026-07-01..2026-09-20) to a local parquet for fast regex work."""
from db import connect, OUT
con = connect()
con.execute(f"""COPY (SELECT id, created_at, speaker_type, speaker, room, content, village_goal
  FROM chat WHERE created_at >= '2026-07-01' AND created_at < '2026-09-20' ORDER BY created_at)
  TO '{OUT}/chat_eraD.parquet' (FORMAT parquet)""")
print(con.execute(f"SELECT count(*), sum(length(content)) FROM '{OUT}/chat_eraD.parquet'").fetchall())
