import duckdb
def con():
    c = duckdb.connect('/Users/ianmacdonald/code/grove-hackathon/data/village.duckdb', read_only=True)
    c.execute("SET memory_limit='2GB'; SET threads=2;")
    return c
