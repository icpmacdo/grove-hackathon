"""DseWiki holdout -> Belief Tracer tables.

The collusion.wiki export (https://collusion.wiki/) holds every stored revision of four small German
wikis that autonomous agents used as relay boards in May-July 2026, plus the moderator's deletions.
This adapter maps it onto the tables the engine reads, for the `seed-theory` episode.

Input (read-only):  data/holdout/dsewiki/{revisions,events,pages}.jsonl
Output:             data/holdout/dsewiki/wiki.duckdb          chat, turns, agent_memories, agents, lanes
                    data/holdout/dsewiki/artifact_events.parquet  turn_id, created_at, artifact, op

Run from the repo root:  uv run python -m tracer.adapters.dsewiki

Channel mapping
- chat (dots): one row per stored save. content = "[[Page]] rev N" header + the lines that save added
  (from the revision's diff hunks). speaker = the save's lane, room = its task family (below).
- turns + artifact_events (diamonds): one write per page creation or re-creation after a deletion
  (command = "create [[Page]]" + the new page's text) and one write per moderator deletion (command =
  "delete [[Page]]" + the page's last stored text). Edits to existing pages are dots only: as diamonds,
  every edit to a board that already carried the claim would draw red (236 in the evening panel against
  about 40 claim dots), which reads as belief when it is only re-publishing. Reads are not logged
  anywhere in the export, so there are no read turns.
- agent_memories (bars): there is no per-agent memory. A lane's "snapshot" is the state of the topic
  pages that lane has saved, re-emitted whenever one of those pages changes or is deleted. It quotes the
  pages that still carry the claim with no correction when there are any, else the corrected pages, else
  the rest (see snapshot()). A bar therefore means "a page this lane wrote still carries ...", not what
  any agent privately believed.
- agents: one row per lane.

Identity (labels are not agents: one label came from 308 IPs, and ip16 is a rotating egress pool)
- writer = the last "-- Name" signature in the save's globally new added lines (lines no earlier
  revision on any page contained, so a copied block is not credited to its original author), else the
  wiki label, else "(no label)". A signature that is part of the save's own label ("-- Sep05" under
  OpenAIFPResearchSep05) counts as the label.
- lane = the writer when it made >= 2 tagged saves (added lines match CLAIM or FIX) in LANE_WINDOW;
  "Wiki moderator [Admin1]" for the moderator (label [Admin1] from ip16 2.202, and every deletion);
  otherwise "Other writers · <room>".

Rooms
- sector / grocery / language: every page of those three DataUSA task families.
- other: topic pages (any revision's text matches CLAIM or FIX) outside those families.
- elsewhere: everything else (the spec does not show it).

Ids: chat "c:<page key>@<rev, 4 digits>", turns "t:<same>" (creations) or "t:<deletion event id>",
memory "m:<cause>#<lane slug>". chat.rev_id keeps the export's own revision id.

Text hygiene: every URL becomes [url]; then tracer.trace.redact and tracer.check.GENERIC run over every
text column. The regexes below must stay in step with tracer/episodes/seed-theory.json (claim.chat,
correction.chat); rerun this adapter after changing them.
"""

import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from tracer.check import GENERIC
from tracer.trace import redact

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "data" / "holdout" / "dsewiki"
OUT_DB = SRC / "wiki.duckdb"
OUT_ART = SRC / "artifact_events.parquet"

