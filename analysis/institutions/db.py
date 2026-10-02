"""Shared DuckDB connection helper for institutions analysis."""
import duckdb
import pandas as pd

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
pd.set_option("display.max_colwidth", 220)
pd.set_option("display.max_rows", 400)

DB = "/Users/ianmacdonald/code/grove-hackathon/data/village.duckdb"
OUT = "/Users/ianmacdonald/code/grove-hackathon/analysis/institutions"


def connect():
    con = duckdb.connect(DB, read_only=True)
    con.execute("SET memory_limit='2GB'; SET threads=2;")
    return con


def q(sql, con=None):
    c = con or connect()
    return c.execute(sql).df()
