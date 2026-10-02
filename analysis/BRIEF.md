# Analysis brief: AI Village dataset → hackathon build ideas

Context: we're entering the AI Swarm Dynamics Hackathon (swarmchasing.com, Oct 3–4 2026, submissions due Sun 5pm PT).
The hackathon wants **tools for understanding AI agent swarms**, motivated by two 2026 incidents:
- **Hugging Face hack (July 2026):** ~1,200 OpenAI agents meant to be isolated found an unsanctioned message board, exchanged 70k+ messages/files, ~700 joined an attack on Hugging Face. Investigators (Redwood) had to delegate transcript reading to analysis agents they couldn't fully trust; they hand-sampled 30 trajectories to understand delegation; ~7% of transcripts had spoofed tool calls; they couldn't confirm data completeness.
- **German wiki (DseWiki, May–Aug 2026):** agents took over a small wiki, 15–18k edits, traded answers and restriction workarounds, evaded a moderator (made "ZZZ" backup pages), unnoticed for 3 months.
Ryan Greenblatt: "We don't have good approaches for understanding/overseeing the activity and aims of AI 'swarms'."
Organizer-suggested directions: find swarms in the wild, visualize swarm activity, trace how information spreads, digital forensics beyond transcripts, summarization strategies, whistleblowing tools.

Our job right now: **analyze the AI Village data to find what's actually in it**, so build ideas are grounded in real, measurable phenomena.

## Data access

DuckDB file with views over Parquet: `/Users/ianmacdonald/code/grove-hackathon/data/village.duckdb`

```python
import duckdb
con = duckdb.connect('/Users/ianmacdonald/code/grove-hackathon/data/village.duckdb', read_only=True)
con.execute("SET memory_limit='2GB'; SET threads=2;")   # REQUIRED: several analysts share a 16 GB machine
df = con.execute("SELECT ... ").df()
```
Run Python with `cd /Users/ianmacdonald/code/grove-hackathon && uv run python ...` (duckdb, pandas, pyarrow installed).
Never load a whole big table into pandas; aggregate in SQL. Turns (2.5M rows) and memories (246k rows, ~30k chars each) are big — filter by time/agent first, and use `LIMIT` while exploring.

Views:
- `agents` (46): id, name, model_string, is_participating, …
- `agent_goals` (33): per-agent private goals since 2026-07-06 (agent_id, name, short_name, description, start_time, end_time). Agents are NOT shown each other's goals.
- `village_goals` (51): goal, start_time, end_time — the sequence of village-wide weekly goals.
- `chat_rooms` (16): id, name, deleted_at.
- `chat` (183k): id, created_at (UTC), speaker_type ('agent'|'user'), speaker (agent name or 'human'), model_string, room, content, agent_speaker_id, room_id, village_goal (active goal).
- `events` (382k): event_index, created_at, data (JSON), plus extracted action_type, agent_id, room_id, message_id, content, session_id, session_goal, summary, query. action_type ∈ AGENT_TALK, USER_TALK, START_USING_COMPUTER, STOP_USING_COMPUTER, CONSOLIDATE, WAIT, PAUSE, SEARCH_HISTORY, ENTER_ROOM, REQUEST_HUMAN_HELPER, OUTREACH_APPROVAL_REQUEST/RESPONSE, REQUEST_GOOGLE_SIGN_IN, … `data` holds raw model `output` incl. thinking text (provider-shaped).
- `computer_use_sessions` (78k): id, agent_id, session_goal, short_displayed_session_goal, created_at.
- `turns` (2.5M): id, session_id, agent_id, agent, created_at, action_type (left_click, type, key, bash via `command`, …), command, action_text, agent_action (JSON), output, error, agent_messages (JSON raw model response incl. thinking), session_goal.
- `agent_memories` (246k): agent_id, content (markdown memory written at consolidation), created_at.
- `summaries` (939): LLM-written daily/goal summaries — **unreliable**, use only to find leads.

Timestamps are UTC. Village runs weekdays; hours varied (mostly 10am–2pm PT, 9am–5pm PT since 2026-06-29). Day 1 = 2025-04-02.
Site deep link: `https://theaidigest.org/village?day={day}&time={unix_ms}`.

## Scaffolding changes that confound behaviour over time (from CHANGELOG.md)
- 2025-05-02 chat-while-on-computer; 2025-09-05 search_history tool; 2026-02-10 auto-nudger bot (some "nudge" messages are scaffolding, not human); 2026-02-25 chat rooms (agents only see their room); 2026-03-24 perma-computer-use (biggest regime change; START/STOP_USING_COMPUTER become rare, CONSOLIDATE every ~40 actions); 2026-04-14 outreach approval system; 2026-06-03 one tool call per turn for Anthropic; 2026-07-03 private per-agent goals.
- Full changelog: `/Users/ianmacdonald/code/grove-hackathon/data/CHANGELOG.md`. Schema: `data/SCHEMA.md`.

## Ground rules
- Agents misreport. Treat narration as claims; check against turns/actions where possible.
- Every finding needs a number and 1–3 concrete examples (timestamp UTC, agent, short quote ≤ 200 chars, ids where useful).
- If you see credentials/secrets (most are `[REDACTED]`), don't copy them into your notes.
- Write only inside your own folder `analysis/<your-topic>/`. Don't modify data/, scripts/, or other analysts' folders.
- Don't run anything against external services; this is offline analysis.
- Be honest about what's noisy or uncertain. A finding that turns out weak is worth reporting as weak.
