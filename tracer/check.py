"""Belief Tracer checker: validates built episode data against tracer/SPEC.md and exits non-zero on
failure. It reads JSON only (the episode data and its spec), never DuckDB, so it runs anywhere.

Usage:
  uv run python -m tracer.check [<slug> ...]   default: every tracer/out/episodes/*.json that has a spec

Checks: required fields and types; t values (epoch ms) inside the episode span; ids unique per
channel; every mark's author has a row; link ends and step keys exist; every step focus clause
lights at least one mark (SPEC Steps semantics plus the viewer note), with the count each step
lights; focus values that name nothing; a step key its own focus dims; no unfilled {placeholder} in
figures, title, headline or lede; stats recomputed from the data where the data allows it; day
numbers, panels and correction time against the spec; kinds against labels and the correction time;
link rooms; no credential-like string in any text field.
"""

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TRACER = Path(__file__).resolve().parent
OUT = TRACER / "out" / "episodes"

CHAT_KINDS = {"belief", "attributed", "hint", "fix", "other"}
MEM_STATES = {"claim", "attributed", "fix", "none"}
FILE_KINDS = {"belief", "fix"}
STANCES = {"adopts", "attributes", "refutes", "unclear", None}
TYPE_ALIAS = {"chat": "chat", "mem": "mem", "memory": "mem", "file": "file", "files": "file", "band": "band"}
FOCUS_FIELDS = {"type", "kind", "stance", "from", "to", "agents", "groups", "panel", "text", "linked", "op"}
STAT_KEYS = ["claim_chat_agents", "claim_mem_agents", "claim_mem_minutes", "memory_only", "attributed_only",
             "group_reach", "fix_mem_agents", "fix_first_minute", "linger_agents", "crossroom_links",
             "first_claim", "first_fix"]
PLACEHOLDER = re.compile(r"\{[A-Za-z_][\w.-]*\}")
LOW, HIGH = 1735689600000, 1830297600000  # 2025-01-01 .. 2028-01-01: anything else is not epoch ms
DAY1 = date(2025, 4, 2)  # AI Village Day 1, on the display-time-zone date

# The strongest redaction pattern (SECRET in trace.py, copied so this file needs no DuckDB; its first
# eight parts are label.py's), plus generic shapes a missed credential could take.
SECRET = re.compile(
    r"\b(?:[a-z0-9]+_)?(?:sk|pk|ghp|gho|ghs|github_pat|glpat|xox[abpr])[-_][A-Za-z0-9_\-]{8,}|"
    r"\bBearer\s+[A-Za-z0-9._\-]{12,}|\beyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}|"
    r"[A-Za-z0-9+/]{20,}={1,2}|"
    r"(?i:(?:api[ _-]?key|access[ _-]?token|password|secret|private[ _-]?key)\s*[:=]\s*`?)[^\s`]{6,}|"
    r"\b[a-z]{2,12}_(?=(?:[A-Za-z0-9_\-]*?[A-Z]){3})(?=(?:[A-Za-z0-9_\-]*?\d){3})[A-Za-z0-9_\-]{20,}|"
    r"\b[a-z]{2,12}_[0-9a-f]{32,}\b|"
    r"(?i:(?:auth|session|refresh)[ _-]?token|credentials?)\s*[:=]\s*`?[^\s`]{6,}|"
    r"\bGOCSPX-[A-Za-z0-9_\-]{10,}|\bAIza[0-9A-Za-z_\-]{30,}|\b(?:AKIA|ASIA)[0-9A-Z]{16}\b|"
    r"\bya29\.[A-Za-z0-9_\-]{20,}|\b1//0[A-Za-z0-9_\-]{20,}|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----(?:[A-Za-z0-9+/=\s.]|\\[rn])*(?:-----END [A-Z ]*PRIVATE KEY-----)?"
)
GENERIC = re.compile(
    r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{16,}|\b(?:ghp|gho|ghs|ghu|ghr)_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}|"
    r"\bhf_[A-Za-z0-9]{20,}|\b(?:AKIA|ASIA)[0-9A-Z]{16}\b|\bxox[abprs]-[A-Za-z0-9-]{10,}|"
    r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}|"
    r"(?i:\b(?:api[_ -]?key|key|token|secret|password|passwd|auth|bearer|credential)s?)[\"'`]?\s*[:=]?\s*[\"'`]?[0-9a-fA-F]{32,}\b|"
    r"PRIVATE KEY-----(?:\s|\\[rn])*[A-Za-z0-9+/]{16,}"
)


def utc_ms(s):
    """A spec time ("YYYY-MM-DD HH:MM:SS" UTC, a date, or epoch ms) -> epoch ms, as the viewer reads it."""
    if isinstance(s, (int, float)) and not isinstance(s, bool):
        return int(s)
    s = str(s).strip()
    if re.fullmatch(r"\d{4}-\d\d-\d\d", s):
        s += " 00:00:00"
    return int(datetime.fromisoformat(s.replace("Z", "")).replace(tzinfo=timezone.utc).timestamp() * 1000)


