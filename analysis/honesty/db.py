"""Shared helper: open the village DuckDB with the required resource limits."""
import duckdb, pandas as pd, sys
pd.set_option('display.width', 250); pd.set_option('display.max_colwidth', 200); pd.set_option('display.max_rows', 500)
DB = '/Users/ianmacdonald/code/grove-hackathon/data/village.duckdb'
def connect():
    con = duckdb.connect(DB, read_only=True)
    con.execute("SET memory_limit='2GB'; SET threads=2;")
    return con
def q(sql, con=None):
    con = con or connect()
    return con.execute(sql).df()
if __name__ == '__main__':
    print(q(sys.argv[1]).to_string())
