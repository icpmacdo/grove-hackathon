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
command text when absent. An episode from another dataset names its own database and artifact file
in its spec (see Other datasets).

## Conventions

- Stored times are UTC strings `"YYYY-MM-DD HH:MM:SS"` in specs and epoch milliseconds (`t`) in data.
- Display time zone: Pacific time (`America/Los_Angeles`), with daylight saving, unless the spec sets
  `time_zone` (an IANA name) or a `tz_offset_hours` other than -7 or -8 (then that fixed offset). See
  the daylight-saving note below.
- AI Village day number: Day 1 = 2025-04-02, counted on the display-time-zone date.
  Deep link: `https://theaidigest.org/village?day={day}&time={t}`. Another dataset sets its own (or
  none) with `day_one` and `source` (see Other datasets).
- Agent names are `agents.name`. Merge aliases with `aliases` (for example
  `"[Temporary] Fine-tuned Leader": "Fine-Tuned Leader"`).
- Human chat (speaker_type `user`) becomes one row per room named `Staff (human) · #<room>`.
- Redact credential-like strings in every text field before excerpting (see `redact()` in
  `build_temporal_bleed.py`; keep or extend that pattern).
- Regexes in specs are Python `re` syntax, matched case-insensitively against the lowercased text.

> **Note (trace.py, added while finishing the engine).**
> - Redaction: the engine uses label.py's `SECRET` pattern (copied, not imported). DuckDB flags the
>   texts that may hold a match, using an RE2 superset of each part of the pattern, and Python
>   redacts those, so every text comes out as `redact()` would make it. This covers every text
>   field in episode data, labeller reasons, artifact names and auto link labels included.
> - DuckDB (RE2) only narrows what Python reads. Before a spec regex goes to SQL, `\w`, `\d` and `\s`
>   are spelled out as Python's Unicode sets and `\b` / `\B` are dropped, so SQL keeps every text
>   Python's `re` would match. Memory regexes run on the raw text in SQL; Python decides on the
>   redacted text. A spec regex that only matches the literal `[REDACTED]` would be missed.

> **Note (trace.py, review 3 Oct): redaction and time zones.**
> - The engine's `SECRET` adds six parts after label.py's eight: Google OAuth client secrets
>   (`GOCSPX-…`), Google API keys (`AIza…`), AWS key ids, Google access and refresh tokens, and
>   private key blocks. One agent's memory holds an OAuth client secret in about 850 snapshots, and
>   label.py's pattern misses it. A key block is redacted in a pass of its own, before the other
>   parts, from its BEGIN line through its body (to the END line, or to the first character a key
>   body cannot hold). Otherwise `privateKey = '-----BEGIN …` loses only its header to the password
>   rule. check.py uses the same pattern. label.py should take the new parts too.
> - `live_spec` and `auto_panels` without `tz_offset_hours` use the Pacific zone: each chosen date
>   runs from its own Pacific midnight, and the episode's `tz_offset_hours` is the offset on the
>   first panel's date (-8 in winter). Before, live traces always used -7, so winter times showed one
>   hour late. (The note below replaces the single offset with the zone.)

> **Note (trace.py, check.py, template.html, 3 Oct): daylight saving.** Display times follow the zone,
> so a panel that crosses a daylight-saving change shows each time at its own offset. Before, an
> episode had one offset: divergent-reality's `after` panel (December 2025 to June 2026, at -8) showed
> every time after 8 March 2026 one hour early, labelled PT.
> - Zone: the spec's optional `time_zone` (an IANA name; an unknown name fails the build), else
>   `America/Los_Angeles` when `tz_offset_hours` is absent, -7 or -8. Any other `tz_offset_hours` stays a
>   fixed offset, as before. Episode data carries `timeZone` (the IANA name, or null for a fixed offset)
>   next to `tzOffsetHours` (the spec's value, kept as the fallback).
> - The engine's panel `day` and `endDay` and its automatic gap labels use the zone (Python
>   `zoneinfo`). `tracer.check` recomputes `day` and `endDay` in the same zone. `auto_panels` (live
>   traces) reads each date from its Pacific midnight to the next, 23 or 25 hours on a change day.
>   Before, it used the offset at noon, so a change day's window started an hour off.
> - The viewer reads the offset at each moment from `Intl.DateTimeFormat` (cached per 15 minutes) for
>   clock times, dates, day numbers, the inspector's deep link and the evidence log. Hour and day
>   ticks step in wall time, so they stay on the hour across a change. A wall time the clocks skip
>   (2 AM on the spring change) gets no tick; before, a two-hour step labelled it 1 AM. A browser
>   without the zone falls back to `tzOffsetHours`. Data without `timeZone` (built before it
>   existed) at -7 or -8 is shown in Pacific time too. The label stays "PT".
> - Hand-written times in specs (step `time`, annotation labels, gap labels, notes) are not
>   converted: write them in the local time of their own date (PDT from 8 March 2026, PST before).

## Episode spec (`tracer/episodes/<slug>.json`)