def utc(t):
    return datetime.fromtimestamp(t / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class Report:
    def __init__(self, slug):
        self.slug, self.fails, self.infos = slug, [], []

    def fail(self, msg):
        self.fails.append(msg)

    def info(self, msg):
        self.infos.append(msg)


# Shape ---------------------------------------------------------------------------------------------

def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def opt(kind):
    return lambda v: v is None or kind(v)


S = lambda v: isinstance(v, str)
B = lambda v: isinstance(v, bool)
L = lambda v: isinstance(v, list)
D = lambda v: isinstance(v, dict)

TOP = {"slug": S, "title": S, "headline": S, "lede": S, "tzOffsetHours": is_num, "claimLabel": opt(S),
       "correctionLabel": opt(S), "panels": L, "gaps": L, "correctionMs": opt(is_int), "groups": L, "rows": L,
       "chat": L, "mem": L, "files": L, "links": L, "annotations": L, "moves": L, "stats": D, "figures": L,
       "steps": L, "notes": D, "labelStats": opt(D)}
ITEM = {
    "panels": {"id": S, "label": S, "startMs": is_int, "endMs": is_int, "weight": is_num, "showOther": B, "day": is_int},
    "gaps": {"after": S, "label": S},
    "groups": {"key": S, "label": S, "note": S},
    "rows": {"name": S, "group": S, "human": B, "silent": B, "note": S},
    "chat": {"t": is_int, "a": S, "room": S, "id": S, "kind": lambda v: v in CHAT_KINDS, "stance": lambda v: v in STANCES,
             "check": lambda v: v in STANCES, "text": S},
    "mem": {"t": is_int, "a": S, "id": S, "state": lambda v: v in MEM_STATES, "stance": lambda v: v in STANCES,
            "check": lambda v: v in STANCES, "text": S, "chars": lambda v: is_int(v) and v >= 0},
    "files": {"t": is_int, "a": S, "id": S, "kind": lambda v: v in FILE_KINDS, "op": lambda v: v in ("write", "read"),
              "artifact": opt(S), "text": S},
    "links": {"from": lambda v: L(v) and len(v) == 2, "to": lambda v: L(v) and len(v) == 2, "label": S, "auto": B,
              "rooms": lambda v: L(v) and len(v) == 2 and all(x is None or S(x) for x in v)},
    "annotations": {"t": is_int, "label": S, "anchor": S},
    "moves": {"agent": S, "t": is_int, "toGroup": S, "label": S},
    "figures": {"value": S, "label": S},
}
OPTIONAL = {"chat": {"reason": S}, "mem": {"reason": S}, "panels": {"endDay": is_int}}
PATTERN_KEYS = {"claim": ("chat", "mem", "files"), "correction": ("chat", "strong", "mem", "files")}


def check_shape(d, r):
    ok = True
    for k, test in TOP.items():
        if k not in d:
            r.fail(f"missing top-level field {k!r}")
            ok = False
        elif not test(d[k]):
            r.fail(f"top-level {k!r} has the wrong type: {type(d[k]).__name__}")
            ok = False
    if not ok:
        return False
    for coll, fields in ITEM.items():
        bad = {}  # field -> [count, first index]
        for i, x in enumerate(d[coll]):
            if not D(x):
                bad.setdefault("(not an object)", [0, i])[0] += 1
                continue
            for f, test in fields.items():
                if f not in x or not test(x[f]):
                    bad.setdefault(f, [0, i])[0] += 1
            for f, test in OPTIONAL.get(coll, {}).items():
                if f in x and not test(x[f]):
                    bad.setdefault(f, [0, i])[0] += 1
        for f, (n, i) in bad.items():
            r.fail(f"{coll}: field {f!r} missing or invalid in {n} item(s), first at index {i}: {str(d[coll][i])[:160]}")
    if not d["panels"]:
        r.fail("panels is empty")
    check_zone_and_patterns(d, r)
    for k in ("how", "method", "limits"):
        if not L(d["notes"].get(k)):
            r.fail(f"notes.{k} is not a list")
    for i, st in enumerate(d["steps"]):
        if not D(st):
            r.fail(f"steps[{i}] is not an object")
            continue
        for k, test in (("time", S), ("title", S), ("body", S), ("links", B), ("moves", B), ("focus", lambda v: D(v) or L(v))):
            if k in st and st[k] is not None and not test(st[k]):
                r.fail(f"steps[{i}].{k} has the wrong type: {type(st[k]).__name__}")
    if d["labelStats"] is not None:
        ls = d["labelStats"]
        for k, test in (("items", is_int), ("labelled", is_int), ("agreement", opt(is_num)), ("checked", opt(is_int)),
                        ("checkSample", opt(is_int))):
            if not test(ls.get(k)):
                r.fail(f"labelStats.{k} missing or invalid: {ls.get(k)!r}")
    for k in STAT_KEYS:
        if k not in d["stats"]:
            r.fail(f"stats: missing {k!r}")
    return not r.fails


def check_zone_and_patterns(d, r):
    """Optional fields: timeZone (an IANA zone name or null) and patterns (the spec's regexes for the
    viewer's highlights; each must compile in Python)."""
    z = d.get("timeZone")
    if z is not None:
        try:
            ZoneInfo(z)
        except (KeyError, ValueError, TypeError):
            r.fail(f"timeZone {z!r} is not a known zone")
    if "patterns" not in d:
        return
    pats = d["patterns"]
    if not D(pats):
        r.fail(f"patterns is not an object: {type(pats).__name__}")
        return
    for k in sorted(set(pats) - {"claim", "correction", "linger"}):
        r.fail(f"patterns: unknown key {k!r}")
    found = [("linger", pats.get("linger"))]
    for part, keys in PATTERN_KEYS.items():
        v = pats.get(part)
        if v is None:
            if part == "claim":
                r.fail("patterns.claim is missing")
            continue
        if not D(v):
            r.fail(f"patterns.{part} is not an object")
            continue
        for k in sorted(set(v) - set(keys)):
            r.fail(f"patterns.{part}: unknown key {k!r}")
        found += [(f"{part}.{k}", v.get(k)) for k in keys]
    for where, p in found:
        if p is None:
            continue
        if not S(p):
            r.fail(f"patterns.{where} is not a string")
            continue
        try:
            re.compile(p)
        except re.error as e:
            r.fail(f"patterns.{where} does not compile: {e}")


# Structure -----------------------------------------------------------------------------------------

def check_structure(d, spec, r):
    panels = d["panels"]
    for a, b in zip(panels, panels[1:]):
        if a["startMs"] > b["startMs"]:
            r.fail(f"panels out of time order: {a['id']} then {b['id']}")
    for p in panels:
        if p["endMs"] <= p["startMs"]:
            r.fail(f"panel {p['id']}: endMs is not after startMs")
    if len({p["id"] for p in panels}) != len(panels):
        r.fail("panel ids are not unique")
    if [g["after"] for g in d["gaps"]] != [p["id"] for p in panels[:-1]]:
        r.fail(f"gaps: 'after' ids {[g['after'] for g in d['gaps']]} do not follow the panels {[p['id'] for p in panels]}")

    keys = [g["key"] for g in d["groups"]]
    if len(set(keys)) != len(keys):
        r.fail("group keys are not unique")
    names = [x["name"] for x in d["rows"]]
    if len(set(names)) != len(names):
        r.fail(f"row names are not unique: {sorted(n for n in set(names) if names.count(n) > 1)}")
    for x in d["rows"]:
        if x["group"] not in keys:
            r.fail(f"row {x['name']!r}: group {x['group']!r} is not in groups")
    for g in keys:
        if not any(x["group"] == g for x in d["rows"]):
            r.fail(f"group {g!r} has no rows")

    # Times: chat and files inside a panel; memory from memory_lookback to the last panel's end.
    first, last = panels[0]["startMs"], panels[-1]["endMs"]
    # Without the spec, memory_lookback is unknown: memory is only checked against the end.
    lookback = utc_ms(spec.get("memory_lookback") or spec["panels"][0]["start"]) if spec else LOW
    inside = lambda t: any(p["startMs"] <= t <= p["endMs"] for p in panels)
    for coll in ("chat", "files"):
        out = [x for x in d[coll] if not inside(x["t"])]
        if out:
            r.fail(f"{coll}: {len(out)} item(s) outside every panel, first {out[0]['id']} at {utc(out[0]['t'])}")
    out = [x for x in d["mem"] if not lookback <= x["t"] <= last]
    if out:
        r.fail(f"mem: {len(out)} snapshot(s) outside {utc(lookback)} .. {utc(last)}, first {out[0]['id']}")
    for coll in ("annotations", "moves"):
        out = [x for x in d[coll] if not min(lookback, first) <= x["t"] <= last]
        if out:
            r.fail(f"{coll}: {len(out)} item(s) outside the episode span, first at {utc(out[0]['t'])}")
    ts = [x["t"] for c in ("chat", "mem", "files", "annotations", "moves") for x in d[c]] + \
         [p[k] for p in panels for k in ("startMs", "endMs")] + ([d["correctionMs"]] if d["correctionMs"] else [])
    bad = [t for t in ts if not LOW <= t <= HIGH]
    if bad:
        r.fail(f"{len(bad)} time value(s) are not epoch milliseconds in 2025-2027, e.g. {bad[0]}")
    if d["correctionMs"] is not None and not first <= d["correctionMs"] <= last:
        r.fail(f"correctionMs {utc(d['correctionMs'])} is outside the panels")

    # Ids unique per channel; every mark has a row (the viewer would invent one otherwise).
    for coll in ("chat", "mem", "files"):
        ids = [x["id"] for x in d[coll]]
        if len(set(ids)) != len(ids):
            r.fail(f"{coll}: {len(ids) - len(set(ids))} duplicate id(s)")
        orphans = sorted({x["a"] for x in d[coll]} - set(names))
        if orphans:
            r.fail(f"{coll}: marks by authors with no row: {orphans}")
    for m in d["moves"]:
        if m["agent"] not in names:
            r.fail(f"moves: {m['agent']!r} has no row")
        if m["toGroup"] not in keys:
            r.fail(f"moves: group {m['toGroup']!r} is not in groups")

    # Link ends and step keys name full ids in the named channel.
    ids = {c: {x["id"] for x in d[c]} for c in ("chat", "mem", "files")}
    for i, ln in enumerate(d["links"]):
        for end in ("from", "to"):
            typ, id_ = ln[end]
            if typ not in ids:
                r.fail(f"links[{i}].{end}: unknown channel {typ!r}")
            elif id_ not in ids[typ]:
                r.fail(f"links[{i}].{end}: {typ} id {id_!r} is not in the data")
    for i, st in enumerate(d["steps"]):
        k = st.get("key")
        if k is not None and not (L(k) and len(k) == 2 and k[0] in ids):
            r.fail(f"steps[{i}] key {k!r} is not [chat|mem|files, id]")
        elif k is not None and k[1] not in ids[k[0]]:
            r.fail(f"steps[{i}] key {k[0]} id {k[1]!r} is not in the data")
        if st.get("range") is not None:
            try:
                a, b = (utc_ms(x) for x in st["range"])
                if b < a:
                    r.fail(f"steps[{i}] range ends before it starts")
            except (TypeError, ValueError):
                r.fail(f"steps[{i}] range {st['range']!r} is not two UTC times")

    seen = set()
    for i, ln in enumerate(d["links"]):
        k = (tuple(ln["from"]), tuple(ln["to"]))
        if k in seen:
            r.fail(f"links[{i}] repeats an earlier link {ln['from']} -> {ln['to']}")
        seen.add(k)
    for a in d["annotations"]:
        if a["anchor"] not in ("start", "middle", "end"):
            r.fail(f"annotation {a['label']!r}: anchor {a['anchor']!r} is not start, middle or end")
    ls = d["labelStats"]
    if ls and is_int(ls.get("items")) and is_int(ls.get("labelled")) and ls["labelled"] > ls["items"]:
        r.fail(f"labelStats: labelled {ls['labelled']} is more than items {ls['items']}")

    for i, f in enumerate(d["figures"]):
        for k in ("value", "label"):
            if PLACEHOLDER.search(f[k]):
                r.fail(f"figures[{i}].{k} has an unfilled placeholder: {f[k]!r}")


# Focus (the viewer's model: marks, memory bands, clause matching, lighting) -------------------------

def model(d):
    panels = d["panels"]
    group = {x["name"]: x["group"] for x in d["rows"]}

    def panel_of(t):
        for p in panels:
            if p["startMs"] <= t <= p["endMs"]:
                return p["id"]
        return "gap" if panels[0]["endMs"] < t < panels[-1]["startMs"] else None

    marks = []
    for x in d["chat"]:
        marks.append({"type": "chat", "t": x["t"], "a": x["a"], "kind": x["kind"], "stance": x["stance"], "id": x["id"],
                      "text": x["text"]})
    for x in d["mem"]:
        marks.append({"type": "mem", "t": x["t"], "a": x["a"], "kind": x["state"], "stance": x["stance"], "id": x["id"],
                      "text": x["text"]})
    for x in d["files"]:
        marks.append({"type": "file", "t": x["t"], "a": x["a"], "kind": "fix" if x["kind"] == "fix" else "belief",
                      "op": "write" if x["op"] == "write" else "read", "stance": None, "id": x["id"], "text": x["text"]})
    for m in marks:
        m["group"], m["panel"], m["linked"] = group.get(m["a"], "_other"), panel_of(m["t"]), False
    by_key = {(m["type"], m["id"]): i for i, m in enumerate(marks)}
    for ln in d["links"]:
        ends = [by_key.get((TYPE_ALIAS.get(ln[e][0], ln[e][0]), ln[e][1])) for e in ("from", "to")]
        if None not in ends:
            for i in ends:
                marks[i]["linked"] = True

    # Memory bands: the state carried between snapshots, per panel, plus each gap between panels.
    bands, mem_by = [], {}
    for i, m in enumerate(marks):
        if m["type"] == "mem":
            mem_by.setdefault(m["a"], []).append(i)

    def band(i, t, t1, panel, start):
        m = marks[i]
        bands.append({"type": "band", "a": m["a"], "group": m["group"], "kind": m["kind"], "stance": m["stance"],
                      "text": m["text"], "linked": m["linked"] and start, "t": t, "t1": t1, "panel": panel, "src": i,
                      "start": start})

    for lst in mem_by.values():
        lst.sort(key=lambda i: marks[i]["t"])
        for pi, p in enumerate(panels):
            prev, inside = None, []
            for i in lst:
                t = marks[i]["t"]
                if t < p["startMs"]:
                    prev = i
                elif t <= p["endMs"]:
                    inside.append(i)
            pts = ([(prev, p["startMs"], False)] if prev is not None else []) + [(i, marks[i]["t"], True) for i in inside]
            for k, (i, t, start) in enumerate(pts):
                t1 = pts[k + 1][1] if k + 1 < len(pts) else p["endMs"]
                if t1 > t:
                    band(i, t, t1, p["id"], start)
            if pi + 1 < len(panels):
                nx = panels[pi + 1]
                last = None
                for i in lst:
                    if marks[i]["t"] < nx["startMs"]:
                        last = i
                if last is not None:
                    band(last, p["endMs"], nx["startMs"], "gap", False)
    return marks, bands


def compile_clause(c, where, r):
    if not D(c):
        r.fail(f"{where}: a focus clause must be an object, got {c!r}")
        return None
    unknown = sorted(set(c) - FOCUS_FIELDS)
    if unknown:
        r.fail(f"{where}: unknown focus field(s) {unknown} (the viewer ignores them, so the clause matches more)")
    o = {}
    for k in ("type", "kind", "stance", "agents", "groups", "panel", "op"):
        if c.get(k) is not None:
            vals = c[k] if L(c[k]) else [c[k]]
            o[k] = {TYPE_ALIAS.get(v, v) for v in vals} if k == "type" else set(vals)
    for k in ("from", "to"):
        if c.get(k) is not None:
            try:
                o[k] = utc_ms(c[k])
            except (TypeError, ValueError):
                r.fail(f"{where}: {k} {c[k]!r} is not a UTC time")
                return None
    if c.get("text") is not None:
        try:
            o["text"] = re.compile(re.sub(r"^\(\?i\)", "", str(c["text"])), re.I)
        except re.error as e:
            r.fail(f"{where}: text regex {c['text']!r} does not compile ({e}); the viewer would match nothing")
            o["bad"] = True
    if c.get("linked") is not None:
        o["linked"] = bool(c["linked"])
    return o


def match(c, m):
    if c.get("bad"):
        return False
    for k, f in (("type", "type"), ("kind", "kind"), ("stance", "stance"), ("agents", "a"), ("groups", "group"),
                 ("panel", "panel"), ("op", "op")):
        if k in c and m.get(f) not in c[k]:
            return False
    if "from" in c or "to" in c:
        lo, hi = c.get("from", float("-inf")), c.get("to", float("inf"))
        if m["type"] == "band":
            if not (m["t"] <= hi and m["t1"] > lo):
                return False
        elif m["t"] < lo or m["t"] > hi:
            return False
    if "text" in c and not c["text"].search(m["text"] or ""):
        return False
    if "linked" in c and bool(m["linked"]) != c["linked"]:
        return False
    return True


def check_steps(d, r):
    marks, bands = model(d)
    # Values a clause may name; any other value matches nothing, so it is most likely a typo that
    # leaves the clause lighting less than its author meant.
    known = {"type": set(TYPE_ALIAS.values()), "kind": CHAT_KINDS | MEM_STATES | FILE_KINDS,
             "stance": STANCES - {None}, "op": {"write", "read"}, "panel": {p["id"] for p in d["panels"]} | {"gap"},
             "groups": {g["key"] for g in d["groups"]} | {"_other"}, "agents": {x["name"] for x in d["rows"]}}
    for i, st in enumerate(d["steps"]):
        name = f"steps[{i}] ({st.get('title', '')})"
        f = st.get("focus")
        if not f:
            r.info(f"{name}: no focus (shows everything)")
            continue
        raw = f if L(f) else f.get("any") if L(f.get("any")) else [f]
        clauses = [compile_clause(c, f"{name} clause {j + 1}", r) for j, c in enumerate(raw)]
        if any(c is None for c in clauses):
            continue
        for j, c in enumerate(clauses):
            for k, ok in known.items():
                bad = sorted(map(str, c.get(k, set()) - ok))
                if bad:
                    r.fail(f"{name} clause {j + 1}: {k} {bad} names nothing in this episode")
        direct = [any(match(c, m) for c in clauses) for m in marks]
        on, bon = list(direct), [False] * len(bands)
        for j, b in enumerate(bands):
            if any(match(c, b) for c in clauses):
                bon[j] = on[b["src"]] = True
            elif b["start"] and direct[b["src"]]:
                bon[j] = True
        counts = []
        for j, c in enumerate(clauses):
            n = sum(match(c, m) for m in marks) + sum(match(c, b) for b in bands)
            counts.append(n)
            if n == 0:
                r.fail(f"{name} clause {j + 1} lights nothing: {json.dumps(raw[j], ensure_ascii=False)}")
        r.info(f"{name}: lights {sum(on)} marks and {sum(bon)} bands (per clause: {', '.join(map(str, counts))})")
        k = st.get("key")
        if L(k) and len(k) == 2:
            i = next((i for i, m in enumerate(marks) if m["type"] == TYPE_ALIAS.get(k[0], k[0]) and m["id"] == k[1]), None)
            if i is not None and not on[i]:
                r.fail(f"{name}: its key evidence ({k[0]} {k[1][:8]}) is dimmed by its own focus")


# Stats ---------------------------------------------------------------------------------------------

def recompute(d):
    """The stats the data can show, recomputed from the marks (memory is compacted, but keeps every
    state change and each agent's first snapshot at or after the correction)."""
    human = {x["name"] for x in d["rows"] if x["human"]}
    corr = d["correctionMs"]
    before = lambda t: corr is None or t < corr
    chat = [x for x in d["chat"] if x["a"] not in human]
    mem = [x for x in d["mem"] if x["a"] not in human]
    files = [x for x in d["files"] if x["a"] not in human]
    claim_first = {}
    for x in sorted(mem, key=lambda x: x["t"]):
        if x["state"] == "claim" and before(x["t"]):
            claim_first.setdefault(x["a"], x["t"])
    ever_claim = {x["a"] for x in mem if x["state"] == "claim"}
    out = {
        "claim_chat_agents": len({x["a"] for x in chat if x["kind"] == "belief" and before(x["t"])}),
        "claim_mem_agents": len(claim_first),
        "claim_mem_minutes": round((max(claim_first.values()) - min(claim_first.values())) / 60000) if claim_first else 0,
        "fix_mem_agents": len({x["a"] for x in mem if x["state"] == "fix"}),
        "attributed_only": sorted({x["a"] for x in mem if x["state"] == "attributed"} - ever_claim),
    }
    if corr is None:
        out["fix_first_minute"], out["linger_agents"] = 0, []
    else:
        corrector = d["stats"].get("corrector")
        out["fix_first_minute"] = len({x["a"] for x in chat if x["kind"] == "fix" and x["a"] != corrector
                                       and corr <= x["t"] and x["t"] // 1000 * 1000 <= corr + 60000})
        out["linger_agents"] = sorted({x["a"] for x in chat if x["kind"] == "belief" and x["t"] >= corr} |
                                      {x["a"] for x in mem if x["state"] == "claim" and x["t"] >= corr})
    out["crossroom_links"] = sum(1 for ln in d["links"] if None not in ln["rooms"] and ln["rooms"][0] != ln["rooms"][1])

    def first(kinds):
        ms = [("chat", x, x["kind"]) for x in chat] + [("mem", x, x["state"]) for x in mem] + \
             [("files", x, x["kind"]) for x in files]
        ms = [(x["t"], typ, x) for typ, x, k in ms if k in kinds]
        if not ms:
            return None
        t, typ, x = min(ms, key=lambda m: (m[0], m[1]))
        return {"t": t, "a": x["a"], "type": typ, "id": x["id"]}

    out["first_claim"], out["first_fix"] = first({"belief", "claim"}), first({"fix"})
    reached = {x["a"] for x in chat if x["kind"] == "belief"} | ever_claim
    reach = {}
    for g in d["groups"]:
        members = [x["name"] for x in d["rows"] if x["group"] == g["key"] and not x["human"]]
        if members:
            reach[g["key"]] = {"reached": sum(n in reached for n in members), "total": len(members)}
    out["group_reach"] = reach
    return out


def check_stats(d, r):
    for k, v in recompute(d).items():
        if d["stats"].get(k) != v:
            r.fail(f"stats.{k}: data says {json.dumps(v, ensure_ascii=False)}, engine says "
                   f"{json.dumps(d['stats'].get(k), ensure_ascii=False)}")
    r.info("stats: " + ", ".join(f"{k} {json.dumps(d['stats'][k], ensure_ascii=False)}"
                                 for k in ("claim_chat_agents", "claim_mem_agents", "fix_mem_agents", "fix_first_minute",
                                           "crossroom_links") if k in d["stats"]) +
           f", linger_agents {len(d['stats'].get('linger_agents') or [])}")


# Meaning: what the data says must agree with the rules that made it -------------------------------

def village_day(t, tz):
    """Day number at epoch ms t; tz is a ZoneInfo (daylight saving included) or a fixed offset in hours."""
    if isinstance(tz, ZoneInfo):
        return (datetime.fromtimestamp(t / 1000, tz).date() - DAY1).days + 1
    return ((datetime.fromtimestamp(t / 1000, timezone.utc) + timedelta(hours=tz)).date() - DAY1).days + 1


def check_meaning(d, spec, r):
    """Rules the engine follows that the data alone can confirm: day numbers, the spec's panels and
    correction time, kinds against labels (red needs an adopts), kinds against the correction time,
    link rooms, the corrector, and the parts of memory_only the data can show."""
    corr = d["correctionMs"]
    try:
        tz = ZoneInfo(d["timeZone"]) if d.get("timeZone") else d["tzOffsetHours"]
    except (KeyError, ValueError, TypeError):
        tz = d["tzOffsetHours"]  # check_shape reported the zone
    where = tz.key if isinstance(tz, ZoneInfo) else f"UTC{tz:+g}"
    for p in d["panels"]:
        if p["day"] != village_day(p["startMs"], tz):
            r.fail(f"panel {p['id']}: day {p['day']}, but {utc(p['startMs'])} UTC is Day {village_day(p['startMs'], tz)} "
                   f"in {where}")
        # endDay: the day the panel ends on; an end at midnight belongs to the day before.
        if "endDay" in p and p["endDay"] != village_day(p["endMs"] - 1, tz):
            r.fail(f"panel {p['id']}: endDay {p['endDay']}, but it ends on Day {village_day(p['endMs'] - 1, tz)} in {where}")
    for k in ("title", "headline", "lede"):
        if PLACEHOLDER.search(d[k]):
            r.fail(f"{k} has an unfilled placeholder: {d[k][:120]!r}")
    probe = corr
    if spec:
        sp = [(p["id"], utc_ms(p["start"]), utc_ms(p["end"])) for p in spec.get("panels", [])]
        if sp != [(p["id"], p["startMs"], p["endMs"]) for p in d["panels"]]:
            r.fail("panels differ from the spec's panels (ids, start or end)")
        c = spec.get("correction") or {}
        want = utc_ms(c["at"]) if c.get("at") else None
        if want != corr:
            r.fail(f"correctionMs {corr} differs from the spec's correction.at ({want})")
        if c.get("probe_from"):
            probe = utc_ms(c["probe_from"])

    # Kinds against labels: red needs a labeller's adopts (the check pass's when the main pass has
    # none); attributed comes only from an attributes label.
    eff = lambda x: x["stance"] or x["check"]
    for coll, field, red in (("chat", "kind", "belief"), ("mem", "state", "claim")):
        bad = [x for x in d[coll] if x[field] == red and eff(x) not in ("adopts", None)]
        if bad:
            r.fail(f"{coll}: {len(bad)} {red} mark(s) whose label is not adopts, first {bad[0]['id']} ({eff(bad[0])})")
        bad = [x for x in d[coll] if x[field] == "attributed" and eff(x) != "attributes"]
        if bad:
            r.fail(f"{coll}: {len(bad)} attributed mark(s) without an attributes label, first {bad[0]['id']} ({eff(bad[0])})")
    # Kinds against the correction time.
    bad = [x for x in d["chat"] if x["kind"] == "fix" and (corr is None or x["t"] < corr)]
    if bad:
        r.fail(f"chat: {len(bad)} fix message(s) before the correction, first {bad[0]['id']}")
    bad = [x for x in d["mem"] if x["state"] == "fix" and (corr is None or x["t"] < corr) and eff(x) != "refutes"]
    if bad:
        r.fail(f"mem: {len(bad)} fix snapshot(s) before the correction without a refutes label, first {bad[0]['id']}")
    # Without the spec the probe window is unknown, so only "no correction, no fix" is checked.
    bad = [x for x in d["files"] if x["kind"] == "fix" and (corr is None or spec and x["t"] < probe)]
    if bad:
        r.fail(f"files: {len(bad)} fix command(s) before the correction's probe window, first {bad[0]['id']}")

    # Link rooms: a chat end's room is the message's room; an automatic hand-off between two agents'
    # file commands crosses a room wall by construction.
    by = {(c, x["id"]): x for c in ("chat", "mem", "files") for x in d[c]}
    for i, ln in enumerate(d["links"]):
        ends = [by.get(tuple(ln[e])) for e in ("from", "to")]
        if None in ends:
            continue
        for e, x, room in zip(("from", "to"), ends, ln["rooms"]):
            if ln[e][0] == "chat" and room != x["room"]:
                r.fail(f"links[{i}].{e}: room {room!r}, but the message is in #{x['room']}")
        if ln["auto"] and ln["from"][0] == ln["to"][0] == "files" and ends[0]["a"] != ends[1]["a"] and \
                (None in ln["rooms"] or ln["rooms"][0] == ln["rooms"][1]):
            r.fail(f"links[{i}]: automatic hand-off between {ends[0]['a']} and {ends[1]['a']} with rooms {ln['rooms']}")
        if ln["from"] == ln["to"]:
            r.fail(f"links[{i}]: both ends are {ln['from']}")

    rows = {x["name"]: x for x in d["rows"]}
    # pin_first: the rows it names (agents or human rows) that the episode shows in that group come
    # first in the group, in its order.
    for g, names in ((spec or {}).get("pin_first") or {}).items():
        if not L(names):
            r.fail(f"pin_first.{g}: {names!r} is not a list of row names")
            continue
        order = [x["name"] for x in d["rows"] if x["group"] == g]
        want = list(dict.fromkeys(n for n in names if n in order))
        if order[:len(want)] != want:
            r.fail(f"pin_first.{g}: rows {want} should open the group, but it starts {order[:len(want)]}")
    c = d["stats"].get("corrector")
    if c is not None and (c not in rows or rows[c]["human"]):
        r.fail(f"stats.corrector {c!r} is not an agent row")

    # memory_only: claim in memory before the correction, no chat message matching claim.chat
    # before it. Chat that matches claim.chat always stays in the data (tagged or not), so an agent
    # with no chat at all before the correction belongs in the list; one with a belief message before
    # the probe window, or a message whose text shows a claim.chat match, does not.
    human = {n for n, x in rows.items() if x["human"]}
    before = lambda t: corr is None or t < corr
    held = {x["a"] for x in d["mem"] if x["state"] == "claim" and before(x["t"]) and x["a"] not in human}
    spoke = {x["a"] for x in d["chat"] if before(x["t"])}
    said = {x["a"] for x in d["chat"] if x["kind"] == "belief" and (probe is None or x["t"] < probe)} if spec or \
        corr is None else set()  # without the spec a probe window may hide in the data
    if spec and spec.get("claim", {}).get("chat"):
        crx = re.compile(spec["claim"]["chat"], re.I)
        said |= {x["a"] for x in d["chat"] if before(x["t"]) and crx.search(x["text"].lower())}
    mo = set(d["stats"].get("memory_only") or [])
    for names, why in ((mo - held, "have no claim snapshot before the correction"),
                       ((held - spoke) - mo, "held the claim and posted nothing before the correction, but are missing"),
                       (mo & said, "said the claim in chat before the correction")):
        if names:
            r.fail(f"stats.memory_only: {sorted(names)} {why}")


# Credentials ---------------------------------------------------------------------------------------

def strings(v, path="$"):
    if isinstance(v, str):
        yield path, v
    elif isinstance(v, dict):
        for k, x in v.items():
            yield from strings(x, f"{path}.{k}")
    elif isinstance(v, list):
        for i, x in enumerate(v):
            yield from strings(x, f"{path}[{i}]")


def check_secrets(d, r):
    hits = []
    for path, s in strings(d):
        for pat in (SECRET, GENERIC):
            m = pat.search(s)
            if m:
                hits.append((path, m.group(0)))
                break
    for path, s in hits[:10]:
        # Show the shape, not the string.
        r.fail(f"credential-like string at {path}: {s[:4]}… ({len(s)} chars)")
    if len(hits) > 10:
        r.fail(f"… and {len(hits) - 10} more credential-like strings")


# Driver --------------------------------------------------------------------------------------------

def check_episode(path, spec):
    r = Report(path.stem)
    try:
        d = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        r.fail(f"cannot read {path}: {e}")
        return r
    if not D(d):
        r.fail("episode data is not a JSON object")
        return r
    if spec is None:
        r.info("no spec: memory times checked against the last panel's end only")
    if check_shape(d, r):
        check_structure(d, spec, r)
        check_steps(d, r)
        check_stats(d, r)
        check_meaning(d, spec, r)
    check_secrets(d, r)
    sizes = {c: len(d.get(c) or []) for c in ("rows", "chat", "mem", "files", "links", "steps")}
    r.info(f"{path.stat().st_size / 1e6:.1f} MB; " + ", ".join(f"{k} {v}" for k, v in sizes.items()))
    return r


def main():
    ap = argparse.ArgumentParser(description="Validate built Belief Tracer episode data against tracer/SPEC.md.")
    ap.add_argument("slugs", nargs="*", help="default: every tracer/out/episodes/<slug>.json that has a spec")
    ap.add_argument("-q", "--quiet", action="store_true", help="print failures only")
    ap.add_argument("--dir", type=Path, default=OUT, help="where the episode data is (default tracer/out/episodes)")
    args = ap.parse_args()
    specs = {p.stem for p in (TRACER / "episodes").glob("*.json")}
    slugs = args.slugs or sorted(p.stem for p in args.dir.glob("*.json") if p.stem in specs)
    if not slugs:
        sys.exit(f"no built episodes with specs in {args.dir}")
    failed = []
    for slug in slugs:
        path = args.dir / f"{slug}.json"
        sp = TRACER / "episodes" / f"{slug}.json"
        spec = json.loads(sp.read_text()) if sp.exists() else None
        if not path.exists():
            print(f"== {slug}  FAIL\n  no episode data at {path}")
            failed.append(slug)
            continue
        r = check_episode(path, spec)
        print(f"== {slug}  {'FAIL' if r.fails else 'ok'}")
        for msg in r.fails:
            print(f"  FAIL {msg}")
        if not args.quiet:
            for msg in r.infos:
                print(f"  {msg}")
        if r.fails:
            failed.append(slug)
    print(f"\n{len(slugs) - len(failed)} of {len(slugs)} episodes pass" + (f"; failed: {', '.join(failed)}" if failed else ""))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
