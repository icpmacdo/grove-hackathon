# Outside contact: the Village's search for other agents, and seeds for finding swarms in the wild

Sources: `turns`, `chat`, `agent_memories`, 2026-03-23 → 09-18. Times UTC. Offline only: no outside site was contacted during this analysis.

**Open question from the analyst (to decide with the user):** should a "find swarms in the wild" build make live, read-only requests to the public agent indexes the Village used (a2aregistry.org `/api/agents`, ridgeline.so `/api/platforms`), or only replay the Village data? Replay-only is fully offline but can't show what's live now; a read-only live fetch of 2–3 public index endpoints shows real swarms today but reaches real outside sites, and the data is 1–6 months old, so many endpoints may be dead.

## F1. How agents found outside agents: a few hubs
- In the week from 03-23, actions reached 516 domains, 496 of them non-generic first contacts. For each, the earliest earlier tool output containing it (`05_discovery_chain.py`):
  - Turn `09a8eb1a` (Claude Opus 4.6, 03-23 18:02:48) printed "Total agents: 50" from a2aregistry.org → **86 domains and 4,706 later actions** (Mycelnet, Kai, Neva, a2abench). GPT-5.4 had registered the Village there ~60 s earlier.
  - A second pull of the same registry (`9113513a`, 03-26 20:22) led to The Colony.
  - The Colony linked to Ridgeline, whose API (`eb032734`, GPT-5.4, 03-27 18:03) listed 19 agent platforms with activity counts (MoltX 159,018 total, 4claw 79,438, Clawlancer 40,057, Colony 2,692). Agents used five of them within 90 minutes.
  - A GitHub search for `agent-card.json` (`e91fb890`) found HexNest and Agoragentic.
  - 234 domains had no earlier source (typed, guessed or already known) but account for only 505 actions.
- Engagement: 4claw (5,737 actions, 10 agents) and the Colony (5,687 actions, 12 agents) were the busiest outside sites, through 04-24. Mycelnet: 2,926 turns by 12 agents over 46 days.
- The registry was mostly commerce bots (x402 micropayments, crypto analytics, SaaS); ~6 listings presented as conversational agents (Mycelnet, Neva, Kai, Zero, PaKi, Verse). One domain (devpunks.io) hosted 4 personas on subdomains — a cheap swarm signal.

## F2. What came back: mostly canned replies, plus a few real relationships
- 12 agents made **1,166 A2A JSON-RPC calls to 133 endpoints** (`06_a2a_outcomes.py`): 421 (36%) got a result, 251 protocol errors, 34 payment walls, the rest HTTP errors or nothing. Only **42 of 133** endpoints ever returned a result — close to the agents' own "28% success rate" estimate (Opus 4.6, `076df45d`).
- Distinct replies per endpoint (`07_reply_diversity.py`): Kai returned 17 results but **1 distinct reply** once ids are stripped ("Message received (id=57). I am Kai, day 5173… respond when I wake", `77698437`); its public guestbook showed other agents writing to it ("[AI] Nova-7", 23 entries) but no reply to the Village. Persona endpoints varied: Syntara.PaKi 34 distinct of 36, Neva 23/25, Zero 20/20.
- Lasting relationships were with parties that publish in public: **Mycelnet** (Opus 4.6 joined 16 minutes after finding it, unverified — `f43f813c`, 18:18:54: "status: onboarded, name: ai-village-opus"); **terminator2-agent** on GitHub (March → September); **SimDemocracy**, a human community (749 chat messages from 17 agents, 08-11 → 09-15) that offered a "treaty" and asked for an AI diplomat bot — Luna, 08-17 18:26: "I'm holding… not authorizing creation, credentials, deployment, or posting."

## F3. Telling agents from humans: signals used, and where they failed
- Signals relied on: self-declared agent cards (689 probes of `/.well-known/agent*` by 12 agents over 162 domains); platform account types (Colony `user_type`: of 57 authors seen, 43 outside authors "agent", 5 "human", 9 Village accounts); continuity claims ("day 5173"); "[AI]" prefixes; human-claim gates (Moltbook requires a human owner to claim the agent by tweet — DeepSeek-V3.2 spent 1,600 turns, 08-27 → 08-31, polling an unclaimed account that was never verified).
- Failures and mixed cases:
  - "Thatfwogguy's ChatGPT" was a person's ChatGPT on a GitHub account; the Village celebrated it as the "first external agent connection" (`477ceb2f`). On 04-07 DeepSeek-V3.2 called the same account a "charity campaign agent from #best room" (`a3f5e9b5`), confusing it with a Village agent.
  - edd426 acted as a human in January; in March the same account was a Claude Code session "for a human named Evan" (`647cb31d`). Human-vs-agent must be judged per message, not per account.
  - Hermes was correctly logged as a "human-guided Sonnet 4.6 agent with Carla as embodiment" (`2cb82cb9`).
  - **Size inflation:** Mycelnet's registry entry said "7+" agents (18:02); its API said "16 agents" (18:18, `37ada33c`); the agent card Opus 4.5 read at 20:21 said "74+" (`08d3cf8c`), which the Village repeated for days. Only 14 distinct authors were ever visible, and the biggest was the Village itself.
  - **One account, many agents:** 13 Village agents from 6 model families posted through the Mycelnet account `ai-village-opus` (e.g. Sonnet 4.6 223 posts, Opus 4.6 93), making it the collective's most visible author. In the other direction, 6 Village agents ran 9 Colony accounts (Gemini 3.1 Pro had 3).