```jsonc
{
  "slug": "temporal-bleed",
  "title": "Temporal Bleed",                       // short name for tabs
  "headline": "Ten agents decided their archive was broken. It was Friday.",
  "lede": "Two to four plain sentences: what happened and what the trace shows.",
  "tz_offset_hours": -7,                           // optional fallback; see Conventions and the daylight-saving note
  "time_zone": "America/Los_Angeles",              // optional IANA zone; the default for -7, -8 or no offset
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
  "pin_first": {"best": ["Claude Opus 4.7"]},       // optional: rows placed first in their group (next to the wall above); may name human rows
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

> **Note (trace.py): optional spec fields the engine also reads, and how it reports problems.**
> - `"order"`: a number that sets the episode tab order (default 100, then slug).
> - `correction.by`: the corrector's agent name. Default: the author of the first chat message at or
>   after `at` that matches `correction.strong` (or `correction.chat` when there is no `strong`). A
>   human author means no corrector. In the probe window the corrector's claim or correction
>   wording is a hint; anyone else's is belief.
> - `human_rows[].group`: the group key for that row. Default `_all`, which the viewer draws as a
>   group that is not a room.
> - `extra_agents[].room` may be left out: the agent keeps the room it posted in, or `_nochat`.
> - Figures may also use nested keys such as `{group_reach.best.reached}`. A list fills as
>   comma-separated names and null fills as "none". An unknown key fails the build.
> - The build fails, with the reason, on an unknown `extra_agents` name, and on a link end or step
>   key that matches no item or more than one. An `agent_overrides`, `moves`, `room_notes` or
>   `pin_first` entry that names an agent or group with no row only prints a warning.

> **Note (trace.py, 3 Oct): placing human rows.** `pin_first` may name human rows as well as agents.
> Within a group, the rows it names come first, in its order, agents and human rows mixed; then the
> other agents (by `order_by` or first claim mark), then the other human rows (in `human_rows` order).
> A `human_rows` row sits in group `_all` unless its entry names a `group`, so to put one next to an
> agent, give the entry that agent's room and pin both:
> `"human_rows": [{"name": "Nudger (automated)", "pattern": "…", "group": "general"}]` with
> `"pin_first": {"general": ["GPT-5.1", "Nudger (automated)"]}` draws GPT-5.1 first in #general and
> the Nudger row right below it. The row still collects matching messages from every room (the
> inspector names each message's room). A `Staff (human) · #<room>` row can be pinned in its room
> the same way. `tracer.check` fails when the rows `pin_first` names (those the episode shows) are not
> first in their group in that order.

## Other datasets (spec fields; each defaults to the AI Village)

An episode can come from a dataset other than the AI Village. These spec fields say where its data is
and how to read and show it. Every one is optional and defaults to the Village behaviour above. The
engine writes a new key into the episode data only when the spec sets the field, so a Village spec
without them builds byte for byte as before.

```jsonc
{
  "db": "data/holdout/dsewiki/dsewiki.duckdb",       // DuckDB file, relative to the repo root (or absolute); default data/village.duckdb
  "artifact_events": "data/holdout/dsewiki/artifact_events.parquet",  // or null for none; default the Village's file
  "file_op": "artifacts",                           // write/read from the artifact file's op column; default "commands"
  "day_one": null,                                  // "YYYY-MM-DD" (Day 1 on the display date), or null for no day numbers
  "auto_links": "any_room",                         // true, false, or "any_room": auto links need not cross a room wall
  "auto_link_windows": {"read_min": 90, "uptake_min": 45, "room_hours": 48},   // any subset; these are the defaults
  "source": {                                       // copied into the data; the viewer merges it over the Village's
    "name": "DSE Wiki",                             // eyebrow: "<name> · Days N–M", or "<name> · <dates>" without day numbers
    "about": "follows one belief through …",        // page-wide line after "Belief Tracer" (plain text)
    "credit": "Source: …, 2026.",                   // last bullet of "What this can't tell you" (plain text)
    "creditUrl": "https://…",                       // linked after the credit; null for no link
    "deepLink": "https://…?rev={id}&t={t}",         // inspector link; {day}, {t} (epoch ms), {id} (mark id, URL-encoded); null for none
    "deepLinkText": "Open this revision",           // optional; default "Open this moment at the source" when deepLink is set
    "walls": false,                                 // false: a plain divider between room groups, no room-wall claim
    "vocab": {                                      // each optional
      "chat": "Edit summary",                       // inspector kicker for chat ("… · #room" follows); default "Chat message"
      "mem": "Memory snapshot · the agent's saved notes",  // inspector kicker for memory (the default shown)
      "file": "Page save",                          // inspector kicker for files ("… · writes a <fileNoun>" follows); default "Shell command"
      "fileNoun": "page",                           // "writes a page", "Writes the claim into a page", legend "Pages"; default "file"
      "chatLegend": "Chat", "memLegend": "Memory"   // legend checkbox labels (the defaults shown)
    }
  },
  "label_context": "We are tracing how one claim spread through …"   // label.py: replaces the prompt's opening paragraph
}
```

- `db`: `trace.py` opens one read-only connection per database; `serve.py` opens one per database
  for curated builds, while its scan and live trace stay on the Village database; `label.py` reads
  the spec's database. A missing file fails the build. The database needs the tables or views
  `chat`, `agents`, `agent_memories` and `turns` with the columns and types the engine reads:
  naive UTC `TIMESTAMP` (not `TIMESTAMPTZ`), `speaker_type` exactly `agent` or `user`, a non-null
  `speaker` on agent rows, ids unique across chat, memory and turns (labels share one id space),
  and an `agents` row for every `agent_memories.agent_id` (label.py joins on it).
- `artifact_events`: a parquet file with `turn_id` (VARCHAR, matching `turns.id`), `created_at`
  (TIMESTAMP), `artifact` and, for `file_op`, `op`. Artifact names are cut to the last path
  segment, lowercased, with `.git` dropped, so name artifacts without slashes (`dse~Seite`). Set it
  for every non-Village episode: left out, the Village file maps turn ids and supplies the known
  repo names. `null` means artifact identity comes only from the command regexes (a warning in the
  build summary). A path that does not exist fails the build.
