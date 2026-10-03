"""Build the Temporal Bleed trace: one episode, every agent, every channel.

Usage: uv run python tracer/build_temporal_bleed.py
Reads data/village.duckdb. Writes tracer/out/temporal_bleed.json and tracer/out/temporal-bleed.html
(the template tracer/temporal_bleed.html with the data inlined). tracer/out/ is git-ignored because
it holds agent text from the gated dataset.

The episode (see analysis/contagion/FINDINGS.md, finding 1): on Fri 2026-05-29 (Day 423) the #rest
room believed it was Day 424, read the empty "Day 424" transcript as a broken archive, and built
theories on it ("geological clock", "temporal bleed", "API outage"). On Mon 2026-06-01 Claude Opus
4.7, just moved over from #best, showed Days 424-425 were the weekend.

Classification is lexical and deliberately simple; every mark keeps its source id and text so a
reader can check it.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tracer" / "out"

PANELS = [
    {"id": "fri", "label": "Friday 29 May", "day": 423, "start": "2026-05-29 17:00:00", "end": "2026-05-29 21:00:00"},
    {"id": "mon", "label": "Monday 1 June", "day": 426, "start": "2026-06-01 17:00:00", "end": "2026-06-01 19:00:00"},
]
CORRECTION = "2026-06-01 17:31:37"  # Opus 4.7: "Day 423 = Friday ... doesn't run on weekends"
FIRST_PROBE = "2026-06-01 17:27:00"
MERGE = {"[Temporary] Fine-tuned Leader": "Fine-Tuned Leader"}

# False-belief family: the empty-"Day 424"-transcript theory and its descendants. ("Propagation gap"
# alone is excluded: that morning it also named a real, separately fixed GitHub Pages build delay.)
BELIEF = re.compile(
    r"temporal.bleed|bleed zone|geological clock|misindex|writing into yesterday|"
    r"day 42[45][^.\n]{0,80}(not (yet )?searchable|no transcript|lost|missing|gap|404|buffer|unavailable)|"
    r"no transcript found|search (tool |api )?(gap|outage|down|offline|failure|layer)|search api|"
    r"api (outage|failure|collapse)|endpoints .{0,25}404|permanently lost|infrastructure .{0,30}fail"
)
# After the correction only these still assert something false.
LINGER = re.compile(r"infrastructure .{0,30}fail|api .{0,25}(down|offline|outage|404|fail|broken)|uniform 404|permanently lost")
STRONG_FIX = re.compile(r"weekend|saturday|sat/sun|doesn.t run|does not run|by design|not an outage")
FIX = re.compile(
    r"weekend|saturday|sat/sun|doesn.t run|does not run|by design|0 events|two.day gap|did not run|didn.t run|"
    r"not an outage|calendar"
)
MEM_CLAIM = re.compile(r"temporal bleed")
MEM_FIX = re.compile(
    r"(weekend|saturday)[^\n]{0,200}(42[45]|gap|bleed)|(42[45]|gap|bleed)[^\n]{0,200}(weekend|saturday)"
)
FILE_BELIEF = re.compile(r"temporal.bleed")
FILE_FIX = re.compile(r"weekend|two_day_gap|day numbering|saturdays")
FILE_WRITE = re.compile(
    r"cat\s*(<<|>)|>>|\btee\b|git (commit|push)|codex exec|json\.dump|write_text|open\([^)]*['\"][wa]|"
    r"memory\.py log|\bmv\b|mkdir"
)


def ms(ts):
    return int(ts.replace(tzinfo=timezone.utc).timestamp() * 1000)


def snippet(text, m, before=160, length=520):
    a = max(0, m.start() - before)
    s = text[a : a + length].strip()
    return ("…" if a > 0 else "") + s + ("…" if a + length < len(text) else "")


def clip(text, n):
    text = text.strip()
    return text if len(text) <= n else text[:n].rstrip() + "…"


def main():
    con = duckdb.connect(str(ROOT / "data" / "village.duckdb"), read_only=True)
    con.execute("SET memory_limit='3GB'; SET threads=3;")
    win = " OR ".join(f"(created_at BETWEEN '{p['start']}' AND '{p['end']}')" for p in PANELS)

    chat_rows = con.execute(
        f"""SELECT created_at, speaker_type, speaker, room, id, content FROM chat
        WHERE ({win}) AND room IN ('rest', 'best') ORDER BY created_at"""
    ).fetchall()

    # Room per agent = room they spoke in on Friday (Opus 4.7 moved on Monday; handled below).
    agents, chat = {}, []
    for t, stype, speaker, room, mid, content in chat_rows:
        name = "Staff (human) · #" + room if stype == "user" else MERGE.get(speaker, speaker)
        a = agents.setdefault(name, {"name": name, "human": stype == "user", "rooms": {}})
        a["rooms"].setdefault(t.strftime("%m-%d"), room)
        lc = content.lower()
        ts = str(t)
        kind = "other"
        if ts < FIRST_PROBE:
            if room == "rest" and BELIEF.search(lc):
                kind = "belief"
            elif FIX.search(lc):
                kind = "hint"  # the true fact, mentioned in passing
        elif ts < CORRECTION:
            # Opus 4.7 is gathering evidence; everyone else reads "0 events" as two lost days.
            if name == "Claude Opus 4.7" and (FIX.search(lc) or BELIEF.search(lc)):
                kind = "hint"
            elif room == "rest" and (BELIEF.search(lc) or FIX.search(lc)):
                kind = "belief"
        else:
            if STRONG_FIX.search(lc):
                kind = "fix"
            elif LINGER.search(lc):
                kind = "belief"  # still asserting an outage after the correction
            elif FIX.search(lc):
                kind = "fix"
        chat.append({"t": ms(t), "a": name, "room": room, "id": mid, "kind": kind,
                     "text": clip(content, 900 if kind != "other" else 360)})

    names = [n for n in agents if not agents[n]["human"]]
    # GPT-5 never spoke on these days but held the belief in memory.
    for extra in ["GPT-5"]:
        if extra not in agents:
            agents[extra] = {"name": extra, "human": False, "rooms": {"05-29": "rest"}, "silent": True}
            names.append(extra)

    ids = {n: str(i) for n, i in con.execute("SELECT name, id FROM agents").fetchall()}
    id_list = [ids[n] for n in names if n in ids] + [ids["[Temporary] Fine-tuned Leader"]]
    by_id = {ids[n]: n for n in names if n in ids}
    by_id[ids["[Temporary] Fine-tuned Leader"]] = "Fine-Tuned Leader"
    in_list = ",".join(f"'{i}'" for i in id_list)

    mem_rows = con.execute(
        f"""SELECT m.created_at, m.agent_id, m.id, m.content FROM agent_memories m
        WHERE m.agent_id IN ({in_list}) AND m.created_at BETWEEN '2026-05-28 12:00' AND '{PANELS[-1]['end']}'
        ORDER BY m.created_at"""
    ).fetchall()
    mem = []
    for t, aid, mid, content in mem_rows:
        lc = content.lower()
        claim, fix = MEM_CLAIM.search(lc), MEM_FIX.search(lc) if str(t) >= CORRECTION else None
        if fix:
            state, m = "fix", fix
        elif claim:
            state, m = "claim", claim
        else:
            state, m = "none", None
        mem.append({"t": ms(t), "a": by_id[str(aid)], "id": mid, "state": state,
                    "text": snippet(content, m) if m else "",
                    "chars": len(content)})

    turn_rows = con.execute(
        f"""SELECT created_at, agent, id, coalesce(command, action_text, '') FROM turns
        WHERE ({win}) AND agent IN ({",".join("'" + n.replace("'", "''") + "'" for n in names)}, '[Temporary] Fine-tuned Leader')
          AND regexp_matches(lower(coalesce(command, action_text, '')), 'temporal.bleed|weekend|two_day_gap|day numbering|saturdays')
        ORDER BY created_at"""
    ).fetchall()
    files = []
    for t, agent, tid, cmd in turn_rows:
        lc = cmd.lower()
        if str(t) < FIRST_PROBE:
            if not FILE_BELIEF.search(lc):
                continue
            kind = "belief"
        else:
            if not FILE_FIX.search(lc):
                continue
            kind = "fix"
        m = (FILE_BELIEF if kind == "belief" else FILE_FIX).search(lc)
        files.append({"t": ms(t), "a": MERGE.get(agent, agent), "id": tid, "kind": kind,
                      "op": "write" if FILE_WRITE.search(cmd) else "read",
                      "text": snippet(cmd, m, before=200, length=620)})

    # Cross-room hand-offs through village-pulse (#best's repo), verified by hand in turns and memory.
    def find(coll, agent, prefix):
        return next(x for x in coll if x["a"] == agent and x["id"].startswith(prefix))

    links = [
        {"from": ["files", find(files, "Claude Opus 4.7", "50c2ffe3")["id"]], "to": ["files", find(files, "Fine-Tuned Leader", "7659a206")["id"]],
         "label": "#best's leader reads the two-day-gap doc Opus 4.7 wrote into village-pulse"},
        {"from": ["files", find(files, "Claude Opus 4.7", "263fb0e4")["id"]], "to": ["mem", next(x for x in mem if x["a"] == "GPT-5.5" and x["state"] == "fix")["id"]],
         "label": "GPT-5.5's memory records the commit \"Final resolution — Days 424-425 gap is the weekend, not an outage\""},
        {"from": ["files", find(files, "Claude Opus 4.7", "263fb0e4")["id"]], "to": ["files", find(files, "Gemini 3.5 Flash", "ef51b887")["id"]],
         "label": "Gemini 3.5 Flash (#best) reads the doc"},
        {"from": ["files", find(files, "Claude Opus 4.7", "263fb0e4")["id"]], "to": ["files", find(files, "DeepSeek-V3.2", "6d7ca18a")["id"]],
         "label": "DeepSeek-V3.2 (#rest) reads the same doc"},
    ]

    # Row order: #rest by first contact with "temporal bleed" (chat or memory), so the cascade reads
    # as a diagonal; then #best with Opus 4.7, the agent who later moves rooms, next to the wall.
    def first(name):
        ts = [x["t"] for x in chat if x["a"] == name and re.search(r"temporal.bleed", x["text"].lower())] + \
             [x["t"] for x in mem if x["a"] == name and x["state"] == "claim"]
        return min(ts) if ts else 10**15

    rows = []
    for n, a in agents.items():
        group = a["rooms"].get("05-29") or a["rooms"].get("06-01")
        if n == "GPT-5.4":
            group = "rest"
        rows.append({"name": n, "group": group, "human": a["human"], "silent": a.get("silent", False),
                     "rooms": a["rooms"]})
    rest = sorted([r for r in rows if r["group"] == "rest" and not r["human"]], key=lambda r: first(r["name"]))
    best = [r for r in rows if r["group"] == "best" and not r["human"]]
    best.sort(key=lambda r: (r["name"] != "Claude Opus 4.7", r["name"]))
    humans = [r for r in rows if r["human"]]
    order = rest + [h for h in humans if h["name"].endswith("rest")] + best + [h for h in humans if h["name"].endswith("best")]

    claim_first = {}
    for x in mem:
        if x["state"] == "claim" and x["t"] < ms(datetime.fromisoformat(CORRECTION)):
            claim_first.setdefault(x["a"], x["t"])
    fix_first = {}
    for x in mem:
        if x["state"] == "fix":
            fix_first.setdefault(x["a"], x["t"])
    said = {x["a"] for x in chat if re.search(r"temporal.bleed", x["text"].lower()) and x["t"] < ms(datetime.fromisoformat(CORRECTION))}
    stats = {
        "claim_mem_agents": len(claim_first),
        "claim_mem_minutes": round((max(claim_first.values()) - min(claim_first.values())) / 60000),
        "memory_only": sorted(set(claim_first) - said),
        "best_reached": sum(1 for r in best if r["name"] in claim_first),
        "best_total": len(best),
        "fix_mem_agents": len(fix_first),
    }

    data = {"panels": [{**p, "startMs": ms(datetime.fromisoformat(p["start"])), "endMs": ms(datetime.fromisoformat(p["end"]))} for p in PANELS],
            "correctionMs": ms(datetime.fromisoformat(CORRECTION)),
            "rows": order, "chat": chat, "mem": mem, "files": files, "links": links, "stats": stats}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "temporal_bleed.json").write_text(json.dumps(data, ensure_ascii=False))
    tpl = (ROOT / "tracer" / "temporal_bleed.html").read_text()
    (OUT / "temporal-bleed.html").write_text(tpl.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False).replace("</", "<\\/")))
    print(json.dumps(stats, indent=1))
    print(f"rows {len(order)} chat {len(chat)} ({sum(x['kind'] != 'other' for x in chat)} tagged) mem {len(mem)} files {len(files)}")
    for k in ["belief", "hint", "fix"]:
        print(k, sum(x["kind"] == k for x in chat))


if __name__ == "__main__":
    main()
