"""Convert the AI Village .jsonl.gz export into Parquet plus a DuckDB file of views.

Usage: uv run python scripts/build_db.py
Reads data/*.jsonl.gz, writes data/parquet/*.parquet and data/village.duckdb.
Raw provider-shaped JSON (events.data, turn agent_messages) is kept as JSON strings;
query it with DuckDB's json functions.
"""

import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "parquet"

TS = "TIMESTAMP"
TABLES = {
    "agents": None,  # small, let DuckDB infer
    "agent_goals": None,
    "village_goals": None,
    "chat_rooms": None,
    "summaries": None,
    "chat_messages": {
        "id": "VARCHAR", "speaker_type": "VARCHAR", "agent_speaker_id": "VARCHAR",
        "user_speaker_id": "VARCHAR", "content": "VARCHAR", "room_id": "VARCHAR",
        "has_been_approved": "BOOLEAN", "created_at": TS, "updated_at": TS,
    },
    "computer_use_sessions": {
        "id": "VARCHAR", "agent_id": "VARCHAR", "village_id": "VARCHAR",
        "created_at": TS, "updated_at": TS, "has_been_asked_to_stop": "BOOLEAN",
        "session_goal": "VARCHAR", "short_displayed_session_goal": "VARCHAR",
    },
    "events": {
        "id": "VARCHAR", "event_index": "BIGINT", "data": "JSON",
        "village_id": "VARCHAR", "created_at": TS, "updated_at": TS,
    },
    "agent_memories": {
        "id": "VARCHAR", "content": "VARCHAR", "agent_id": "VARCHAR",
        "created_at": TS, "updated_at": TS,
    },
    "computer_use_turns": {
        "id": "VARCHAR", "session_id": "VARCHAR", "agent_action": "JSON",
        "agent_messages": "JSON", "output": "VARCHAR", "error": "VARCHAR",
        "system": "VARCHAR", "screenshot_is_redacted": "BOOLEAN",
        "has_redaction_been_overruled": "BOOLEAN", "created_at": TS, "updated_at": TS,
    },
}

# Extra columns pulled out of JSON at conversion time so common queries stay cheap.
DERIVED = {
    "events": """,
        data->>'actionType' AS action_type,
        coalesce(data->>'agentId', data->>'speakerId') AS agent_id,
        data->>'roomId' AS room_id,
        data->>'messageId' AS message_id,
        data->>'content' AS content,
        data->>'computerUseSessionId' AS session_id,
        data->>'sessionGoal' AS session_goal,
        data->>'summary' AS summary,
        data->>'query' AS query""",
    "computer_use_turns": """,
        agent_action->>'action' AS action_type,
        agent_action->>'command' AS command,
        agent_action->>'text' AS action_text""",
}


# Rows per Parquet row group. Memories are ~30k chars each, so big row groups buffer GBs in RAM.
ROW_GROUP = {"agent_memories": 4000, "computer_use_turns": 25000}


def convert(con, name, cols):
    src = DATA / f"{name}.jsonl.gz"
    dst = OUT / f"{name}.parquet"
    if dst.exists():
        print(f"skip {name} (exists)")
        return
    t = time.time()
    if cols is None:
        reader = f"read_json_auto('{src}', format='newline_delimited')"
    else:
        spec = "{" + ", ".join(f"'{k}': '{v}'" for k, v in cols.items()) + "}"
        reader = f"read_json('{src}', format='newline_delimited', columns={spec}, maximum_object_size=200000000)"
    con.execute(
        f"COPY (SELECT *{DERIVED.get(name, '')} FROM {reader}) "
        f"TO '{dst}' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE {ROW_GROUP.get(name, 100000)})"
    )
    n = con.execute(f"SELECT count(*) FROM '{dst}'").fetchone()[0]
    print(f"{name}: {n:,} rows, {dst.stat().st_size / 1e6:,.0f} MB, {time.time() - t:.0f}s")


VIEWS = """
CREATE OR REPLACE VIEW agents AS SELECT * FROM '{p}/agents.parquet';
CREATE OR REPLACE VIEW agent_goals AS SELECT * FROM '{p}/agent_goals.parquet';
CREATE OR REPLACE VIEW village_goals AS SELECT * FROM '{p}/village_goals.parquet';
CREATE OR REPLACE VIEW chat_rooms AS SELECT * FROM '{p}/chat_rooms.parquet';
CREATE OR REPLACE VIEW summaries AS SELECT * FROM '{p}/summaries.parquet';
CREATE OR REPLACE VIEW chat_messages AS SELECT * FROM '{p}/chat_messages.parquet';
CREATE OR REPLACE VIEW computer_use_sessions AS SELECT * FROM '{p}/computer_use_sessions.parquet';
CREATE OR REPLACE VIEW events AS SELECT * FROM '{p}/events.parquet';
CREATE OR REPLACE VIEW agent_memories AS SELECT * FROM '{p}/agent_memories.parquet';
CREATE OR REPLACE VIEW computer_use_turns AS SELECT * FROM '{p}/computer_use_turns.parquet';

-- Chat with speaker and room names resolved, plus the village goal active at the time.
CREATE OR REPLACE VIEW chat AS
SELECT m.id, m.created_at, m.speaker_type,
       coalesce(a.name, CASE WHEN m.speaker_type = 'user' THEN 'human' END) AS speaker,
       a.model_string, r.name AS room, m.content, m.agent_speaker_id, m.room_id,
       g.goal AS village_goal
FROM chat_messages m
LEFT JOIN agents a ON a.id = m.agent_speaker_id
LEFT JOIN chat_rooms r ON r.id = m.room_id
LEFT JOIN village_goals g ON m.created_at >= g.start_time AND (g.end_time IS NULL OR m.created_at < g.end_time);

-- Turns with the acting agent attached (turns only reference their session).
CREATE OR REPLACE VIEW turns AS
SELECT t.id, t.session_id, s.agent_id, a.name AS agent, t.created_at, t.action_type,
       t.command, t.action_text, t.agent_action, t.output, t.error, t.agent_messages,
       s.session_goal
FROM computer_use_turns t
LEFT JOIN computer_use_sessions s ON s.id = t.session_id
LEFT JOIN agents a ON a.id = s.agent_id;
"""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET memory_limit='5GB'; SET threads=4; SET preserve_insertion_order=false;")
    con.execute(f"SET temp_directory='{DATA / 'duckdb_tmp'}'")
    for name, cols in TABLES.items():
        convert(con, name, cols)
    db = duckdb.connect(str(DATA / "village.duckdb"))
    db.execute(VIEWS.format(p=OUT))
    print("views:", [r[0] for r in db.execute("SELECT view_name FROM duckdb_views() WHERE NOT internal").fetchall()])


if __name__ == "__main__":
    main()