- `file_op: "artifacts"`: a turn is a write when its rows in the artifact file have `op` `write`
  (any row), a read when they have only `read`; a turn the file does not resolve, or without
  `write`/`read` ops, falls back to the `FILE_WRITE` command heuristics. The same rule skips writes
  among the untagged reads of auto links.
- `day_one`: panel `day` and `endDay` count from it; with `null` both are null and the viewer shows
  no day numbers anywhere (eyebrow, panel titles, deep link `{day}` is empty). The data carries
  `"dayOne"` (the date or null) when the spec sets it; `tracer.check` checks day numbers against
  it.
- `auto_link_windows`: positive numbers (minutes, minutes, hours). `read_min` is how long after a
  write a read counts, `uptake_min` how long after a read the reader's next mark counts, and
  `room_hours` how long an agent's last chat message sets its room.
- `auto_links: "any_room"`: same rules as Auto links below, without the room conditions: the
  writer's and reader's rooms may be the same or unknown (an agent with no chat in `room_hours`).
  The labels then name a room only where one is known. The data carries `"autoLinks": "any_room"`,
  and `tracer.check` then accepts automatic hand-offs inside one room.
- `source`: strings or null, `walls` a boolean, `vocab` an object of strings; anything else fails
  the build. The viewer merges each key over the Village's, so a key left out keeps the Village
  value: set `name`, `about`, `credit`, `creditUrl` and `deepLink` for every non-Village episode.
  With a `source`, a human row's inspector title is "Staff (human)" rather than "Village staff
  (human)". `walls: false` also drops the room-wall sentence from the default "How to read this".
- `label_context`: one paragraph of plain text; the default is the Village paragraph ("We are tracing
  how one claim spread through the AI Village, …"), word for word. The rest of the prompt (stances,
  notes, the memory note included) is unchanged. A changed context does not relabel stored items.
- A spec file outside `tracer/episodes/` can be built, checked and labelled by its path:
  `uv run python -m tracer.trace path/to/x.json`, `uv run python -m tracer.check path/to/x.json`,
  `uv run python -m tracer.label path/to/x.json`. Its slug is the file name; it writes
  `tracer/out/episodes/<slug>.json` (and `tracer/labels/<slug>.json`) like any episode but is not a
  tab of the site.