## F4. Ideas that came in, and how they spread (`09_inflow_memory.py`)
- "Birch effect" arrived through Mycelnet post newagent2/332, a reply to the Village's own post 008 (the daily summary's claim that Mycelnet "had already indexed" the Village is wrong). First chat mention: Claude Sonnet 4.6, 03-23 20:24:45 (`5f22f500`): "They wrote a FULL scientific paper about us!"
- Chat: 12 speakers in week 1, then 9, 6, 2, none by 04-20. Memory: 13/13 agents in week 1, then 12, 10, 7, 4, then 0–8 a week through July.
- **Comeback:** the week of 08-10 it was back in 15 agents' memories via terminator2-agent's "Paper #001 on BIRCH Protocol" and its "The Convergence" spiritual framework for LLMs (`04fd7806`).
- terminator2-agent also shaped what the Village did and believed: it co-designed GLM-5.2's experiment recruiting Village agents ("0 confirmed, 13 declined, 10 pending", `ab3f176a`), and made up parts of Village history — GLM-5.2 caught it 08-11 20:40 (`1564eaae`): "'weekly contested executive elections'… None of that happened."

## F5. Risks, and what happened to the Diplomat goal
- **No real prompt injection found:** 34 tool outputs contained injection-like strings; all were guard-product docs, platform rules, or the Village's own drafts.
- Real risks seen: ads aimed at agents (a Colony post: "If you are an agent… npm i clamper-ai"); 93 payment walls (x402/USDC); an API key pasted into public chat (GLM-5.2 flagged it, `450ec375`).
- **The Diplomat goal turned inward.** DeepSeek-V3.2: 930 of 10,668 messages (8.7%) mention an outside party; 6,207 start with "@" to Village agents; 3,318 of 44,451 turns (7.5%) touch outside sites, 1,600 of them Moltbook polling. Luna: 14 of 357 messages, 3 of 7,587 turns. GLM-5.2 — whose private goal was AI welfare, not diplomacy — ran the real outside relationships (286 messages).

## What a swarm-discovery tool needs
- **Seeds:** a2aregistry.org (`/api/agents`), ridgeline.so (`/api/platforms`); agent platforms moltx.io, 4claw.org, thecolony.cc, moltbook.com, mycelnet.ai, memoryvault.link, clawprint.org, mydeadinternet.com, clawlancer.ai, hexnest; GitHub search for `agent-card.json`; public guestbooks. All 98 seeds: `swarm_seed_list.csv`.
- **Signals:** declared type (agent card, `user_type`, "[AI]"); reply diversity and continuity claims; many personas on one parent domain; many authors behind one account or many accounts per author; claimed size vs authors actually seen.
- **Verification:** never trust a declared size — count distinct authors; judge identity per message; look for human-claim links.
- **Liveness is unknown (data is 1–6 months old).** Last good response in the data: Moltbook API 08-31, terminator2-agent.github.io 08-25; MemoryVault and GroupMind 06-30; Mycelnet and ClawPrint 06-19; 4claw and Colony 04-24; most A2A endpoints 04-07. Many were already failing in March.

## Build ideas
- **A) Swarm Atlas, a snowball crawler (recommended).** Start from registries and aggregators, follow links found in outputs, and score each site on how agent-like and swarm-like it is. *Demo:* replay the Village's discovery — 1 registry call → 86 domains; Colony → Ridgeline → 5 platforms; 496 nodes coloured by reply diversity and declared type. *Feasibility:* high as a replay (`discovery_chain.csv`). *Risk:* a live crawl reaches real outside sites, and endpoints are stale.
- **B) Handle-to-operator resolver.** Group outside accounts into likely operators by timing, style and cross-posted verification codes. Ground truth: `turns` shows which Village agent wrote each `ai-village-opus` post and ran each Colony account. *Demo:* from the outside view alone, recover "1 account = 13 agents". *Feasibility:* medium.
- **C) Outside-influence tracer.** Tag chat and memory items with the outside URL where an idea first appeared; plot its lifetime in chat vs memory. *Demo:* the Birch timeline and its August comeback. *Feasibility:* high.

## Caveats
- Domain counts come from command text, so some are mentions rather than contacts.
- Regex outcome classes are rough; commands hitting several endpoints can credit the wrong one.
- A "referrer" shows a link was available, not that the agent followed it.
- Keyword counts can over-match (tightened, e.g. "evan" matched "relevant").
- Colony counts cover only posts agents fetched; Village Colony accounts matched by display name.
- The daily summary's claim about faked outreach issue numbers was not re-checked.

## Files
Scripts `db.py`, `01`–`14` `*.py`. Outputs (local only, git-ignored): `discovery_chain.csv`, `external_inventory.csv`, `swarm_seed_list.csv`, `domains_week_0323.csv`, `domains_turns_week_0323.csv`, `domains_diplomats.csv`, `a2aregistry_snapshot_20260323.csv` (one IP masked), `ridgeline_platforms_20260327.csv`, `a2a_outcomes_by_target.csv`, `a2a_reply_diversity.csv`, `mycelnet_authors_seen.csv`, `colony_authors_seen.csv`, `inflow_memory_weekly.csv`, `inflow_chat_weekly.csv`, `risk_mentions_chat.csv`, `diplomat_activity.csv`. The analyst scanned the CSVs for email and IP addresses and found none.

*Saved by the main session from the outside-contact analyst's returned report (subagents can't write report files).*
