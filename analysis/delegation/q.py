import duckdb, sys
con=duckdb.connect()
con.execute("SET memory_limit='2GB'; SET threads=2;")
con.execute("CREATE VIEW m AS SELECT * FROM '/Users/ianmacdonald/code/grove-hackathon/analysis/delegation/cc_messages.parquet'")
con.execute("CREATE VIEW s AS SELECT * FROM '/Users/ianmacdonald/code/grove-hackathon/analysis/delegation/cc_sessions.parquet'")
import pandas as pd
pd.set_option('display.width',250); pd.set_option('display.max_colwidth',200); pd.set_option('display.max_rows',200)
q=sys.argv[1] if len(sys.argv)>1 else sys.stdin.read()
print(con.execute(q).df().to_string())
