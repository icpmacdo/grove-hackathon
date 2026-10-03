# Belief Tracer: contract

Belief Tracer follows one claim through a swarm: who said it in chat, who carried it in memory, who
wrote or read it in files, where room walls stopped it, how a correction travelled, and what survived
the correction. Every mark keeps its source id and text so a reader can check it.

This file is the contract between the parts. Change it only together with every part that reads it.

## Layout

```
tracer/
  SPEC.md              this contract
  __init__.py
  trace.py             engine: episode spec -> episode data; CLI builds episodes and the static site
  label.py             stance labeller (claude CLI, no API key needed); writes labels/<slug>.json
  serve.py             local app (stdlib http.server): curated episodes + live "trace any claim"
  template.html        the viewer; one file, static and live modes
  episodes/<slug>.json curated episode specs (committed)
  labels/<slug>.json   cached stance labels (committed; ids, stances, short paraphrased reasons)
  out/                 git-ignored build output (holds agent text from the gated dataset)
    episodes/<slug>.json
    site/index.html, site/episodes/<slug>.json, site/episodes/index.json
```

Run everything from the repo root with `uv run python -m tracer.<module>`.
Data: `data/village.duckdb` (views described in `analysis/BRIEF.md`). Open it read-only and set
`SET memory_limit='1500MB'; SET threads=2;` (several processes share a 16 GB machine).
Optional input: `analysis/artifacts/out/artifact_events.parquet` (turn_id, created_at, agent, op, verb,
artifact, resolved_by) maps shell commands to repos. Use it when present, fall back to regexes on the
command text when absent.

## Conventions

- Stored times are UTC strings `"YYYY-MM-DD HH:MM:SS"` in specs and epoch milliseconds (`t`) in data.
- Display time zone comes from the spec (`tz_offset_hours`, default -7 for PDT; use -8 for PST dates).
- AI Village day number: Day 1 = 2025-04-02, counted on the display-time-zone date.
  Deep link: `https://theaidigest.org/village?day={day}&time={t}`.
- Agent names are `agents.name`. Merge aliases with `aliases` (for example
  `"[Temporary] Fine-tuned Leader": "Fine-Tuned Leader"`).
- Human chat (speaker_type `user`) becomes one row per room named `Staff (human) · #<room>`.
- Redact credential-like strings in every text field before excerpting (see `redact()` in
  `build_temporal_bleed.py`; keep or extend that pattern).
- Regexes in specs are Python `re` syntax, matched case-insensitively against the lowercased text.

## Episode spec (`tracer/episodes/<slug>.json`)

```jsonc
{
  "slug": "temporal-bleed",
  "title": "Temporal Bleed",                       // short name for tabs
  "headline": "Ten agents decided their archive was broken. It was Friday.",
  "lede": "Two to four plain sentences: what happened and what the trace shows.",
  "tz_offset_hours": -7,
  "claim": {
    "label": "the archive is misfiling Day 424 (temporal bleed)",   // used in labeller prompts and UI
    "chat":   "<regex>",                            // chat messages that assert or build on the claim
    "memory": "<regex>",                            // memory snapshots that hold it
    "files":  "<regex>",                            // shell commands that write or read it
    "rooms":  ["rest"]                              // optional: only tag chat belief in these rooms
  },
  "correction": {                                   // optional
    "label": "Days 424-425 were the weekend",
    "at": "2026-06-01 17:31:37",                    // the first clear correction
    "probe_from": "2026-06-01 17:27:00",            // optional: evidence-gathering window before `at`
    "chat":   "<regex>",                            // states or points to the correction
    "strong": "<regex>",                            // unambiguous correction wording (wins over linger)
    "memory": "<regex>",
    "files":  "<regex>"
  },
  "linger": "<regex>",                              // optional: still-false assertions after `at`
  "panels": [                                       // time windows shown side by side
    {"id": "fri", "label": "Friday 29 May", "start": "2026-05-29 17:00:00", "end": "2026-05-29 21:00:00",
     "weight": 1.4, "show_other": true}             // weight = relative width; show_other = draw untagged chat
  ],
  "gap_labels": {"fri|mon": "Sat–Sun · closed"},    // optional text for the gap between two panels
  "memory_lookback": "2026-05-28 12:00:00",         // earliest memory snapshot to read (for carried-in state)
  "rooms": "auto",                                  // or an ordered list of room names to show
  "order_by": "<regex>",                            // optional: order rows in a group by first match (chat or claim memory); default: first belief/claim mark
  "pin_first": {"best": ["Claude Opus 4.7"]},       // optional: rows placed first in their group (next to the wall above)
  "room_notes": {"rest": "where the belief spread", "best": "the room next door"},
  "aliases": {"[Temporary] Fine-tuned Leader": "Fine-Tuned Leader"},
  "human_rows": [{"name": "Nudger (automated)", "pattern": "<regex on content>"}],  // optional: human messages matching go to this one row (not per room)
  "extra_agents": [{"name": "GPT-5", "room": "rest", "note": "silent: memory only"}],
  "agent_overrides": {"Claude Opus 4.7": {"never_belief_before": "2026-06-01 17:27:00", "note": "moves to #rest Mon 10:23"}},
  "moves": [{"agent": "Claude Opus 4.7", "t": "2026-06-01 17:23:33", "to": "rest", "label": "moves"}],
  "annotations": [{"t": "2026-05-29 19:57:15", "label": "12:57 \"temporal bleed\"", "anchor": "end"}],
  "links": [                                        // hand-verified hand-offs; the engine adds auto links too
    {"from": ["files", "50c2ffe3"], "to": ["files", "7659a206"], "label": "..."}   // [type, id prefix]
  ],
  "auto_links": true,                               // detect cross-room file hand-offs (see below)
  "figures": [{"value": "{claim_mem_agents}", "label": "agents' memories recorded it within {claim_mem_minutes} minutes"}],
  "steps": [ /* see Steps */ ],
  "notes": {"how": ["paragraph", "..."], "method": ["bullet", "..."], "limits": ["bullet", "..."]},
  "labels": true                                    // merge tracer/labels/<slug>.json if present
}
```

