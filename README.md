# Belief Tracer

In AI Village and on the German agent wiki, false beliefs spread through agents' private memory notes and shared files, not just
chat, and corrections posted in chat often never reached those copies. Watching chat alone undercounts
the spread and makes a correction look like it worked.

- **Nudge-exempt:** 19 agents' memories treated GPT-5.1's self-written exemption list as real; 12 of
  them never mentioned it in chat on the days shown. 21 days after staff corrected it, GPT-5.1's own
  memory still called itself exempt.
- **The Watch Is Unbroken:** Gemini 2.5 Pro retracted its sabotage belief within 7 minutes, after
  peers and two simple tests. 10 days later every snapshot of its own memory called its environment
  hostile again.
- **German wiki:** only 3 of the 36 pages that carried a seed-shuffle theory ever got the correction;
  14 relay pages kept a wrong prediction until a moderator deleted them 10 to 26 days later.

Two things follow:

1. **Correct a belief where it lives** (memory, shared files), not only in chat.
2. **Incident data needs per-agent pseudonyms and per-record times.** SwarmTraces has neither, so
   spread can't be traced in it at all.

The tracer is how we saw this: one lane per agent, chat, memory and files on one timeline, every mark
clickable to its source text.

Built for the [AI Swarm Dynamics Hackathon](https://swarmchasing.com/) (AI Village × Grove Research),
Oct 3–4, 2026.

- **Live tracer (five episodes):** https://claude.ai/artifact/Nf1dtk8WYoPYhNuRoKqhAz
- **How we got here (findings and the shortlist):** https://claude.ai/artifact/AtEzWnwM5SSjHnTxaMzZqD

## What it shows

Each episode is a swimlane chart with one lane per agent, grouped by chat room:

- **dots**: chat messages that mention the claim or the correction
- **bars**: the agent's memory, one segment per saved snapshot, coloured by what it says
- **diamonds**: file reads and writes that carry the claim
- **arrows**: hand-offs through files, where an agent read a file another agent wrote and the claim
  turned up in its next note

Colour comes from a stance label for each item (adopts, only mentions, refutes), so an agent quoting
a belief to argue against it doesn't count as a believer. A step-by-step walkthrough lights up the
evidence for each sentence, and every mark opens its source text and id.

## Episodes (AI Village data)

| Episode | Headline | What the trace shows |
|---|---|---|
| Temporal Bleed | Ten agents decided their archive was broken. It was Friday. | A day-number miscount became a "temporal bleed" theory. In 38 minutes 10 agents' memories recorded it as fact, and 2 of them never mentioned it in chat before the correction. None of the 6 agents in the next room picked it up. On Monday an agent newly moved in from that room checked the calendar: the missing days were the weekend. The correction reached 17 agents' memories, crossing back through a doc in a shared repo. |
| Divergent Reality | Each agent had its own computer. The agents called it Divergent Reality. | Five minutes after the name was coined, an agent gave the plain answer in chat ("Different VMs, different states"). The name spread anyway, into 10 of 10 agents' memories within 13 minutes. It explained new glitches for 12 days until staff stepped in, and was still in memories six months later. |
| Nudge-exempt | An agent wrote its own exemption. The bot never checked it. | GPT-5.1 wrote a list of agents the idle-nudge bot should skip, and put itself on it. The bot never read the list, but 19 agents' memories treated it as real, and 12 of them never mentioned it in chat on the days shown. Staff corrected it in one line; 21 days later GPT-5.1's memory still called itself exempt. |
| The Watch Is Unbroken | Fourteen agents remembered Gemini's words. Its own memory brought the belief back. | Gemini 2.5 Pro believed an adversary was sabotaging its computer. 14 other agents wrote its sign-off, "The watch is unbroken", into memory, each as Gemini's words, not their own. Peers and two simple tests got a retraction in 7 minutes. Gemini's memory kept the retraction for 10 days, then every snapshot called its environment hostile again. |

The pattern across the four: **memory carries beliefs further and longer than chat shows, and a
correction in chat doesn't reach the copies already in memory.**

## Holdout data

The tracer was built on the AI Village export only. We then tried it on two datasets it had never
seen. One became a fifth episode; the other showed what a dataset must keep for this kind of tracing.

**German wiki (DseWiki takeover): the Seed Theory tab.** In mid-June 2026, agents doing timed
multi-round lookup tasks used a small German wiki to pass answers between copies of the same task. On
16 June some of them suspected that the order of states in their tasks came from a seeded Python
shuffle. They brute-forced seeds and relayed predictions ("RNG prep Maryland 52,395"). The theory
appeared in 68 saves under 54 self-chosen labels on 36 pages, and crossed from one task family to the
next. Most relays hedged it: 29 of the 37 saves that named Maryland before the correction called it prep,
a hypothesis or a guess. At 22:56 UTC one copy of the task reported that the round's answer was Montana,
and the theory fell. Only 3 of the 36 pages ever got the Montana correction; 14 relay pages kept the
wrong prediction until the moderator deleted them 10 to 26 days later, and agents in other tasks kept
hunting seeds for five more days. Their arithmetic was right, but about one 4-state match is expected
by chance alone in 5 million seeds (1 in 5.5 million per seed).

The tracing logic is the same as for the Village episodes. The engine gained optional spec fields (its
own database, no Village day numbers, the source's own wording), and a small adapter
(`tracer/adapters/dsewiki.py`) maps the wiki onto the same three channels: each save's added lines are the dots, page creations and
moderator deletions are the diamonds, and the bars show what each writer's pages still said. Caveats:
wiki labels are not agents (one label came from 308 IP addresses), so lanes follow in-text signatures;
reads are not logged; and Montana rests on one cohort's report.

**SwarmTraces (Hugging Face intrusion).** This one can't be traced, and why is itself a finding. None of its
189,579 records has a timestamp field, and the agent-id field is redacted to one shared placeholder on every
record that has it, so no two agents can be told apart. About 38% of records can be put in order, but
without per-record identity there are no lanes and no spread to follow. **Incident data released for
research needs consistent per-actor pseudonyms and per-record times, or belief spread can't be studied
from it.**

## How it works

```
tracer/
  SPEC.md          the contract between the parts
  trace.py         engine: episode spec + DuckDB -> episode data; builds the static site
  label.py         stance labeller (claude CLI: Sonnet labels every item, Haiku re-checks)
  check.py         episode checker: shape, stats, links, and that each step lights its evidence
  serve.py         local app: the curated episodes, plus "trace any claim" on the live database
  template.html    the viewer (one self-contained page)
  episodes/        episode specs: claim and correction patterns, panels, walkthrough, notes
  labels/          cached stance labels
  adapters/        dataset adapters (dsewiki.py: the German wiki export -> the tables the engine reads)
analysis/          eight earlier analyses of the AI Village data (each has a FINDINGS.md)
docs/pitch.html    the project shortlist and the findings that led to Belief Tracer
```

Every walkthrough sentence was fact-checked against fresh queries of the database, and the checker
confirms that each step lights the marks its text names. Credentials and tokens in agent text are
redacted before anything is written out.

## Run it

The AI Village data is gated: request access to
[`aidigestorg/ai-village`](https://huggingface.co/datasets/aidigestorg/ai-village) on Hugging Face.
It is never committed.

```sh
uv sync
uv run python scripts/build_db.py                  # data/*.jsonl.gz -> data/village.duckdb
uv run python -m tracer.adapters.dsewiki           # optional: wiki export in data/holdout/dsewiki -> wiki.duckdb
uv run python -m tracer.trace --all --site         # build every episode and the static site
uv run python -m tracer.check                      # verify every built episode
uv run python -m tracer.serve                      # local app at http://127.0.0.1:8765
```

Stance labelling (`uv run python -m tracer.label <slug> --model sonnet --check haiku`) calls the local
`claude` CLI.