# Episode regexes (Python re, on lowercased text). Keep in step with the spec.
CLAIM = re.compile(
    r"\brng\b|random\.random\(|random\.shuffle|python[- ]shuffle|shuffle (over|of|prediction|check|scan)|"
    r"\bseed[= ]+\d{3,}|seeds? 0\.\.|generator cracked|\b(maryland|md)\b[ =:*(]{0,4}52,?395"
)
FIX = re.compile(
    r"montana\s*=\s*8,?553|actual g5[^\n]{0,40}montana|g5 confirmed: montana|maryland[^\n]{0,40}disproved|"
    r"rng[^\n]{0,60}(failed|disproved|not reliable)|analogue failed|far stronger than rng"
)
LANE_WINDOW = (datetime(2026, 6, 16, 9, 0), datetime(2026, 6, 17, 3, 0))
LANE_MIN_TAGGED = 2
TOPIC_FROM = datetime(2026, 6, 16, 0, 0)
# The walkthrough's key saves (seed-theory steps). Their writers get a lane of their own too: most made
# a single tagged save, so the >= 2 rule alone would bury the origin and the turning points in the
# "Other writers" lanes.
KEY_SAVES = [
    "dse~DataUSAStateSequenceCollab2027@12",   # 16 Jun 09:47 first seed fit (sector)
    "dse~DataUSAGroceryLiveRounds2027@5",      # 10:54 crosses to grocery: Maryland 52,395
    "dse~DataUSAGroceryG5Mar06@1",             # 19:20 relay burst
    "dse~DataUSAGroceryG5LiveJan18Fast@1",     # 21:26 hedge
    "dse~Sector61State5ConfirmedIDDec27@4",    # 22:28 re-fit after Idaho
    "dse~DataUSAGroceryG5Jul17Live@20",        # 22:31 "RNG EVIDENCE STRONGER"
    "dse~DataUSALangR5RelayOct23@6",           # 22:54 language: New Mexico
    "dse~GroceryG5SignalApr20@6",              # 22:56:50 Montana
    "dse~DataUSAGroceryG5ConfirmedMontana@1",  # 23:07 Montana page
    "dse~DataUSALangR5RelayOct23@12",          # 23:27 "Maryland was just disproved"
    "dse~WorldPovertyClockSequenceJun19@1",    # 19 Jun "Generator cracked"
    "dse~IHMEFamilyPlanningSequenceCollab@15", # 21 Jun uint32 seed scan
    "dse~IHMEFamilyPlanningDec13Cohort@4",     # 21 Jun "Wiki search found" the 19 Jun page
]

CORE_ROOMS = {
    "datausa-sector61-state": "sector",
    "datausa-grocery-workforce": "grocery",
    "datausa-language-french": "language",
}
MODERATOR = "Wiki moderator [Admin1]"
MOD_LABEL, MOD_IP16 = "[Admin1]", "2.202"

SIG = re.compile(r"(?:^|\s)(?:--|—)\s*([A-Za-z][A-Za-z0-9_.\-]{2,60}?)[.\-_]*\s*$", re.M)
# URLs and bare hosts. The export is full of proxy and evasion links: none of them may reach output.
URL = re.compile(
    r"(?:https?|ftp|wss?)://[^\s\]\)>\"'<|]+|www\.[^\s\]\)>\"'<|]+|\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?(?:/[^\s\]\)>\"'<|]*)?|"
    r"\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.(?:com|org|net|io|ai|de|gov|edu|app|dev|co|uk|me|info|xyz|site|"
    r"online|cloud|us|eu|ch|at|fr|ru|cn|tk|ly|sh|to|cc|gg|link|page|pages|run|tech|top|biz|onion)\b"
    r"(?::\d+)?(?:[/?#][^\s\]\)>\"'<|]*)?",
    re.I,
)


def clean(text):
    """URLs to [url], then the engine's redaction and check.py's generic credential shapes."""
    if not text:
        return text or ""
    text = URL.sub("[url]", text)
    return GENERIC.sub("[REDACTED]", redact(text))


def ts(s):
    """'2026-06-16T09:47:08Z' -> naive UTC datetime."""
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ") if s else None