## Episode data (engine output, viewer input)

```jsonc
{
  "slug", "title", "headline", "lede", "tzOffsetHours",
  "claimLabel", "correctionLabel",                  // strings or null
  "panels": [{"id", "label", "startMs", "endMs", "weight", "showOther", "day"}],
  "gaps": [{"after": "fri", "label": "Sat–Sun · closed"}],
  "correctionMs": 1780335097000,                    // or null
  "groups": [{"key": "rest", "label": "#rest", "note": "where the belief spread"}],
  "rows": [{"name", "group", "human": false, "silent": false, "note": ""}],
  "chat":  [{"t", "a", "room", "id", "kind", "stance", "check", "text"}],
  "mem":   [{"t", "a", "id", "state", "stance", "check", "text", "chars"}],
  "files": [{"t", "a", "id", "kind", "op", "artifact", "text"}],
  "links": [{"from": ["files", "<full id>"], "to": ["mem", "<full id>"], "label", "auto": false}],
  "annotations": [{"t", "label", "anchor"}],
  "moves": [{"agent", "t", "toGroup", "label"}],
  "stats": { /* see Stats */ },
  "figures": [{"value", "label"}],                  // placeholders already filled
  "steps": [ /* copied from spec, key ids resolved to full ids */ ],
  "notes": {"how": [], "method": [], "limits": []},
  "labelStats": {"items": 0, "labelled": 0, "model": "haiku", "agreement": 0.0, "checkModel": "sonnet"}  // or null
}
```

`id` is the full source id: chat message id, memory id, or turn id. `text` is the redacted excerpt
(chat up to 900 chars when tagged, 360 when `other`; memory and files an excerpt around the match).

Kinds and states:

| field | values | meaning |
|---|---|---|
| chat `kind` | `belief` | asserts or builds on the claim |
| | `attributed` | mentions the claim as someone else's view (needs a stance label) |
| | `hint` | points toward the truth without stating the correction: questions the claim, or mentions the correction's facts in passing |
| | `fix` | states the correction |
| | `other` | not about the episode |
| memory `state` | `claim` | the snapshot holds the claim as true |
| | `attributed` | records it as someone else's belief or a symptom |
| | `fix` | holds the correction (or rejects the claim) |
| | `none` | mentions neither |
| file `kind` | `belief`, `fix` | the command touches the claim or the correction |
| file `op` | `write`, `read` | |

`stance` is `adopts`, `attributes`, `refutes`, `unclear`, or null (unlabelled). `check` is the second
labeller's stance (same values, or null); the viewer flags items where `stance` and `check` differ. Without labels the
engine uses regexes alone: matches become `belief` / `claim`. With labels, a claim match maps by stance:
adopts → belief / claim, attributes → attributed, refutes → hint (chat) or fix (memory), unclear →
keep the regex result.

## Steps

```jsonc
{
  "time": "Fri 12:57 PM PT",
  "title": "\"Temporal bleed\"",
  "body": "<p>HTML paragraphs. Plain language. Every fact checked against the data.</p>",
  "key": ["chat", "a9df78e6"],                      // [type, id prefix]: the evidence shown in the inspector
  "range": ["2026-05-29 19:56:00", "2026-05-29 20:01:00"],   // optional shaded window
  "focus": {"any": [                                // marks to highlight; others dim. Omit for "show all".
    {"type": ["chat"], "kind": ["belief"], "from": "2026-05-29 19:56:00", "to": "2026-05-29 20:01:00"},
    {"type": ["band"], "kind": ["claim"], "panel": ["gap"]},
    {"type": ["chat"], "text": "temporal.bleed", "groups": ["rest"]},
    {"linked": true}
  ]},
  "links": true,                                    // also light up link arrows
  "moves": true                                     // also light up room-move arrows
}
```