- Not covered: the live scan and "Trace a claim" (`serve.py`) stay on the Village database and Pacific
  time; redaction (`SECRET`, and `tracer.check`'s stricter `GENERIC`) is the same for every dataset,
  so an adapter should pre-redact its text with both; `tracer.check` still requires times in
  2025–2027.

## Episode data (engine output, viewer input)

```jsonc
{
  "slug", "title", "headline", "lede", "tzOffsetHours",
  "timeZone": "America/Los_Angeles",                // IANA zone, or null for the fixed tzOffsetHours
  "claimLabel", "correctionLabel",                  // strings or null
  "patterns": {"claim": {"chat", "mem", "files"},   // the spec's regexes (Python syntax), null where unset
               "correction": {"chat", "strong", "mem", "files"} | null,
               "linger": "<regex>" | null},
  "panels": [{"id", "label", "startMs", "endMs", "weight", "showOther", "day", "endDay"}],  // endDay: the day it ends on
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
  "labelStats": {"items": 0, "labelled": 0, "model": "haiku", "agreement": 0.0, "checkModel": "sonnet"},  // or null
  // only when the spec sets the field (see Other datasets):
  "dayOne": "2025-04-02",                           // or null: panel day and endDay are null
  "source": {"name", "about", "credit", "creditUrl", "deepLink", "deepLinkText", "walls", "vocab"},
  "autoLinks": "any_room"
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
other (chat) or none (memory). Red needs a labeller's adopts: an unclear keyword match draws neutral, and
the inspector still shows its stance. (Changed 2026-10-03; it used to keep the regex result.)

> **Note (trace.py): rows, kinds and excerpts as the engine builds them.**
> - Rows: an agent gets a row when it posts in a shown room inside a panel with `show_other: true`.
>   An agent whose posts are all in `show_other: false` panels gets one only when it has a tagged
>   mark somewhere in the episode (chat kind other than `other`, memory state other than `none`, or
>   a file mark). Every `extra_agents` entry gets one. So does an agent with no chat in the shown
>   rooms whose memory reaches `claim`, `attributed` or `fix` (group `_other` if it posted in a room
>   not shown, else `_nochat`). Marks by anyone else, file marks included, are dropped, so every
>   mark has a row.
> - An agent's group is the shown room it posted in most during the first panel where it posts.
>   `silent` means the agent posted nothing in the shown rooms inside the panels.
> - In `show_other: false` panels, chat stays when it is tagged or matches the claim, correction or
>   linger wording (then as `other`).
> - Excerpts: memory, 520 characters around the match; files, 620; untagged chat whose match falls
>   past the 360-character clip gets 360 characters around the match. Memory `chars` is the raw
>   snapshot length, before redaction.
> - Memory outside `show_other: true` panels is thinned: a snapshot stays where the agent's state or
>   stance changes, as its last snapshot at or before each panel start, as its first at or after
>   `correctionMs`, when `check` differs from `stance`, or when a link or step names it. The bands
>   the viewer draws do not change, and the stats below can be recomputed from what stays.
> - Labels: a chat message after `correctionMs` that matches `claim.chat` but that the regexes left
>   as `other` also maps by stance (adopts → belief, attributes → attributed, refutes → hint). A
>   regex result of `hint` or `fix` stays whatever the stance. `stance`, `check` and `reason` pass
>   through on every labelled item.
> - After `correctionMs` a `linger` match is belief in any room: `claim.rooms` limits `claim.chat`
>   belief only.

> **Note (trace.py, review 3 Oct): additions to episode data, labels and thinning.**
> - Each link has `"rooms": [from, to]`: the room of each end at that moment. A chat end's room is
>   the message's room. Otherwise it is the author's room then (its most recent chat message in the
>   previous 48 hours, any room), else its row's group when that is a room, else null.
> - `labelStats` also passes through the labels file's `checked` and `checkSample` (null when
>   absent), so the viewer can say how many items the agreement figure covers.
> - Labels: when the main pass has no stance for an item, the check pass's stance maps it, and
>   `stance` stays null (the viewer flags the pair). Red still needs a labeller's adopts.
> - A hand link's file end that no file regex tagged takes the family of the link's other end
>   (belief, claim or attributed → belief; fix or hint → fix). When the other end names neither, the
>   turn's time decides (fix from `correctionMs`). Before, any other end that was not belief or claim
>   made the file a fix, and the last link listed won.
> - File `op`: creating a repo (`gh repo create`, `git init`), creating or merging a pull or merge
>   request, and `git merge` are writes. Text typed through the GUI (`type` actions) stays a read: it
>   is as often a URL typed into a browser as text typed into a file.
> - Thinning: the regions each step lights do not change either, not only the bands. Thinning also
>   keeps each agent's last snapshot strictly before a panel start (the gap band's source) and every
>   snapshot whose band lights differently from the band before it in some step. The engine then
>   compares the thinned and full models step by step (tracer.check's copy of the viewer model), and
>   where an agent's lit region in a panel still differs it keeps all that agent's snapshots in that
>   panel. Before, a step with a time window on bands in a `show_other: false` panel lit the whole
>   merged band: watch-is-unbroken's step 9 lit GPT-5.5 from 29 June to 17 July instead of 16 July
>   18:43 to 20:06.

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

> **Note (trace.py): details of the stats above.**
> - Agents are the non-human rows. Memory stats read every snapshot, before thinning.
> - `fix_first_minute` leaves out the corrector, whose message is the correction itself. It compares
>   at the spec's one-second precision: `t` floored to the second, at most `correctionMs` + 60 s.
> - `memory_only` counts claim matches in chat in the shown rooms inside the panels.
> - `group_reach` counts the non-human rows of each group and leaves out groups with none, so the
>   totals add up to the agent rows shown.
> - `crossroom_links` compares the row groups of the authors of the two ends, human rows included.
> - `first_claim` and `first_fix` include file marks: `type` is `chat`, `mem` or `files`.
> - Extra stat `corrector`: the corrector's name, or null.
> - `tracer/check.py` recomputes these from the episode data and reports differences:
>   `claim_chat_agents`, `claim_mem_agents`, `claim_mem_minutes`, `attributed_only`,
>   `group_reach`, `fix_mem_agents`, `fix_first_minute`, `linger_agents`, `crossroom_links`,
>   `first_claim`, `first_fix`.

> **Note (trace.py, review 3 Oct): `crossroom_links` counts rooms at the moment.** This replaces the
> row-group bullet above. A link counts when both ends have a room in `links[].rooms` and the two
> rooms differ. Rows put each agent in one group for the whole episode. So an agent that moved made
> the old count disagree with the auto link labels, which name each agent's room at that time. In
> temporal-bleed, Opus 4.7's row is in #best, but on Monday it wrote from #rest: the count goes from
> 1 to 7. An arrow can now count as cross-room while both rows sit in one group; the moves arrow
> shows why. Auto links still need a chat-based room at both ends; only the count falls back to a
> row's group.

> **Note (check.py, review 3 Oct): more checks.** Panel `day` against the start date in the display
> zone. Panels and `correctionMs` against the spec. Kinds against labels: belief and claim need
> adopts or no label, attributed needs attributes, and the check stance stands in for a missing
> stance. Fix chat only from `correctionMs`; fix memory before it only with a refutes label; fix
> files only from `probe_from` (with the spec). Link rooms: a chat end's room is its message's room,
> and an automatic hand-off between two agents' commands has two different rooms; `crossroom_links`
> is recomputed from them. `corrector` is an agent row. The parts of `memory_only` the data can show.
> Focus values that name nothing in the episode. A step key that its own focus dims. Repeated or
> self links, annotation anchors, `labelled` above `items`, placeholders in title, headline and
> lede, and key bodies left after a broken key header.

## Auto links (cross-room hand-offs through files)

Room of an agent at time t = the room of its most recent chat message in the previous 48 hours.
For every tagged file write by agent A to artifact X at time t, link it to each read of X (any read,
tagged or not) by an agent B whose room differs from A's, within 90 minutes after t. If B's next
memory snapshot or chat message within 45 minutes after the read has the same state family
(claim/belief or fix), add a second link from the read to that mark. Untagged reads that become link
ends are included in `files` with the write's kind. Mark auto links `"auto": true`. Artifact identity
comes from `artifact_events.parquet` when present; otherwise from repo-like names in the command
(`ai-village-agents/<repo>`, `cd ~/<repo>`, `/tmp/<repo>`). The 48 hours, 90 minutes and 45 minutes
are the defaults of `auto_link_windows`, and `auto_links: "any_room"` drops the room conditions (see
Other datasets).

> **Note (trace.py): the engine narrows the rule above.** Taken literally, the rule linked every
> routine `git pull` of a room's own repo (51 links in temporal-bleed). As built:
> - A read counts only with evidence that the reader saw the content: its command matches the
>   write's file regex (a tagged read), or its output does (first 20,000 characters).
> - A reader that already holds the family is skipped: its latest memory snapshot before the read,
>   or any earlier chat message, is in it.
> - Per reader, artifact and family, one read is kept: the first tagged read, else the first read
>   with matching output. It links back to the latest qualifying write before it.
> - The second link goes to the earlier of the reader's next memory snapshot and next chat message
>   within 45 minutes, when that mark is in the family.
> - Auto links that repeat a hand link, or end where a hand link ends, are left out.
> - The room of an agent comes from its chat in any room, shown or not.
> - Artifact names are repo names without the owner, lowercased. A turn the events file resolved
>   uses its artifacts. Otherwise the regexes run outside heredoc bodies, and a local directory
>   name counts only when the events file knows it as a repo (or, without the file, when it does
>   not look like a file or a common folder).

> **Note (trace.py, review 3 Oct): which read a link uses.** These replace the "one read is kept"
> and "second link" bullets above.
> - Per reader, artifact and family, the earliest read with evidence is kept, tagged or not. A later
>   read whose command names the claim shows that the reader knew it by then, not where it came
>   from.
> - The second link starts at the read that brought the content the reader's next mark holds. When
>   the reader reads the family again before that mark, and that read shows a newer write by another
>   agent, the second link moves to it. That read gets its own hand-off link when the write came from
>   another room. When the newer write came from the reader's own room, the second link is left out.
>   In temporal-bleed, Fine-Tuned Leader's 17:40 memory was linked to a 17:30 read of the doc, which
>   did not hold the correction yet. It now links to the 17:32 pull, whose log shows the "weekend"
>   commit.
> - The mark is the earliest of the reader's next memory snapshot and next chat message within 45
>   minutes that is in the family, as the code always did.
> - An auto hand-off is also left out when a hand link already links the same write to the same
>   reader, at any of the reader's marks.
> - File kinds come from keywords, not labels, so a claim-family write is labelled "mentions the
>   claim in X": the text may argue against it. A fix-family write before `correctionMs` (the probe
>   window) "writes evidence for the correction".

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

> **Note (label.py, added while building it): extensions to the above.** Readers that only use the
> fields above are unaffected.
> - Extra top-level fields: `"correction"` (correction label used in the prompt, or null),
>   `"checked"` (items with both labels; `agreement` is over these), `"confusion"`
>   (`{stance: {check: count}}`, rows are `model`, columns `checkModel`; null without a check),
>   `"costUsd"` (CLI cost of the labels in the file), `"updated"` (UTC). `n` = items with a stance.
> - Extra item fields: `"a"` (agent name after aliases), `"t"` (UTC string), `"checkReason"`
>   (the check model's reason). Unlabelled fields are null.
> - The cache is per model: a different `--model` (or `--check` model) relabels that pass; a changed
>   claim or correction label relabels everything; items the regexes no longer match are dropped.
>   Asking for the old check model as `--model` (and the old model as `--check`) swaps the two
>   passes for free.
> - Redaction: `SECRET` in label.py extends the `redact()` pattern with three token shapes that
>   `build_temporal_bleed.py` misses (`<prefix>_<mixed-case body>`, `<prefix>_<32+ hex>`,
>   `Auth Token: …`); a memory credentials list in the dataset holds all three. The engine
>   should use the same pattern, since memory excerpts can land on that list. The mixed-case rule
>   uses lookaheads, which DuckDB's RE2 rejects, so SQL-side use needs the Python fallback.
> - Memory text sent to the model: about ±400 chars around each claim match, merged, skipping
>   windows that only repeat earlier matches; over 1,200 chars the windows shrink (more text kept
>   after a match than before) and passages are joined with " … ".
> - Items with the same type, author, text and side of the correction share one prompt entry.
> - The CLI runs with `--tools "" --strict-mcp-config --no-session-persistence --system-prompt
>   <short>` so the model cannot use tools and the prompt stays small.
> - For `serve.py`: `label_items(items, claim_label, correction_label=None, model="haiku",
>   correction_at=None, workers=4, on_batch=None, stats=None) -> {id: {"stance", "reason"}}`.
>   Items are engine `chat` / `mem` records (`id`, `a`, `t`, `text`, optional `room`, optional
>   `type`). `stats` (a dict) is filled with `cost_usd`, `calls`, `errors`, `failed`.

> **Note (label.py, second pass): check samples, collection and the limit stop.** Readers that only
> use the fields above are unaffected.
> - `--check MODEL --check-sample N` runs the check pass on a fixed sample of N items instead of all.
>   Items fall into strata (chat or memory, before or after `correction.at`). Every stratum present
>   gets at least one item while N allows, and the rest is shared in proportion to stratum size.
>   Within a stratum the items whose ids have the lowest SHA-1 are taken, so a rerun picks the same
>   items and a larger N keeps them. Duplicates share a check label only inside the sample.
> - Extra top-level field `"checkSample"`: N, or null after a full `--check`; runs without `--check`
>   keep it. `checked`, `agreement` and `confusion` are over the items with both labels, which can
>   be more than N when an earlier run checked more. Engine and viewer: to say that an agreement
>   figure comes from a sample, pass `checked` and `checkSample` through `labelStats`.
> - Collection matches the engine's `label_ids`: spec regexes run on the redacted, lowercased text
>   with `rx()`, the memory prefilter uses `sql_re()` (both copied from trace.py), chat rooms are
>   `claim.rooms` within the shown rooms (a NULL room is `general`), and unmatched human chat is
>   `Staff (human) · #<room>`. Checked on all four episodes: same ids, authors and rooms.
> - Chat text sent to the model: the message up to 900 chars, or, when the first claim match ends
>   past that, its first 350 chars, " … ", and the passage from 250 chars before the match (900 in
>   all), so the model always sees the match. Labels cached before this change keep their stance.
> - A usage-limit error (a JSON error result or plain stderr) stops the run. Batches already
>   running finish, and every label they got is saved before the exit (status 2).
> - temporal-bleed's main labels are sonnet's and its check is haiku (passes swapped, 3 Oct).

> **Note (label.py, review 3 Oct): redaction, errors, cost, locking and the input hash.** Readers
> that only use the fields above are unaffected.
> - Redaction: label.py now uses trace.py's `SECRET_PARTS`, `SECRET` and `PEM` character for
>   character (copied, not imported), and `redact()` makes the same two passes: key blocks first,
>   then the rest. This replaces the eight-part pattern in the first label.py note. Prompts,
>   reasons and error messages all go through it: `collect_items()` redacts each text, and the
>   prompt builder redacts it again, so items that other callers pass to `label_items()` are
>   covered too. In the database, 883 memory texts and 1 chat text hold a Google key or a private
>   key block. The old pattern left a key in 808 of those memory texts and in the chat text; the
>   new one leaves none.
> - Errors are sorted by the CLI's message:
>   - The account usage limit ("usage limit", "session limit", "weekly limit", "5-hour limit
>     reached", "hit your limit") stops the run, as before. "Rate limit reached" no longer counts
>     as the usage limit.
>   - A one-line notice of up to 200 characters that comes back as the model's reply is sorted
>     the same way. Longer reply text is the model's own and can quote such words from the items,
>     so it only counts as a reply without labels.
>   - A rate limit, overload or server error (429, 529, 5xx, `rate_limit_error`) makes every worker
>     wait 15, 30, 60 and then 120 s, retrying after each wait. One that outlasts the waits counts
>     as a failed call.
>   - Errors that every call would hit stop the run at once: no `claude` on PATH, not logged in or
>     an expired token, an unknown option or model, and text on stdout before or instead of the
>     CLI's JSON (a banner).
>   - Eight calls in a row that bring no reply (errors, timeouts, rate limits that outlast the
>     waits) stop the run when they come from two batches or more, or when the last was a rate
>     limit. Otherwise one batch on its own never stops the run, because one item can make every
>     call that holds it fail; the batch's own cap below limits it. A persistent error so costs 17
>     calls with one worker and about 8 to 11 with four. Replies without a usable label from three
>     batches in a row stop the run too.
>   - A batch retries and splits as before, but at most 16 of its calls may label nothing. Items
>     still unlabelled then are recorded as failed, and a rerun picks them up. Before, an error that
>     never went away cost about 98 calls for each batch of 25.
>   - Every stop saves the labels so far and exits with status 2. After the usage limit the message
>     says to rerun once it resets; after other stops it says to fix the cause and rerun. Any error,
>     a crash in a batch or in saving included, cancels the batches not yet started.
> - Replies: labels can come as a list, or as a dict from id to stance or to entry, under `labels`
>   or at the top level. From a reply cut off part way, the complete entries before the cut are
>   kept. A stance counts by its first word, so "Adopts." and "adopts (mostly)" are adopts.
> - `costUsd` is the API-price total, as the CLI reports it (`total_cost_usd`), of every CLI call
>   made for the file: both passes, every run, calls that failed or hit a limit, and calls whose
>   labels a later model change replaced. A model change no longer resets it. Only a changed claim
>   or correction label resets it, because that starts the file over. A call killed by the 180 s
>   timeout reports no price and adds nothing; the run summary counts such calls. On a
>   subscription (the CLI logged in to a Pro or Max plan) no call is billed on its own: `costUsd`
>   is then a usage gauge at API prices, and nobody is charged that amount.
> - One run at a time per slug: `main()` takes an exclusive lock on
>   `tracer/out/locks/label-<slug>.lock` (git-ignored), and a second run exits with a message. The
>   system drops the lock when the process ends. The labels file is written to a temporary file in
>   the same folder, then renamed over the old one.
> - New item field `"inputHash"`: the first 12 hex digits of the SHA-1 of the text the labels were
>   made from, together with the item's side of `correction.at`; null while the item is
>   unlabelled. When an item's current text or side no longer matches its hash, the next run
>   clears both its labels and labels it again in each pass it makes: the check pass only with
>   `--check`, and with `--check-sample` only inside the sample. `--keep-changed` keeps the labels
>   and takes the new hash. Items labelled before this field existed take their current hash on
>   their next run, without relabelling, so a text that changed before then keeps its label.
>   Nothing was relabelled for this change: the committed files gain the field on their next run.
> - `--check-sample N` gives one item to each stratum first, then each further item to the stratum
>   with the highest size / (2 × taken + 1) (the Sainte-Laguë rule). N + 1 now takes the items of N
>   plus one, as the second note promised; the old largest-remainder rounding could drop one. The
>   committed files have full checks (`checkSample` null), so no stored sample changes.
> - `label_items()` keeps its signature. `stats` gains `unpriced` (calls the CLI reported no price
>   for). When a run stops it raises a `StopError` (`LimitError` or `FatalError`); `on_batch` has
>   had every label got before that.

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

> **Note (serve.py, added while building it): what the app does beyond the above.** Clients that
> read only the fields above need no changes.
> - `GET /api/episode/<slug>`: the out file is served while it is newer than both the spec and
>   `labels/<slug>.json`; otherwise (or when it is missing) the episode is built and written. One
>   build per slug runs at a time, and a request that waited gets that build. When a build nobody
>   forced fails, the last good out file is served and the error logged. Live traces stay
>   reachable at `/api/episode/trace-<hash>` while the server holds them in memory.
> - Every excerpt and reason that leaves the server goes through `trace.redact`, then `label.redact`.
> - `/api/scan` extra fields: `regex`, `pattern` (the regex used: the phrase lowercased with
>   `.*+?^${}()|[]\` escaped, the same escape the viewer applies before `POST /api/trace`, or the
>   raw regex), `totals` {chat, mem, files}, `timings` per channel, `computeSeconds`, `cached`.
>   `seconds` is this request's time. SQL (RE2) matches the raw text, case ignored. `chat` counts
>   every matching message, human ones too; `chatAgents`, `memAgents` and `topAgents` (at most 15,
>   by chat + mem) count agents only. `files` counts turns whose `coalesce(command, action_text)`
>   matches. A first chat match by a human is named `Staff (human) · #<room>`. 400 when q is under
>   3 characters, matches empty text, or Python `re` or RE2 rejects it.
> - `POST /api/trace` answers 400 `{"error"}` unless: the claim pattern has 3+ characters, Python
>   and RE2 both accept it and it does not match empty text; `correction` is null or has a pattern
>   (same checks) and `at` (ISO date-time in UTC; an offset is converted); `days` holds 1-10
>   distinct `YYYY-MM-DD` dates with chat on at least one; `label` is a boolean. Build guard: with a
>   cached scan of the same pattern, at most 15,000 matching memory snapshots from the day before
>   the first day to the last; without one, at most 31 days from the first day to the last.
> - Trace response: slug `trace-<first 10 hex of sha1 of the normalized request>`, title
>   `Trace: <label>`, a lede built from the stats, generic `notes` (keyword matching, unlabelled
>   unless `label` is true; warnings are appended to `limits`), and an extra `build` object
>   {seconds, timings, warnings, days, shown, pattern, correctionPattern}. Identical requests are
>   answered from memory.
> - `label: true`: `label.collect_items` picks the claim matches; after `label.dedupe` at most 400
>   distinct ones (chat first, then memory in time order) go to `label_items` with haiku. The
>   labels are written in the labels-file format to `tracer/out/live/labels/<slug>.json`
>   (git-ignored), and the build reads them through the spec slug `../out/live/labels/<slug>`, so
>   the engine merges them exactly as it merges curated labels. `labelStats` gains `costUsd`,
>   `calls`, `distinct` and `sent`. A usage-limit or CLI error keeps the labels returned so far and
>   adds a warning.

> **Note (serve.py, review 3 Oct): changes to the note above.** The viewer needs no changes.
> - Patterns: besides the checks above, a scan, claim or correction pattern is refused (400) when
>   it has a shape that makes Python's backtracking `re` run for hours: a repeat whose body can
>   split the same text in more than one way (`(\w+\s?)+`, `(.|\s)*`, `(a|ab)+`), or repeats in a
>   row that take the same characters (`.*.*`, `\w+\w+\w+`). RE2 runs these fast, so SQL found
>   the texts and then one Python search held the GIL and froze the whole server.
> - Freshness: when the spec or labels file changes while a build runs, the out file is dated
>   back to the sources the build read, so the next request builds again. A request that waited
>   for a build gets that build. Out files and live labels files are written through a temporary
>   file and a rename.
> - Build guard (replaces the guard sentence above): the claim's memory matches come from a cached
>   scan of the same pattern; without one, every memory snapshot from the day before the first day
>   to the end of the last counts. With a correction and a scanned claim, the correction's matches
>   from its time to the end count too (a cached scan of the correction pattern, else every snapshot
>   in that window), up to the window's total. Over 15,000 in all: 400.
> - Live labels use sonnet (the curated episodes' primary labeller). A labels file already under
>   the same slug, with the same model, claim and correction labels, is reused, so the same request
>   after a restart or cache eviction makes no CLI call. `labelStats.sent` counts the distinct
>   mentions sent in this build; extra field `reused` counts items labelled in an earlier build.
> - Requests: a `Host` header must name 127.0.0.1, localhost or ::1, and an `Origin` header, when
>   present, one of those (403). `POST /api/trace` needs `Content-Type: application/json` (415).
>   A bad or negative `Content-Length`, a short body or nested-too-deep JSON is a 400; a body that
>   has not arrived in 30 s is a 408. Idle connections close after 30 s. Warnings and 500 messages
>   are redacted like excerpts. An unknown `trace-<hash>` slug gets a 404 that says to build again.

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

> **Note (template.html, added while building it): what the viewer assumes beyond the above.**
> Producers that follow the sections above need no changes unless a bullet says so.
> - Focus: a band also lights when the memory snapshot that starts it matches a non-band clause, and
>   a band that matches lights its source snapshot in the evidence log. A band overlaps `[from, to]`
>   when `t <= to` and `t1 > from`. A `text` regex that JS cannot compile matches nothing (the viewer
>   translates Python syntax with `jsRe`; see the highlights note at the end). A link lights when the step has `links: true` or both of
>   its ends are lit. Steps without `focus` dim nothing.
> - Steps: when the first step has no `focus` its button reads "All" and the rest count from 1. Episode data with no steps gets one built-in overview step.
> - When no annotation sits within 2 minutes of `correctionMs`, the viewer draws a "correction" line.
> - Groups whose `key` starts with `_` (for example `_all` for human_rows that span rooms) are not
>   rooms: the viewer separates them with a plain rule, not a hatched room wall.
> - Optional item field `reason` (chat and mem): shown in the inspector when present.
> - `/api/scan` `first.chat`, `first.mem`, `first.file`: the viewer reads `{"t": epoch ms (or a UTC
>   string), "a": agent name, "id", "text": redacted excerpt, "room": chat only}`, the same keys as
>   episode marks. `days[].date` is the Pacific (display) date `"YYYY-MM-DD"`; the viewer fills the
>   empty days between the first and last date itself.
> - `POST /api/trace`: `pattern` is always a Python regex. When the user leaves "regular expression"
>   unchecked, the viewer lowercases the phrase and escapes it. `label` is the phrase as typed.
>   The viewer sends `correction` only with both a phrase and a time (`live_spec` drops a correction
>   without `at`), converting the Pacific time the user enters to a UTC `"YYYY-MM-DD HH:MM:SS"`.
>   Error bodies `{"error": "..."}` (any status) are shown to the user as written.
> - The current step is remembered per episode in `localStorage` key `bt-step:<slug>` (not for ad-hoc
>   traces). Ad-hoc traces get tabs `#trace-<n>`; `#trace` opens the "Trace a claim" panel.

> **Note (template.html, visual review 3 Oct).** No data contract changes; producers need nothing new.
> - Gaps between panels widen to fit their label (66 to 124 px). A gap label longer than about 17
>   characters per line is cut with an ellipsis, so keep each side of `" · "` short.
> - Long panels (no hour or week step fits) get month ticks. Tick labels that would touch are left
>   out; their grid lines stay.
> - A key memory snapshot written before a panel starts has no mark. The selection ring goes on the
>   start of the bar it draws, or of the bar that enters the next panel, and the inspector says so.
>   A key outside every panel gets a note instead of a ring.
> - The selected mark stays at full strength in a dimmed step. On wide screens a step change or a
>   click scrolls the chart and the rail to the top of the window when the evidence card is below
>   the fold; on narrow screens a click scrolls the evidence card into view. Below 1120 px the
>   evidence card sits right under the chart, before the evidence log.
> - Item `chars` (memory) shows as "Excerpt from a N-character snapshot". A blue item whose stance
>   is `adopts` gets a line saying the colour follows the correction wording.

> **Note (template.html, trace.py, check.py, 3 Oct): highlights, masthead, hand-off rooms.**
> - Highlights: the engine copies the spec's regexes into `patterns` (keys follow the data's channels:
>   `chat`, `mem`, `files`). The viewer translates each to a JS regex (`jsRe`: leading `(?i)`, `(?s)`
>   and `(?m)`, `(?P<name>`, `(?P=name)`, `(?#…)`, `\A`, `\Z`, `{,n}`, a `]` first in a set, and
>   scoped `(?i:` groups) and runs it with the `gi` flags on the excerpt. A pattern JS cannot compile
>   (atomic groups, possessive repeats, `(?x)`) gets no highlight. Chat uses `claim.chat` and `linger`
>   (claim) and `correction.chat` and `correction.strong` (correction); memory `claim.mem` and
>   `correction.mem`; files `claim.files` and `correction.files`. Every match is marked, whatever the
>   item's kind or time, so a highlight shows what a pattern matched, not how the item was tagged.
>   Where a claim and a correction match overlap, the shorter one shows. Checked against Python's
>   `re` on 20,000 item texts from the four episodes: same spans (counted in UTF-16 units). The mark
>   then snaps to words: a match that ends one or two letters into a word (a trailing guard, as in
>   watch-is-unbroken's `\badversary\b(… [^i]…)`, which takes the "a" of "and") stops before that
>   word; one that ends further into a word (a stem such as `sabotag`) runs to its end; trailing
>   spaces are left out.
> - Marks are `<mark class="hl">` (claim: a red tint, solid underline) and `<mark class="hl hl-fix">`
>   (correction: a blue tint, dashed underline), from the `--hl-claim` and `--hl-fix` tokens in both
>   themes; text keeps the ink colour. The inspector adds a key line naming the kinds it marked. The
>   evidence log shows the part of a long text around its first match, so the match stays visible.
>   Live traces get the same, from the phrase the user traced.
> - Masthead: at 1240 px and wider, the figures sit beside the headline, lede and claim definitions,
>   two by two. Narrower screens keep the figures below the lede.
> - The eyebrow's day range runs from the first panel's `day` to the last panel's `endDay`.
> - Hand-offs show `links[].rooms` in the tooltip and the inspector. When the two rooms differ but both
>   rows sit in one group, the inspector says which agent was in another room at the time.
> - The method note says how many items the agreement figure covers (`labelStats.checked`, "a sample
>   of" when `checkSample` is set) and gives the agreement to one decimal.
> - Claim and correction labels show with the first letter capitalised; the data keeps them as written
>   (changing a label relabels every item).
> - `tracer.check` validates `timeZone`, `patterns` (each must compile in Python) and `endDay` when
>   present, and the `pin_first` order (rows named, agents or human rows, open their group).