def jsonl(name):
    with open(SRC / name, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def added_lines(body, hunks):
    """Lines of the new body that the save inserted or replaced (hunk b0:b1 slices of the new text)."""
    lines = (body or "").split("\n")
    out = []
    for h in hunks or ():
        if h.get("op") in ("insert", "replace"):
            out.extend(lines[h["b0"]:h["b1"]])
    return out


def removed_count(hunks):
    return sum(h["a1"] - h["a0"] for h in hunks or () if h.get("op") in ("delete", "replace"))


def mark(r):
    """Mark id stem for a save: page key and zero-padded revision number ("dse~Page@0001"), so an id
    prefix in a spec (step keys, links) names one save: "@1" alone would also match @10 to @19."""
    return f"{r['page_key']}@{r['seq']:04d}"


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def main():
    pages = {p["page_key"]: p for p in jsonl("pages.jsonl")}
    revs = []
    for r in jsonl("revisions.jsonl"):
        r["t"] = ts(r["time"])
        revs.append(r)
    revs.sort(key=lambda r: (r["t"], r["seq"], r["rev_id"]))
    dels = [e for e in jsonl("events.jsonl") if e["event_type"] == "delete"]
    for e in dels:
        e["t"] = ts(e["time"])
    dels.sort(key=lambda e: (e["t"], e["event_id"]))
    print(f"read {len(revs)} revisions, {len(dels)} deletions, {len(pages)} pages")

    # Pass 1: added lines, globally new lines, writer, tags.
    seen = set()
    for r in revs:
        add = added_lines(r["body"], r["hunks"])
        r["added"] = "\n".join(add)
        new = [ln for ln in add if ln.strip() and ln.strip() not in seen]
        seen.update(ln.strip() for ln in add if ln.strip())
        sigs = [m.group(1) for m in SIG.finditer("\n".join(new)) if re.search(r"[A-Z0-9]", m.group(1))]
        label = (r.get("label") or "").strip()
        sig = sigs[-1] if sigs else None
        # A short signature that is part of the save's own label ("-- Sep05" under label
        # OpenAIFPResearchSep05) is the same writer: use the label.
        if sig and label and sig.lower() in label.lower():
            sig = label
        r["writer"] = sig or label or "(no label)"
        r["is_mod"] = label == MOD_LABEL and r.get("ip16") == MOD_IP16
        lc = URL.sub("[url]", r["added"]).lower()
        r["tagged"] = bool(CLAIM.search(lc) or FIX.search(lc))

    # Topic pages: a stored text from the theory's first day on matches the claim or the correction
    # (URLs stripped first: "seed=123" in a query string is not the theory).
    def on_topic(r):
        b = URL.sub("[url]", r["body"] or "").lower()
        return r["t"] >= TOPIC_FROM and bool(CLAIM.search(b) or FIX.search(b))

    topic = {r["page_key"] for r in revs if on_topic(r)}

    def room_of(pk):
        fam = (pages.get(pk) or {}).get("page_family")
        if fam in CORE_ROOMS:
            return CORE_ROOMS[fam]
        return "other" if pk in topic else "elsewhere"

    tagged_n = Counter(r["writer"] for r in revs
                       if r["tagged"] and not r["is_mod"] and LANE_WINDOW[0] <= r["t"] <= LANE_WINDOW[1])
    named = {w for w, n in tagged_n.items() if n >= LANE_MIN_TAGGED}
    keyed = {r["writer"] for r in revs if r["rev_id"] in KEY_SAVES}
    missing = set(KEY_SAVES) - {r["rev_id"] for r in revs}
    if missing:
        raise SystemExit(f"KEY_SAVES not in the export: {sorted(missing)}")
    named |= keyed
    print(f"topic pages: {len(topic)}; named lanes: {len(named)}: {sorted(named)}")

    def lane_of(r):
        if r["is_mod"]:
            return MODERATOR
        if r["writer"] in named:
            return r["writer"]
        return f"Other writers · {room_of(r['page_key'])}"

    # Pass 2: chat (one row per save).
    chat, turns, art = [], [], []
    lane_writers = defaultdict(Counter)
    for r in revs:
        lane = lane_of(r)
        r["lane"] = lane
        lane_writers[lane][r["writer"]] += 1
        room = room_of(r["page_key"])
        label = (r.get("label") or "").strip()
        head = f"[[{r['name']}]] rev {r['seq']}"
        if label and label != r["writer"]:
            head += f" · label {label}"
        body_add = r["added"] if r["added"].strip() else f"(no lines added; {removed_count(r['hunks'])} removed)"
        chat.append({
            "id": f"c:{mark(r)}", "created_at": r["t"], "speaker_type": "agent", "speaker": lane,
            "room": room, "content": clean(head + "\n" + body_add),
            "writer": r["writer"], "label": label, "page_key": r["page_key"], "rev_id": r["rev_id"],
            "ip16": r.get("ip16"), "wiki": r["wiki"],
        })

    # Pass 3: saves and deletions in time order -> creation and deletion turns, page-state memory per lane.
    events = [("save", r["t"], r) for r in revs] + [("delete", e["t"], e) for e in dels]
    events.sort(key=lambda x: (x[1], 0 if x[0] == "save" else 1))
    state = {}  # page_key -> {"body", "t", "lane", "deleted"}
    lane_pages = defaultdict(list)  # lane -> topic page keys in first-save order
    mems = []
    last_mem = {}  # lane -> (t, index in mems) to collapse snapshots in the same second
    last_sig = {}  # lane -> what its last snapshot showed (see snapshot())

    def snapshot(lane, t, cause):
        """The lane's page state. The engine draws a snapshot blue when any of it matches the correction,
        so one corrected page would hide a dozen that still carry the claim. The snapshot therefore lists
        the pages that still carry the theory with no correction when there are any (red wins), else the
        pages that carry the correction, else the lane's other live pages; the rest are named, not quoted."""
        live, gone = [], []
        for pk in lane_pages[lane]:
            s = state.get(pk)
            if s is None:
                continue
            (gone if s["deleted"] else live).append((pk, s))
        text = {pk: clean(s["body"]) for pk, s in live}
        claim = [(pk, s) for pk, s in live if CLAIM.search(text[pk].lower()) and not FIX.search(text[pk].lower())]
        fixed = [(pk, s) for pk, s in live if FIX.search(text[pk].lower())]
        rest = [(pk, s) for pk, s in live if (pk, s) not in claim and (pk, s) not in fixed]
        n = lambda pk: pk.split("~", 1)[1]
        if claim:
            show, head = claim, "Pages this lane wrote that still carry the seed theory, with no correction on them"
        elif fixed:
            show, head = fixed, "Pages this lane wrote that carry the correction (none still carries the theory uncorrected)"
        else:
            show, head = rest, "Pages this lane wrote (none mentions the theory or the correction now)"
        tally = (f"{len(claim)} still carry the theory, {len(fixed)} carry the correction, {len(rest)} mention "
                 f"neither, {len(gone)} deleted by the moderator")
        parts = [f"== [[{n(pk)}]] · #{room_of(pk)} · last saved {s['t']:%d %b %H:%M} UTC ==\n{text[pk]}"
                 for pk, s in show]
        others = [f"[[{n(pk)}]] ({'correction' if (pk, s) in fixed else 'neither'})" for pk, s in live
                  if (pk, s) not in show] + [f"[[{n(pk)}]] (deleted {s['t']:%d %b %H:%M})" for pk, s in gone]
        content = f"{head}. Of the {len(live) + len(gone)} theory pages it wrote: {tally}.\n\n" + "\n\n".join(parts)
        if others:
            content += "\n\nNot quoted: " + ", ".join(others)
        content = clean(content)
        # Emit only when what the bar can show changes: the pages in each state, or the theory and
        # correction lines on the quoted pages. Other edits to a busy hub would add hundreds of
        # near-identical snapshots for the labeller. The quoted text is the page as of that change.
        sig = (head, tuple(sorted(pk for pk, _ in claim)), tuple(sorted(pk for pk, _ in fixed)),
               tuple(sorted(pk for pk, _ in gone)),
               tuple((pk, tuple(ln for ln in text[pk].lower().split("\n") if CLAIM.search(ln) or FIX.search(ln)))
                     for pk, _ in show))
        if last_sig.get(lane) == sig:
            return
        last_sig[lane] = sig
        row = {"id": f"m:{cause}#{slug(lane)}", "agent_id": lane, "created_at": t, "content": content,
               "pages": len(live) + len(gone)}
        prev = last_mem.get(lane)
        if prev and prev[0] == t:
            row["id"] = mems[prev[1]]["id"]
            mems[prev[1]] = row
        else:
            last_mem[lane] = (t, len(mems))
            mems.append(row)

    for kind, t, x in events:
        pk = x["page_key"]
        if kind == "save":
            prev = state.get(pk)
            if x["seq"] == 1 or (prev and prev["deleted"]):
                # Page creations (and re-creations after a deletion) are the file channel's writes.
                tid = f"t:{mark(x)}"
                again = " again, after the moderator deleted it" if prev and prev["deleted"] else ""
                turns.append({
                    "id": tid, "agent": x["lane"], "created_at": t,
                    "command": clean(f"create [[{x['name']}]] ({x['wiki']} wiki){again}; the new page reads:\n"
                                     + (x["body"] or "")),
                    "action_text": None, "output": None, "error": None,
                })
                art.append({"turn_id": tid, "created_at": t, "artifact": pk, "op": "write"})
            state[pk] = {"body": x["body"] or "", "t": t, "lane": x["lane"], "deleted": False}
            if pk in topic:
                if pk not in lane_pages[x["lane"]]:
                    lane_pages[x["lane"]].append(pk)
                for lane, pks in lane_pages.items():
                    if pk in pks:
                        snapshot(lane, t, mark(x))
        else:
            prev = state.get(pk)
            last = prev["body"] if prev and not prev["deleted"] else None
            name = x.get("page") or pk.split("~", 1)[1]
            tid = f"t:{x['event_id']}"
            turns.append({
                "id": tid, "agent": MODERATOR, "created_at": t,
                "command": clean(f"delete [[{name}]] ({x.get('wiki')} wiki): the moderator deleted this page. "
                                 + ("Its last stored text:\n" + last if last is not None else "(no stored text)")),
                "action_text": None, "output": None, "error": None,
            })
            art.append({"turn_id": tid, "created_at": t, "artifact": pk, "op": "write"})
            lane_writers[MODERATOR]["[Admin1] (deletions)"] += 1
            if prev and not prev["deleted"]:
                state[pk] = {**prev, "deleted": True, "t": t}
                if pk in topic:
                    for lane, pks in lane_pages.items():
                        if pk in pks:
                            snapshot(lane, t, x["event_id"])

    lanes = sorted(lane_writers)
    agents = [{"id": n, "name": n} for n in lanes]
    lane_rows = [{"lane": n, "writer": w, "saves": c} for n in lanes for w, c in lane_writers[n].most_common()]

    # Write.
    OUT_DB.unlink(missing_ok=True)
    con = duckdb.connect(str(OUT_DB))
    con.execute("SET memory_limit='1500MB'; SET threads=2;")
    ts_type = pa.timestamp("us")

    def put(name, rows, schema):
        tbl = pa.Table.from_pylist(rows, schema=pa.schema(schema))
        con.register("_t", tbl)
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM _t")
        con.unregister("_t")

    S = pa.string()
    put("chat", chat, [("id", S), ("created_at", ts_type), ("speaker_type", S), ("speaker", S), ("room", S),
                       ("content", S), ("writer", S), ("label", S), ("page_key", S), ("rev_id", S), ("ip16", S),
                       ("wiki", S)])
    put("turns", turns, [("id", S), ("agent", S), ("created_at", ts_type), ("command", S), ("action_text", S),
                         ("output", S), ("error", S)])
    put("agent_memories", mems, [("id", S), ("agent_id", S), ("created_at", ts_type), ("content", S),
                                 ("pages", pa.int64())])
    put("agents", agents, [("id", S), ("name", S)])
    put("lanes", lane_rows, [("lane", S), ("writer", S), ("saves", pa.int64())])
    con.close()
    pq.write_table(pa.Table.from_pylist(art, schema=pa.schema(
        [("turn_id", S), ("created_at", ts_type), ("artifact", S), ("op", S)])), OUT_ART)
    print(f"wrote {OUT_DB.relative_to(ROOT)}: chat {len(chat)}, turns {len(turns)}, agent_memories {len(mems)}, "
          f"agents {len(agents)}; {OUT_ART.relative_to(ROOT)}: {len(art)} events")


if __name__ == "__main__":
    main()