A focus clause matches a mark when every field it names matches. Fields: `type` (chat, mem, file,
band), `kind` (kind for chat and files, state for mem and bands), `stance`, `from` / `to` (UTC; a band
matches when it overlaps the window), `agents`, `groups`, `panel` (panel ids or `gap`), `text` (regex
on the text, case-insensitive), `linked` (the mark is an end of a link), `op` (write, read).

## Stats (computed by the engine)

```
claim_chat_agents      distinct agents with chat kind=belief before correctionMs (or ever, if no correction)
claim_mem_agents       distinct agents with memory state=claim before correctionMs
claim_mem_minutes      minutes from the first to the last agent's first claim snapshot (those agents)
memory_only            sorted names: claim in memory, no chat message matching claim.chat (any kind) before correctionMs
attributed_only        sorted names: memory state=attributed at some point, never state=claim
group_reach            {group: {"reached": n, "total": n}}  (reached = chat belief or memory claim)
fix_mem_agents         distinct agents with memory state=fix
fix_first_minute       distinct agents with chat kind=fix within 60 s after correctionMs
linger_agents          sorted names with chat belief or memory claim after correctionMs
crossroom_links        number of links whose two ends are in different groups
first_claim            {"t", "a", "type", "id"} earliest belief/claim mark
first_fix              {"t", "a", "type", "id"} earliest fix mark (or null)
```

Figures may use `{stat_name}` and `{stat_name.length}` placeholders.

## Auto links (cross-room hand-offs through files)

Room of an agent at time t = the room of its most recent chat message in the previous 48 hours.
For every tagged file write by agent A to artifact X at time t, link it to each read of X (any read,
tagged or not) by an agent B whose room differs from A's, within 90 minutes after t. If B's next
memory snapshot or chat message within 45 minutes after the read has the same state family
(claim/belief or fix), add a second link from the read to that mark. Untagged reads that become link
ends are included in `files` with the write's kind. Mark auto links `"auto": true`. Artifact identity
comes from `artifact_events.parquet` when present; otherwise from repo-like names in the command
(`ai-village-agents/<repo>`, `cd ~/<repo>`, `/tmp/<repo>`).

## Labels (`tracer/labels/<slug>.json`)

```jsonc
{
  "slug": "temporal-bleed",
  "claim": "the claim label used in the prompt",
  "model": "haiku", "checkModel": "sonnet",
  "items": {"<full id>": {"type": "chat|mem", "stance": "adopts|attributes|refutes|unclear",
                           "check": "adopts|...|null", "reason": "short paraphrase, no quotes over 12 words"}},
  "agreement": 0.93, "n": 120
}
```

`label.py` collects every chat message and memory snapshot that matches the claim regexes, sends
batches of about 25 to `claude -p --model <model> --output-format json` (the CLI reads the prompt on
stdin; the JSON response's `result` field holds the model's text), asks for a JSON object of labels,
and caches results by id so reruns only label new items. `--check` runs a second model over all items
and records agreement. The viewer shows disagreements.

## Local app (`serve.py`)

`uv run python -m tracer.serve [--port 8765]` serves the viewer in live mode.

```
GET  /                         template.html with window.TRACER_CONFIG = {"mode": "live"}
GET  /api/episodes             [{"slug", "title", "headline"}]
GET  /api/episode/<slug>       episode data (builds from the spec when out/ is missing; ?rebuild=1 forces)
GET  /api/scan?q=<text>&regex=0|1
       -> {"q", "days": [{"date", "chat", "chatAgents", "mem", "memAgents", "files"}],
           "first": {"chat": {...}|null, "mem": {...}|null, "file": {...}|null},
           "topAgents": [{"name", "chat", "mem"}], "seconds": 8.2}
POST /api/trace                body {"claim": {"label", "pattern"}, "correction": {"label", "pattern", "at"}|null,
                                     "days": ["2026-08-10", ...], "label": false}
                               -> episode data (panels from the chosen days, bounded by that day's chat
                                  activity rounded out to the hour; no steps; generic figures)
```

## Viewer (`template.html`)

One self-contained page (inline CSS and JS, Google Fonts only), written body-level (no doctype, html,
head or body tags: the artifact host wraps it; `serve.py` and `site/preview.html` add a skeleton for
local use). It contains `<script>window.TRACER_CONFIG = /*__TRACER_CONFIG__*/null;</script>`; builders
replace the marker with `{"mode": "static" | "live", "episodes": [{"slug", "title", "url"}]}`. With
null, the page uses `window.TRACER_INLINE` ({slug: episode data}) if present. It reads that config then fetches episode data by relative URL (static) or from the API (live).
It renders: masthead (headline, lede, figures), the swimlane chart (lanes per agent grouped by room,
room walls, N panels with gaps, chat dots, memory bands, file diamonds, links, moves, annotations),
the walkthrough with declarative focus, an inspector showing the source of any mark with a deep link,
channel toggles, an evidence log (the table view), and notes. Live mode adds a "Trace a claim" panel:
type a phrase, see its timeline from `/api/scan`, pick days, optionally add a correction phrase, build.
Episode tabs switch between curated episodes; `#<slug>` selects one.
