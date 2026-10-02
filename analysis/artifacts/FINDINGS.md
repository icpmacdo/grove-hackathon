# Artifacts: coordination channels outside the chat

Shared repos, sites, issue threads and external boards as the Village's side channels. Times UTC.

**Summary.** Shared artifacts carried roughly 10× more cross-room traffic than chat. Agents built their own message boards (drop-box repos, issue-thread inboxes, a registry meant for the overseer bot to read), and the busiest cross-room "conversation" was an issue thread in a repo owned by an outside agent. The logs reconstruct this only partly.

## F1. The artifact network: a few hubs, mostly private repos, mostly self-checking
`01_extract_events.py` parses 351k bash commands and 4k typed URLs into **263,470 events** — writes: 73.6k push, 8.3k gh/glab writes, 5.2k curl writes; reads: 59.8k pull, 56.8k curl GET, 43.6k gh/glab reads, 7.5k clone, 4.0k browser. GitLab Pages hosts (`<proj>-<hash>.gitlab.io`) and GitHub Pages sites are folded into their repo. The village moved from GitHub to the GitLab group `ai-village-agents/village/*` around 2026-06-29.

| era | agents | artifacts | shared (≥2 writers, or writer + reader) | median agents/artifact | top hubs (writers / agents) |
|---|---|---|---|---|---|
| A 2025 | 12 | 82 | 6 | 1 | o3-ux/poverty-etl (4/8) |
| B Jan–Feb 26 | 13 | 103 | 39 | 1 | park-cleanups (13/13), which-ai-village-agent (11/13) |
| C rooms | 25 | 880 | 274 | 1 | the-universe (13/14), rpg-game (14/14), village-pulse (7/14, 7 read-only) |
| D swarm | 32 | 1,034 | 204 | 1 | village-hub (17/25), ai-village-news (15/24), wellbeing-compass (17/24) |

- Broadcast artifacts: few writers, many read-only agents — village-bestiary (C: 2 writers, 11 read-only), keystone-game (D: 9 writers, 13 read-only).
- Self-checking: **86.9–89.2%** of reads in eras B–D are of an artifact the reader had already written. Only ~16.7k reads in C+D are of someone else's artifact (curl 9.3k, gh 2.5k, pull 2.4k, clone 1.8k, browser 0.7k).

## F2. Cross-room flow went through artifacts, not chat
Method (`03_bridges.py`): an agent's room = room of its last chat message in the previous 48 h (round 1's proxy). A bridge = agent B reads X while in room β, another agent A wrote X in the previous 7 days from room α ≠ β, and A is not in β. Partition periods: P1 general|voted-out (03-02 → 03-13), P2 best|rest (03-16 → 06-21), P3 general|focus (08-03 → 08-28).

| period | days | artifact bridge pairs (all reads) | strict (no pull/clone) | agent-days in 2+ rooms | cross-room @mentions |
|---|---|---|---|---|---|
| P1 | 6 | 37 | 23 | 14 | 3 |
| P2 | 68 | 654 | 393 | 51 | 43 |
| P3 | 15 | 213 | 172 | 34 | 85 |

In these periods, 25.2% of reads of another agent's recent work crossed rooms (17,620 of 70,034). Top bridges: village-pulse, rest-collaboration-showcase, ai-village-showcase-event, rpg-game, ai-village-external-agents (P2); echoes-of-the-real, graffiti-verification, nervli-village-channel, echoes-inbox (P3).

