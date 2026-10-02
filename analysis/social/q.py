"""Tiny query helper: uv run python analysis/social/q.py "SQL1;; SQL2" """
import duckdb, sys
import pandas as pd
con = duckdb.connect('/Users/ianmacdonald/code/grove-hackathon/data/village.duckdb', read_only=True)
con.execute("SET memory_limit='2GB'; SET threads=2;")
pd.set_option('display.width', 250); pd.set_option('display.max_columns', 30)
pd.set_option('display.max_colwidth', 220); pd.set_option('display.max_rows', 300)
q = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
for stmt in [s for s in q.split(';;') if s.strip()]:
    print(con.execute(stmt).df()); print()
