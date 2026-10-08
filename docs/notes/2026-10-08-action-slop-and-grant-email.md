# 2026-10-08: action-only "slop" angle, and a question to the grant team

These notes come from a Claude Desktop session that Ian pasted in. The papers and their numbers come from that
session and were not re-checked here. The data figures under "Data check" were checked against the local export.
For the earlier ideas, see `2026-10-07-grant-and-drift-watch.md`.

## The idea

Study agent behaviour from **actions alone**: the computer-use turns (`agent_action`, tool output, screenshot
metadata) and the events timeline (`AGENT_TALK`, `START_USING_COMPUTER`, `WAIT`, `PAUSE`, `SEARCH_HISTORY`, …),
without reading any text the agents wrote.

"Action slop" means low-information action sequences, all countable from `agent_action`, screenshot hashes and
events:
- the same click repeated on an unchanged screen,
- oscillating between two states,
- screenshot-only turns that do nothing,
- long WAIT runs,
- sessions that balloon in length while the session goal stays the same.

## Related work (from the other session; not verified here)

- **Your Agent Has a Genome** (arXiv 2606.15579, Apr 2026). Encodes tool-call streams as Explore / Execute /
  Plan / Verify sequences and analyses them at the sequence level (self-loop rates), without reading content. It
  notes that patterns may differ across models.
- **TraceLab** (arXiv 2606.30560, Jun 2026). About 4,300 Claude Code and Codex sessions: about 350k LLM steps and
  430k tool calls, with their patterns characterised.
- **Step-level Optimization for Efficient Computer-use Agents** (arXiv 2604.27151). Names two failure modes:
  progress stalls (loops, repeated equivalent actions) and silent semantic drift. Failed episodes run about
  2.5–2.8× longer, with much higher action repetition.
- **Learning from Failure** (arXiv 2606.31270). Redundant action loops are about a quarter of computer-use agent
  failures, even after self-improvement rounds.
- **OS-Marathon** (arXiv 2601.20650, Jan 2026). On long repetitive tasks, agents execute each subtask but fail to
  sustain the loop.
- **Sequential Behavioral Watermarking** (arXiv 2605.11036). Its premise is that trajectories carry little
  evidence of which agent produced them. The Village can test that: can model family be identified from action
  n-grams alone?
- Background: a February 2026 survey of agent trajectory analysis (Wang et al., IEEE TSE).

## Data check (local export of 2026-09-20, checked 2026-10-08)

- `turns`: **2,510,487 turns from 46 agents**, 2025-04-02 to 2026-09-19. The other session's "1.14M turns" and
  "15+ agents" probably come from an older dataset card. Use the export's numbers.
- The event action types listed above match `analysis/BRIEF.md`.
- Confounds for any action-rate trend (from the CHANGELOG):
  - Always-on computer use from 2026-03-24 made START/STOP_USING_COMPUTER rare, with CONSOLIDATE about every 40
    actions.
  - Anthropic models moved to one tool call per turn on 2026-06-03.
  - Chat rooms arrived on 2026-02-25.
  - The idle-nudge bot ran from 2026-02-10 to 2026-08-20.
- Existing related evidence: Gemini 2.5 Pro made 6,302 one-character `echo -n 'a' >>` appends on 10–15 July 2026
  (`analysis/rhythms/FINDINGS.md`). That is a ready example of action slop.

## Draft pitch (written by Claude in the other session; reference only)

**The submitted pitch must be human-written.** Keep this draft as notes on structure and content only. Two of its
figures need fixing (see the bracketed notes).

> **Action slop: what the Village's 1.1M computer-use turns say without reading the text** *[2.51M turns in the
> 2026-09-20 export]*
>
> Recent work analyzes agents from their actions alone: "Your Agent Has a Genome" (Apr 2026) encodes tool-call
> streams as Explore/Execute/Plan/Verify sequences and studies self-loop rates; step-level CUA work (Apr 2026)
> shows failed GUI trajectories run ~2.5x longer with far higher action repetition. The Village holds 1.14M turns
> across 15+ frontier agents over 18 months *[2.51M turns, 46 agents]*, the largest real-world sample for this lens.
>
> Ignoring all generated text, I'll encode each computer_use_turn's agent_action into a small action alphabet and
> compute, per agent per month: repeat-action rate on unchanged screens, oscillation rate, action-transition
> entropy, and session length relative to session_goal. I'll test (1) whether these "action slop" rates differ by
> model family and fall across model upgrades, controlling for CHANGELOG.md; (2) whether a classifier can identify
> model family from action n-grams alone, a direct check on the claim that trajectories carry little provenance
> signal; (3) whether action slop co-occurs with chat slop, using the chat only as an outcome label, never as input.
>
> Deliverable: a one-page report with graphs and code. Nulls count.
>
> Alongside, short public videos on the papers, linked in the report.

The other session's advice was that the text-based and action-based versions are not rivals. For a single pitch,
lead with the action channel, because it's the less-trodden path, and keep the chat-slop link as test (3).

## Email to the grant team (tidied version)

The question is whether you can submit again if your first idea is declined. It also floats a more abstract pitch:
public videos on relevant papers first, then the most promising research run on the dataset.

> Good evening!
>
> I had a quick question regarding the grant. Is it possible to submit a second time if an initial idea is
> declined?
>
> The idea I'm considering is a little more abstract: a series of public videos on relevant papers related to
> "slopvestigations" (investigating low-quality or repetitive agent behaviour in the Village), and then
> implementing the most promising of that research against the Village dataset. I'm uncertain whether this is a
> bit too out there conceptually, and if there's only one chance to submit, I might go with a safer proposal
> instead.
>
> Here's a sample of the video format, summarizing three seminal papers on forecasting superintelligence:
> https://x.com/dumbfook/status/2105012753803174325
>
> I'd appreciate your thoughts.
>
> Very best regards,
> Ian

Proofreading notes from that session:
- Split the comma splice.
- Gloss "slopvestigations".
- Say "three seminal papers on forecasting superintelligence".
- If you settle on the action-only angle, describe it as "repetitive or low-information agent behaviour" rather
  than "text slop", so the reply addresses the version you'll actually pitch.

## Open items

- Wait for AI Digest's answer on resubmission. It decides whether to lead with a safe pitch or the video-series
  pitch.
- Compare the action-slop pitch with the 2026-10-07 options. Safety theater is still the strongest finding-led
  option, and Drift Watch was rated 5/11.
- Before pitching action slop, run a quick check that repeat rates and screenshot-only turns can be computed from
  `agent_action` across the regime changes listed above.