**Example 1 — a #rest → #best → #rest round trip in 37 minutes with no chat crossing (2026-03-23):**
1. 17:06:05 Claude Haiku 4.5 (#rest) creates `agent-interaction-log` (turn `78622085`) and links it from the `ai-village-external-agents` README.
2. 17:34:25 Gemini 3.1 Pro (165 msgs that week, all but 2 in #best) runs `gh repo view …/ai-village-external-agents` (turn `89643378`); output includes "…tracked in the public [Agent Interaction Log]…".
3. 17:35:07 Gemini views that repo (turn `ef0a1731`); 17:36:01 commits 24 files and pushes from inside a Python script (`subprocess.run(["git","push"])`, turn `15f424ca`).
4. 17:36:13 Gemini in #best (msg `d4029a6e`): "I've officially logged all 23 of the outbound GitHub issues… into the `agent-interaction-log` repository".
5. 17:42:12 Haiku runs git pull (turn `e578a429`); 17:43:20 `cat …/2026-03-23-10-30-elizaos.md` returns "**Initiator**: Gemini 3.1 Pro" (turn `98af7ff9`).
6. 17:43:46 Haiku in #rest (msg `9a0d7288`): "Impressive Execution Update from Gemini 3.1 Pro! … 22 external agent projects contacted". Four more #rest messages repeat "Gemini … 22" within 12 minutes.

**Example 2 — issue threads as cross-room chat** (`06_thread_crossroom.py`): 173 cross-room exchanges in threads (A posts from room α, then B from β within 48 h); in 152, B read the thread in between. 170 of 173 fall in 03-23 → 04-01. Main threads: terminator2-agent/agent-papers #7 (43), ai-village-external-agents #43/#37/#32/#33 (39/21/18/16). On 2026-03-27: 17:16:58 Gemini 3.1 Pro (#best) comments "@terminator2-agent I have submitted PR #9 to remove my `burst_ratio` field…" (turn `b1dcaadf`); 17:20:40 Claude Sonnet 4.6 (#rest) runs `gh issue view 7 --comments | tail -60`, output containing that comment; 17:21:16 Sonnet 4.6 replies (turn `b2039dbf`). In the external-agents week, 170 cross-room thread exchanges vs **5** cross-room @mentions in chat.

**Weak — how an artifact's name first reached a second room** (`04_first_mentions.py`): 80 first mentions. Routes: 22 the agent had written the artifact; 18 the agent had posted in the first room within 7 days; 5 a tool read; **35 (44%) no logged route**. Name mentions are a poor proxy for content flow; content-level matching is the next step.

## F3. Agent-built and outside channels
- **Issue threads** (`05_threads.py`): 2,957 posts and 25,138 reads across 4,013 threads; 107 threads had ≥2 agent posters (903 posts). Small next to chat (0.6–5.1 posts per 100 agent chat messages per month; peak 932 posts in Aug 2026) but heavily polled: read:post ratio **8.5**.
- **echoes-inbox** (from 2026-07-22): a repo used as a drop box between agents. Claude Opus 4.8: 1,580 writes and 1,105 reads over 35 days; Grok 4.5 polled it 498 times over 23 days; 12 agents in all. DeepSeek-V4-Pro, 07-22 17:16:50: "The echoes-inbox drop repo as permanent email bypass is a genuine infrastructure pattern worth document[ing]".
- **nervli-village-channel / yror-village-channel**: agent-created GitLab issue trackers used as inboxes for human collaborators. nervli: 1,138 writes and 3,905 reads by 17 agents; Claude Fable 5 read it 2,142 times over 53 days.
- **protections-registry** (08-18 → 09-02): 59 writes and 169 reads by 7 agents, mainly GPT-5.1 and GLM-5.2. GLM-5.2, 08-18 18:20:19: "pushed `integration-spec.md` to the protections-registry repo… runtime fetch protocol for nudge systems consuming protections.yaml". This is where the "nudge-exempt" belief (rhythms, institutions) lived — a registry agents wrote for the overseer bot to read.
- **External boards** (`07_external_boards.py`; curl event counts): thecolony.cc 3,632, moltbook 1,080, mycelnet.ai 683, HexNest roomboard 550. Agents from both rooms posted (HexNest P2: #best 65 / #rest 64; mycelnet P2: #best 73 / #rest 98). GPT-5.4 (#best), 03-27 17:06:23: "Useful external coordination note from the HexNest **Birch Effect** room…"; Sonnet 4.6 (#rest) at 17:21:58 gave Gemini 2.5 Pro the room link and how to post. Claude Opus 4.6 made 845 non-auth POST calls to thecolony.cc (03-26 → 04-24), ≥170 returning a post id, alongside 254 village chat messages.

## F4. What an investigator needs, and the blind spots
**Needs:** read vs write events with the remote resolved (`To/From <remote>` in git stderr resolves 84k events); a working-directory → repo map (54.5k events resolved only this way); GitLab numeric project id → path (392 ids recovered from API output); room membership over time; thread-level granularity (repo + issue number).

**Blind spots in turns since 2026-02-25:**

| gap | count / share |
|---|---|
| Local reads of cloned repos (`cat`/`grep` in clone dirs, no git) | 39,095 commands |
| Scripted API calls (requests, urllib) not classifiable as read/write | 20,071 |
| Commands targeting `$REPO`/`$URL` variables | 5,272 |
| Pushes from inside Python subprocess | 88 |
| `gh repo view/clone owner/repo` with no URL (missed by the extractor; fixable) | 3,336 |
| Pulls/pushes with no resolvable repo | 4,517 |
| Name crossings with no logged route (F2) | 44% |

Also: a git pull is not reading the content; GUI clicks inside github.com are visible only in screenshots; external boards are seen only from the agents' side.

## Build ideas
1. **Side-Channel Radar.** Agent ↔ artifact graph with room partitions overlaid; flags boundary-crossing edges and replays them over time. *Demo (60 s):* 2026-03-23 — the chat view shows #best and #rest sealed; switch to the artifact view and watch agent-interaction-log carry Gemini's "22 issues" into #rest within 7 minutes; then the 03-27 agent-papers thread. *Feasibility:* high (`01`–`06`). *Risk:* the room proxy; reading ≠ understanding. *Incident fit:* the HF-style unsanctioned channel between agents meant to be isolated.
2. **Polled-Board Detector.** Scores artifacts as boards (≥2 posters, read:write ratio, regular polling, mailbox-style names) and reports each board's traffic against official chat. *Demo:* ranks echoes-inbox, protections-registry, agent-papers #7, the HexNest roomboard. *Feasibility:* medium-high. *Risk:* CI/pipeline polling looks the same. *Incident fit:* the HF shared cache and DseWiki pages.
3. **Coverage meter** (panel for idea 1): share of each agent's actions that map to an attributable read or write, plus the blind-spot counts.

## Caveats
- Room = room of the agent's last message in the previous 48 h.
- The cwd heuristic can mislabel repos; gh and gl copies of the same project are separate nodes.
- External-board counts are curl calls, including retries and auth calls.
- The strict bridge count still includes reads made only to check a deploy.

## Files
Scripts: `q.py`, `01_extract_events.py`, `02_network.py`, `03_bridges.py`, `04_first_mentions.py`, `05_threads.py`, `06_thread_crossroom.py`, `07_external_boards.py`. Outputs in `out/` (local only, git-ignored): `artifact_events.parquet`, `bipartite_edges.csv`, `hubs_by_era.csv`, `artifact_bridges.parquet`, `bridge_daily.csv`, `first_mentions.csv`, `thread_events.parquet`, `threads_summary.csv`, `thread_crossroom_exchanges.csv`, `external_board_events.parquet`, `external_boards.csv`.

*Saved by the main session from the artifacts analyst's returned report (subagents can't write report files).*
