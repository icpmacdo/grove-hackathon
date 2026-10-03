"""Belief Tracer engine: an episode spec in, episode data out. The contract is tracer/SPEC.md.

Usage:
  uv run python -m tracer.trace temporal-bleed [<slug> ...]   writes tracer/out/episodes/<slug>.json
  uv run python -m tracer.trace --all --site                  every spec, plus the static site in tracer/out/site/

Generalizes build_temporal_bleed.py and keeps its logic: the classification order (probe window, a
strong fix beats a lingering claim), memory read from memory_lookback so state carries into each
panel, the file write heuristic, redaction, excerpts and row ordering. Classification is lexical and
deliberately simple; every mark keeps its source id and text so a reader can check it.

The parquet files behind the views are not sorted by time, so every query is a full scan. The engine
keeps them few and bounded: chat inside the panels, one memory scan from memory_lookback to the last
panel's end (text is fetched only for snapshots the spec's regexes match), and one or two turn scans
inside the panels. DuckDB (RE2) prefilters with the spec's regexes when it can parse them; Python's
re makes every final decision. Every text is redacted before it is excerpted (label.py's pattern);
DuckDB flags the few texts that can hold a credential, so Python only redacts those.

Check built episodes against the contract with: uv run python -m tracer.check
"""

import argparse
import copy
import json
import re
import sys
import time
from bisect import bisect_left, bisect_right
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

ROOT = Path(__file__).resolve().parent.parent
TRACER = ROOT / "tracer"
OUT = TRACER / "out"
DB = ROOT / "data" / "village.duckdb"
ARTIFACT_EVENTS = ROOT / "analysis" / "artifacts" / "out" / "artifact_events.parquet"
DAY1 = date(2025, 4, 2)
PACIFIC = ZoneInfo("America/Los_Angeles")
MARKER = "/*__TRACER_CONFIG__*/null"

# Group keys that are not rooms. Room names are lowercase words, so the underscore keeps them apart.
NOCHAT, OTHER_ROOMS, ALL_ROOMS = "_nochat", "_other", "_all"
GROUP_LABELS = {NOCHAT: "(no chat in window)", OTHER_ROOMS: "(other rooms)", ALL_ROOMS: "All rooms"}

# Auto links: a read counts within 90 minutes of a write; a reader's next mark within 45 minutes.
READ_WINDOW, UPTAKE_WINDOW, ROOM_MEMORY = 90 * 60000, 45 * 60000, 48 * 3600000
OUTPUT_CHARS = 20000  # command output read for evidence that a reader saw a write

# Credential-like strings: the redact() pattern of build_temporal_bleed.py plus the three token shapes
# label.py adds (<prefix>_<mixed-case body>, <prefix>_<32+ hex>, "Auth Token: ..."), which a memory
# credentials list in the dataset holds. Joined, the first eight parts are label.py's SECRET, character
# for character. The engine adds Google and AWS key shapes and private key blocks after them: one
# agent's memory holds a Google OAuth client secret (GOCSPX-...) in hundreds of snapshots.
SECRET_PARTS = [
    r"\b(?:[a-z0-9]+_)?(?:sk|pk|ghp|gho|ghs|github_pat|glpat|xox[abpr])[-_][A-Za-z0-9_\-]{8,}",
    r"\bBearer\s+[A-Za-z0-9._\-]{12,}",
    r"\beyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}",
    r"[A-Za-z0-9+/]{20,}={1,2}",
    r"(?i:(?:api[ _-]?key|access[ _-]?token|password|secret|private[ _-]?key)\s*[:=]\s*`?)[^\s`]{6,}",
    r"\b[a-z]{2,12}_(?=(?:[A-Za-z0-9_\-]*?[A-Z]){3})(?=(?:[A-Za-z0-9_\-]*?\d){3})[A-Za-z0-9_\-]{20,}",
    r"\b[a-z]{2,12}_[0-9a-f]{32,}\b",
    r"(?i:(?:auth|session|refresh)[ _-]?token|credentials?)\s*[:=]\s*`?[^\s`]{6,}",
    r"\bGOCSPX-[A-Za-z0-9_\-]{10,}",
    r"\bAIza[0-9A-Za-z_\-]{30,}",
    r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
    r"\bya29\.[A-Za-z0-9_\-]{20,}",
    r"\b1//0[A-Za-z0-9_\-]{20,}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----(?:[A-Za-z0-9+/=\s.]|\\[rn])*(?:-----END [A-Z ]*PRIVATE KEY-----)?",
]
SECRET = re.compile("|".join(SECRET_PARTS))
# A key block goes first, in a pass of its own: in "privateKey = '-----BEGIN ..." the password rule
# would take the start of the header and leave the key body behind.
PEM = re.compile(SECRET_PARTS[-1])
# For each part, a superset that DuckDB's RE2 can run: no lookaheads (the mixed-case body needs one
# capital, and one digit in or right after it), Python's Unicode \s and \d spelled out (RE2's are
# ASCII), [^\s`] widened to [^`]. RE2's ASCII \b only adds matches next to ASCII letters. A text where
# a part's superset finds nothing holds no match of that part, so SQL tells Python which parts can
# match (usually none) and redact_parts() runs only those, with the same result as redact().
_WS = r"[\t\n\x{0b}\f\r \x{1c}-\x{1f}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]"
SUSPECT_PARTS = [
    SECRET_PARTS[0],
    rf"\bBearer{_WS}+[A-Za-z0-9._\-]{{12,}}",
    SECRET_PARTS[2],
    SECRET_PARTS[3],
    rf"(?i:(?:api[ _-]?key|access[ _-]?token|password|secret|private[ _-]?key){_WS}*[:=]{_WS}*`?)[^`]{{6,}}",
    r"\b[a-z]{2,12}_[A-Za-z0-9_\-]*(?:[A-Z][A-Za-z0-9_\-]*\p{Nd}|[0-9][A-Za-z0-9_\-]*[A-Z])",
    SECRET_PARTS[6],
    rf"(?i:(?:auth|session|refresh)[ _-]?token|credentials?){_WS}*[:=]{_WS}*`?[^`]{{6,}}",
    *SECRET_PARTS[8:13],
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
]
SUSPECT = "|".join(SUSPECT_PARTS)
FILE_WRITE = re.compile(
    r"cat\s*(<<|>)|>>|\btee\b|git (commit|push)|codex exec|json\.dump|write_text|open\([^)]*['\"][wa]|"
    r"memory\.py log|\bmv\b|mkdir|gh repo create|git init\b|\b(?:gh|glab) (?:pr|mr) (?:create|merge)\b|\bgit merge\b"
)
# Regex fallback for artifact identity: GitHub org paths, and local clones under ~, /home/<user> or
# /tmp. A local directory name only counts when it names a known repo (when the artifact events
# file is present), because two agents' ~/notes are different folders.
REPO_URL = re.compile(r"ai-village-agents(?:/|\.github\.io/)([\w.-]+)", re.I)
REPO_DIR = re.compile(r"(?:~|/home/[\w-]+|/tmp)/([\w.-]+)")
NOT_REPO = re.compile(
    r"^\.|^(tmp|home|desktop|downloads|documents|bin|lib|src|docs|data|out|output|logs?|notes|memory|"
    r"scripts|work|repo|repos|projects?|test|tests)$|"
    r"\.(md|txt|json|jsonl|py|sh|log|html?|csv|js|ts|png|jpe?g|gif|svg|ya?ml|toml|pdf|out|err|tmp|bak|zip|gz)$",
    re.I,
)
# Heredoc bodies are file contents, not targets: a doc that links to a repo does not write to it.
HEREDOC = re.compile(r"(<<-?\s*(['\"]?)(\w+)\2[^\n]*\n).*?^\s*\3\s*$", re.S | re.M)
PLACEHOLDER = re.compile(r"\{([A-Za-z_]\w*(?:\.[\w-]+)*)\}")
# Red needs a labeller's "adopts": an unclear label draws neutral, so off-topic keyword matches stay grey.
LABEL_CHAT = {"adopts": "belief", "attributes": "attributed", "refutes": "hint", "unclear": "other"}
LABEL_MEM = {"adopts": "claim", "attributes": "attributed", "refutes": "fix", "unclear": "none"}
FAMILY = {"belief": {"belief", "claim"}, "fix": {"fix"}}
# A hand link's untagged file end takes the family of the link's other end.
HAND_KIND = {"belief": "belief", "claim": "belief", "attributed": "belief", "fix": "fix", "hint": "fix"}


def redact(text):
    return SECRET.sub("[REDACTED]", PEM.sub("[REDACTED]", text))


_PARTS = {}


def redact_parts(text, parts):
    """redact() for a text in which only SECRET's parts flagged in parts (from suspect_sql) can match.
    The other parts match nowhere in it, so leaving them out of the alternation changes nothing."""
    key = tuple(i for i, f in enumerate(parts or ()) if f)
    if not key:
        return text
    if len(SECRET_PARTS) - 1 in key:
        text = PEM.sub("[REDACTED]", text)
    if key not in _PARTS:
        _PARTS[key] = re.compile("|".join(SECRET_PARTS[i] for i in key))
    return _PARTS[key].sub("[REDACTED]", text)


def suspect_sql(expr):
    """SQL: per SECRET part, whether expr may hold a match of it (a list of booleans), or NULL when
    it can hold none. redact_parts() takes the list."""
    flags = ", ".join(f"regexp_matches({expr}, {lit(p)})" for p in SUSPECT_PARTS)
    return f"CASE WHEN regexp_matches({expr}, {lit(SUSPECT)}) THEN [{flags}] END"


def parse(ts):
    """UTC string or naive UTC datetime -> naive UTC datetime."""
    return ts if isinstance(ts, datetime) else datetime.fromisoformat(ts)


def ms(ts):
    return int(parse(ts).replace(tzinfo=timezone.utc).timestamp() * 1000)


def from_ms(t):
    return datetime.fromtimestamp(t / 1000, timezone.utc).replace(tzinfo=None)


def local(t, tz):
    """Wall time at epoch ms t: tz is a zone (ZoneInfo, daylight saving included) or a fixed offset in hours."""
    if isinstance(tz, ZoneInfo):
        return datetime.fromtimestamp(t / 1000, tz).replace(tzinfo=None)
    return from_ms(t) + timedelta(hours=tz)


def display_zone(spec):
    """The episode's display zone: the spec's "time_zone" (an IANA name), else Pacific time when
    tz_offset_hours is absent, -7 or -8. Another offset stays a fixed offset (None)."""
    if spec.get("time_zone"):
        try:
            return ZoneInfo(spec["time_zone"])
        except (KeyError, ValueError) as e:
            raise ValueError(f"time_zone {spec['time_zone']!r} is not a known zone") from e
    return PACIFIC if spec.get("tz_offset_hours", -7) in (-7, -8) else None


def village_day(t, tz):
    return (local(t, tz).date() - DAY1).days + 1


def lit(value):
    """A SQL string literal. Timestamps and regexes are inlined so DuckDB can fold them."""
    if isinstance(value, datetime):
        value = value.strftime("%Y-%m-%d %H:%M:%S.%f")
    return "'" + str(value).replace("'", "''") + "'"


def snippet(text, m, before=160, length=520):
    a = max(0, m.start() - before)
    s = text[a : a + length].strip()
    return redact(("…" if a > 0 else "") + s + ("…" if a + length < len(text) else ""))


def clip(text, n):
    text = text.strip()
    return redact(text if len(text) <= n else text[:n].rstrip() + "…")


def rx(pattern):
    """Spec regexes run on lowercased text, so re.I (slow on long text) is only needed when the
    pattern itself has a capital letter outside an escape like \\S."""
    if not pattern:
        return None
    return re.compile(pattern, re.I if re.search(r"[A-Z]", re.sub(r"\\.", "", pattern)) else 0)


def hit(r, text):
    return r.search(text) if r else None


def either(*patterns):
    return "|".join(f"(?:{p})" for p in patterns if p)


_PY_SETS = {"w": r"\pL\pN_", "d": r"\p{Nd}", "s": _WS[1:-1]}


def sql_re(pattern):
    """A spec regex for an RE2 prefilter that matches wherever Python's re would: \\w, \\d and \\s
    spelled out as Python's Unicode sets (RE2's are ASCII), \\b and \\B dropped. Python's re still
    makes every decision."""
    if not pattern:
        return pattern
    out, i, in_set = [], 0, False
    while i < len(pattern):
        c = pattern[i]
        if c == "\\" and i + 1 < len(pattern):
            e = pattern[i + 1]
            if e in _PY_SETS:
                out.append(_PY_SETS[e] if in_set else f"[{_PY_SETS[e]}]")
            elif not (e in "bB" and not in_set):
                out.append(c + e)
            i += 2
            continue
        if c == "[" and not in_set:
            # a ] first in the set (after an optional ^) is a literal
            j = i + 1 + (pattern[i + 1 : i + 2] == "^")
            j += pattern[j : j + 1] == "]"
            out.append(pattern[i:j])
            in_set, i = True, j
            continue
        if c == "]" and in_set:
            in_set = False
        out.append(c)
        i += 1
    return "".join(out)


def connect():
    con = duckdb.connect(str(DB), read_only=True)
    con.execute("SET memory_limit='1500MB'; SET threads=2; SET enable_progress_bar=false;")
    return con


def re2(con, pattern):
    """True when DuckDB's RE2 parses the pattern, so SQL can prefilter with it."""
    if not pattern:
        return False
    try:
        con.execute(f"SELECT regexp_matches('', {lit(pattern)}, 'i')").fetchone()
        return True
    except duckdb.Error:
        return False


def minutes(dt_ms):
    n = round(dt_ms / 60000)
    return "under a minute" if n < 1 else "1 minute" if n == 1 else f"{n} minutes"


# Specs -------------------------------------------------------------------------------------------

def spec_path(slug):
    return TRACER / "episodes" / f"{slug}.json"


def list_specs():
    """Curated episode slugs, by the optional spec field "order" (default 100), then slug."""
    specs = []
    for p in (TRACER / "episodes").glob("*.json"):
        try:
            order = json.loads(p.read_text()).get("order", 100)
        except (ValueError, AttributeError):
            order = 100
        specs.append((order, p.stem))
    return [slug for _, slug in sorted(specs)]


def load_spec(slug):
    p = spec_path(slug)
    if not p.exists():
        raise FileNotFoundError(f"no episode spec {p.relative_to(ROOT)} (have: {', '.join(list_specs())})")
    spec = json.loads(p.read_text())
    spec.setdefault("slug", slug)
    return spec


def pacific_offset(day):
    """Pacific UTC offset in hours on a date (at noon): -7 in summer time, -8 in winter."""
    noon = datetime.combine(day, datetime.min.time()).replace(hour=12, tzinfo=PACIFIC)
    return int(noon.utcoffset().total_seconds() // 3600)


def auto_panels(days, con=None, tz_offset_hours=None):
    """One panel per display-time-zone date, bounded by that day's first and last chat message
    rounded out to the hour. Weight follows duration; untagged chat is drawn for one or two days.
    Without tz_offset_hours each date is a Pacific date at that date's offset."""
    own = con is None
    con = con or connect()
    try:
        panels = []
        for d in sorted(set(days)):
            day = date.fromisoformat(d)
            tz = pacific_offset(day) if tz_offset_hours is None else tz_offset_hours
            start = datetime.combine(day, datetime.min.time()) - timedelta(hours=tz)
            first, last = con.execute(
                f"SELECT min(created_at), max(created_at) FROM chat "
                f"WHERE created_at >= {lit(start)} AND created_at < {lit(start + timedelta(days=1))}"
            ).fetchone()
            if first is None:
                continue
            a = first.replace(minute=0, second=0, microsecond=0)
            b = last.replace(minute=0, second=0, microsecond=0)
            if b < last:
                b += timedelta(hours=1)
            if b <= a:
                b = a + timedelta(hours=1)
            panels.append({"id": d, "label": f"{day:%a} {day.day} {day:%b}",
                           "start": a.strftime("%Y-%m-%d %H:%M:%S"), "end": b.strftime("%Y-%m-%d %H:%M:%S"),
                           "hours": (b - a).total_seconds() / 3600})
        if not panels:
            raise ValueError(f"no chat on any of these days: {', '.join(days)}")
        mean = sum(p["hours"] for p in panels) / len(panels)
        for p in panels:
            p["weight"] = round(p.pop("hours") / mean, 2)
            p["show_other"] = len(panels) <= 2
        return panels
    finally:
        if own:
            con.close()


def live_spec(claim, correction=None, days=(), con=None, tz_offset_hours=None):
    """A spec for a live trace: claim {"label", "pattern"}, optional correction {"label", "pattern",
    "at"}, and the chosen days. One pattern drives chat, memory and files. No steps; generic figures.
    tz_offset_hours defaults to the Pacific offset on the first panel's date (-8 in winter); either
    Pacific offset makes the display zone Pacific time, with daylight saving (display_zone)."""
    panels = auto_panels(days, con, tz_offset_hours)
    if tz_offset_hours is None:
        tz_offset_hours = pacific_offset(date.fromisoformat(panels[0]["id"]))
    p = claim["pattern"]
    spec = {
        "slug": None, "title": claim.get("label") or p, "headline": f"Tracing: {claim.get('label') or p}",
        "lede": "", "tz_offset_hours": tz_offset_hours,
        "claim": {"label": claim.get("label") or p, "chat": p, "memory": p, "files": p},
        "panels": panels, "memory_lookback": (parse(panels[0]["start"]) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
        "rooms": "auto", "auto_links": True, "labels": False,
        "figures": [
            {"value": "{claim_chat_agents}", "label": "agents said it in chat"},
            {"value": "{claim_mem_agents}", "label": "agents held it in memory"},
            {"value": "{memory_only.length}", "label": "held it in memory without saying it in chat"},
            {"value": "{crossroom_links}", "label": "file hand-offs between rooms"},
        ],
    }
    if correction and correction.get("pattern") and correction.get("at"):
        c = correction["pattern"]
        spec["correction"] = {"label": correction.get("label") or c, "at": correction["at"],
                              "chat": c, "strong": c, "memory": c, "files": c}
        spec["figures"][3] = {"value": "{fix_mem_agents}", "label": "agents' memories took up the correction"}
    return spec


# Engine ------------------------------------------------------------------------------------------

def build_episode(spec, con=None, info=None):
    """Episode spec (dict) -> episode data (dict), as tracer/SPEC.md describes. If given, info (a
    dict) receives build notes outside the contract: warnings, agents added with no chat, the
    corrector and the rooms shown."""
    own = con is None
    con = con or connect()
    try:
        ep = Episode(spec, con)
        data = ep.build()
        if info is not None:
            info.update(warnings=ep.warnings, addedNoChat=ep.added, corrector=ep.corrector, rooms=ep.rooms,
                        memMerged=ep.dropped_mem, timings=ep.timings, noRow=ep.hidden, filesNoRow=ep.dropped_files)
        return data
    finally:
        if own:
            con.close()


class Episode:
    def __init__(self, spec, con):
        self.spec, self.con = spec, con
        self.warnings = []
        self.tz = spec.get("tz_offset_hours", -7)
        # Display times, day numbers and gap labels follow the zone (daylight saving included);
        # tz_offset_hours is the fallback for an episode outside Pacific time.
        self.zone = display_zone(spec)
        self.disp = self.zone or self.tz
        self.aliases = spec.get("aliases", {})
        self.overrides = spec.get("agent_overrides", {})
        if not spec.get("panels"):
            raise ValueError("spec has no panels")
        self.panels = [dict(p, s=ms(p["start"]), e=ms(p["end"])) for p in spec["panels"]]
        if any(a["s"] > b["s"] for a, b in zip(self.panels, self.panels[1:])):
            raise ValueError("panels must be in time order")
        claim, corr = spec["claim"], spec.get("correction") or {}
        self.c_chat, self.c_mem, self.c_files = rx(claim.get("chat")), rx(claim.get("memory")), rx(claim.get("files"))
        self.claim_rooms = set(claim.get("rooms") or []) or None
        if corr and not corr.get("at"):
            raise ValueError("correction needs \"at\"")
        self.corr_ms = ms(corr["at"]) if corr else None
        self.probe_ms = ms(corr["probe_from"]) if corr.get("probe_from") else self.corr_ms
        self.x_chat, self.x_strong = rx(corr.get("chat")), rx(corr.get("strong"))
        self.x_mem, self.x_files = rx(corr.get("memory")), rx(corr.get("files"))
        self.corrector = corr.get("by")
        self.linger = rx(spec.get("linger"))
        self.order_rx = rx(spec.get("order_by"))
        self.human_rows = [(h["name"], rx(h["pattern"]), h.get("group", ALL_ROOMS)) for h in spec.get("human_rows", [])]
        self.lookback = parse(spec.get("memory_lookback") or spec["panels"][0]["start"])
        self.end = parse(spec["panels"][-1]["end"])
        self.label_ids = set()  # chat and memory items the labeller would see (claim regex matches)

    def warn(self, msg):
        self.warnings.append(msg)

    def alias(self, name):
        return self.aliases.get(name, name)

    def win(self, col="created_at", extra=None):
        """SQL for "inside any panel"; extra(p) may add a condition per panel."""
        out = []
        for p in self.panels:
            c = f"{col} BETWEEN {lit(parse(p['start']))} AND {lit(parse(p['end']))}"
            if extra and extra(p):
                c += " AND " + extra(p)
            out.append(f"({c})")
        return " OR ".join(out)

    def panel_at(self, t):
        return next((p for p in self.panels if p["s"] <= t <= p["e"]), None)

    # Chat ----------------------------------------------------------------------------------------

    def load_chat(self):
        con = self.con
        case = " ".join(f"WHEN created_at BETWEEN {lit(parse(p['start']))} AND {lit(parse(p['end']))} THEN {i}"
                        for i, p in enumerate(self.panels))
        counts = con.execute(
            f"""SELECT speaker_type, speaker, coalesce(room, 'general'), CASE {case} END, count(*) FROM chat
            WHERE {self.win()} GROUP BY ALL"""
        ).fetchall()
        by_room = Counter()
        for _, _, room, _, n in counts:
            by_room[room] += n
        rooms = self.spec.get("rooms", "auto")
        self.rooms = [r for r, _ in sorted(by_room.items(), key=lambda x: (-x[1], x[0]))] if rooms == "auto" else list(rooms)

        # An agent's group: the room it posted in most during the first panel where it posts.
        posts, elsewhere, self.posted_full = {}, set(), set()
        for stype, speaker, room, pi, n in counts:
            if stype == "user" or speaker is None:
                continue
            name = self.alias(speaker)
            if room in self.rooms:
                posts.setdefault(name, {}).setdefault(pi, Counter())[room] += n
                if self.panels[pi].get("show_other", True):
                    self.posted_full.add(name)
            else:
                elsewhere.add(name)
        self.group_of = {}
        for name, per in posts.items():
            c = per[min(per)]
            self.group_of[name] = max(c, key=lambda r: (c[r], -self.rooms.index(r)))
        self.elsewhere = elsewhere - set(posts)

        # Panels that hide untagged chat only need the tagged messages: prefilter in SQL when RE2 can.
        tagged = either(self.spec["claim"].get("chat"), (self.spec.get("correction") or {}).get("chat"),
                        (self.spec.get("correction") or {}).get("strong"), self.spec.get("linger"))
        pre = re2(con, sql_re(tagged))
        tagged_rx = rx(tagged)
        hide = lambda p: f"regexp_matches(content, {lit(sql_re(tagged))}, 'i')" if pre and not p.get("show_other", True) else None
        rows = con.execute(
            f"""SELECT created_at, speaker_type, speaker, room, id, content, {suspect_sql('content')}
            FROM (SELECT created_at, speaker_type, speaker, coalesce(room, 'general') AS room, id::VARCHAR AS id,
                         coalesce(content, '') AS content FROM chat
                  WHERE ({self.win(extra=hide)}) AND coalesce(room, 'general') IN ({','.join(lit(r) for r in self.rooms)}))
            ORDER BY created_at, id"""
        ).fetchall() if self.rooms else []
        rows = [(t, stype, speaker, room, mid, redact_parts(content, parts))
                for t, stype, speaker, room, mid, content, parts in rows]

        # The corrector: author of the first correction-worded message at or after `at`. During the
        # probe window its evidence-gathering is a hint; everyone else's reading of it is belief.
        if self.corr_ms is not None and not self.corrector:
            fx = self.x_strong or self.x_chat
            for t, stype, speaker, room, mid, content in rows:
                if ms(t) >= self.corr_ms and hit(fx, content.lower()):
                    self.corrector = self.alias(speaker) if stype != "user" else None
                    break

        self.chat, self.said, self.order_first, self.humans = [], {}, {}, {}
        self.chat_seq = {}  # name -> [(t, kind, id)] for every message, kept or not (for auto links)
        for t, stype, speaker, room, mid, content in rows:
            lc, tm = content.lower(), ms(t)
            if stype == "user":
                # Human rows: one per room, or the spec's human_rows row (group "_all" unless it names one).
                hr = next(((n, g) for n, p, g in self.human_rows if p.search(lc)), None)
                name = hr[0] if hr else f"Staff (human) · #{room}"
            else:
                name = self.alias(speaker)
            kind = self.chat_kind(name, room, tm, lc)
            claim = hit(self.c_chat, lc)
            if claim:
                self.said.setdefault(name, tm)
                if self.claim_rooms is None or room in self.claim_rooms:
                    self.label_ids.add(mid)
            if self.order_rx and self.order_rx.search(lc):
                self.order_first.setdefault(name, tm)
            self.chat_seq.setdefault(name, []).append((tm, kind, mid))
            # Panels with show_other false drop chat that matches none of the episode's regexes. A
            # message that names the claim stays even when its kind is "other" (for example a mention
            # after the correction), with an excerpt around the match if the match is past the clip.
            m = hit(tagged_rx, lc)
            p = self.panel_at(tm)
            if kind == "other" and not m and p and not p.get("show_other", True):
                continue
            if stype == "user":
                self.humans.setdefault(name, hr[1] if hr else room)
            text = clip(content, 900) if kind != "other" else \
                snippet(content, m, 120, 360) if m and m.start() > 300 else clip(content, 360)
            self.chat.append({"t": tm, "a": name, "room": room, "id": mid, "kind": kind, "stance": None, "check": None,
                              "text": text, "_claim": bool(claim)})

    def chat_kind(self, name, room, t, lc):
        in_rooms = self.claim_rooms is None or room in self.claim_rooms
        nbb = self.overrides.get(name, {}).get("never_belief_before")
        can_believe = in_rooms and not (nbb and t < ms(nbb))
        claim, hint = hit(self.c_chat, lc), hit(self.x_chat, lc)
        if self.corr_ms is None or t < self.probe_ms:
            if can_believe and claim:
                return "belief"
            return "hint" if hint else "other"  # the true fact, mentioned in passing
        if t < self.corr_ms:
            # The corrector is gathering evidence; everyone else reads it as more proof of the claim.
            if name == self.corrector:
                return "hint" if (hint or claim) else "other"
            return "belief" if can_believe and (claim or hint) else "other"
        if hit(self.x_strong, lc):
            return "fix"
        if hit(self.linger, lc):
            return "belief"  # still asserting the claim after the correction
        return "fix" if hint else "other"

    # Memory --------------------------------------------------------------------------------------

    def load_memory(self):
        """Every snapshot from memory_lookback to the last panel's end, for all agents. DuckDB returns
        text only for snapshots the spec's regexes can match (RE2 is linear time; Python's re is the
        bottleneck on 30k-character memories), with a flag per regex and per SECRET part. Python
        redacts the few texts that may hold a credential, then decides on the redacted text as in the
        prototype. The rest keep their size and state "none"."""
        con = self.con
        self.agent_names = {i: n for i, n in con.execute("SELECT id::VARCHAR, name FROM agents").fetchall()}
        claim_p, fix_p = self.spec["claim"].get("memory"), (self.spec.get("correction") or {}).get("memory")
        c_sql = (f"regexp_matches(content, {lit(sql_re(claim_p))}, 'i')" if re2(con, sql_re(claim_p)) else "true") \
            if claim_p else "false"
        f_sql = "false"
        if fix_p and self.corr_ms is not None:
            at = lit(from_ms(self.corr_ms))
            f_sql = f"(created_at >= {at} AND regexp_matches(content, {lit(sql_re(fix_p))}, 'i'))" \
                if re2(con, sql_re(fix_p)) else f"created_at >= {at}"
        if c_sql == "true" or f_sql.startswith("created_at"):
            self.warn("memory regex is not RE2-compatible: fetching full memory text (slow)")
        cur = con.execute(
            f"""SELECT created_at, agent_id, id, chars, CASE WHEN c OR f THEN content END, c, f,
                   CASE WHEN c OR f THEN {suspect_sql('content')} END
            FROM (SELECT created_at, agent_id::VARCHAR AS agent_id, id::VARCHAR AS id, length(content) AS chars,
                         content, {c_sql} AS c, {f_sql} AS f
                  FROM agent_memories WHERE created_at BETWEEN {lit(self.lookback)} AND {lit(self.end)})
            ORDER BY created_at, id"""
        )
        self.mem_all = []
        while batch := cur.fetchmany(500):
            for t, aid, mid, chars, content, c, f, parts in batch:
                tm = ms(t)
                name = self.alias(self.agent_names.get(aid, aid))
                state, m = "none", None
                if content is not None:
                    # Without a credential, the redacted text is the raw text and RE2's verdict (a
                    # superset of Python's) can skip a search; with one, Python runs both searches.
                    content = redact_parts(content, parts)
                    lc = content.lower()
                    claim = hit(self.c_mem, lc) if c or parts else None
                    fix = hit(self.x_mem, lc) if (f or parts) and self.corr_ms is not None and tm >= self.corr_ms else None
                    if fix:
                        state, m = "fix", fix
                    elif claim:
                        state, m = "claim", claim
                    if claim:
                        self.label_ids.add(mid)
                self.mem_all.append({"t": tm, "a": name, "id": mid, "state": state, "stance": None, "check": None,
                                     "text": snippet(content, m) if m else "", "chars": chars or 0})

    # Rows ----------------------------------------------------------------------------------------

    def build_rows(self):
        """One row per agent that posts in a panel showing all chat; per agent whose posts are all in
        panels that show only tagged chat, when it has a tagged mark somewhere in the episode (chat
        kind other than other, memory state other than none, or a file mark); per extra agent; per
        agent with no chat in the shown rooms whose memory holds the claim, an attribution or the
        correction; and per human row. Marks by anyone else are dropped, so every mark has a row."""
        spec = self.spec
        known = set(self.agent_names.values()) | set(self.aliases.values())
        tagged = {x["a"] for x in self.chat if x["kind"] != "other"} | \
            {x["a"] for x in self.mem_all if x["state"] != "none"} | {x["a"] for x in self.files}
        place = {n: g for n, g in self.group_of.items() if n in self.posted_full or n in tagged}
        notes = {}
        for e in spec.get("extra_agents", []):
            if e["name"] not in known:
                raise ValueError(f"extra_agents: unknown agent {e['name']!r}")
            place[e["name"]] = e.get("room") or place.get(e["name"]) or NOCHAT
            if e.get("note"):
                notes[e["name"]] = e["note"]
        for name, o in self.overrides.items():
            if o.get("note"):
                notes.setdefault(name, o["note"])
        # Agents with no chat in the window whose memory holds the claim or the correction.
        holders = sorted({x["a"] for x in self.mem_all if x["state"] in ("claim", "attributed", "fix")} - set(place))
        for name in holders:
            place[name] = OTHER_ROOMS if name in self.elsewhere else NOCHAT
        self.added = holders
        self.hidden = sorted(set(self.group_of) - set(place))  # untagged chat in show_other=false panels only
        self.mem = [x for x in self.mem_all if x["a"] in place]
        self.mem_by = {}  # name -> (times, snapshots), in time order
        for x in self.mem:
            ts, xs = self.mem_by.setdefault(x["a"], ([], []))
            ts.append(x["t"])
            xs.append(x)

        humans = self.humans
        self.dropped_files = sum(1 for x in self.files if x["a"] not in place)
        self.chat = [x for x in self.chat if x["a"] in place or x["a"] in humans]
        self.files = [x for x in self.files if x["a"] in place]
        chatted = set(self.group_of)  # silent: no post at all in the shown rooms inside the panels

        group_keys = [r for r in self.rooms if r in place.values() or r in humans.values()]
        group_keys += sorted({g for g in place.values() if g not in group_keys and g not in GROUP_LABELS})
        group_keys += [g for g in (OTHER_ROOMS, NOCHAT) if g in place.values()]
        group_keys += sorted({g for g in humans.values() if g not in group_keys})
        notes_g = spec.get("room_notes", {})
        self.groups = [{"key": g, "label": GROUP_LABELS.get(g, "#" + g), "note": notes_g.get(g, "")} for g in group_keys]

        # pin_first places named rows first in their group, in its order. It may name human rows too
        # (a human_rows entry with a room "group", or a "Staff (human) · #room" row); the other human
        # rows follow the agents.
        pins = spec.get("pin_first", {})
        for g in pins:
            if g not in group_keys:
                self.warn(f"pin_first: group {g!r} is not shown")
        rows = []
        for g in group_keys:
            members = [n for n, pg in place.items() if pg == g]
            hs = [h for h, hg in humans.items() if hg == g]
            pin = pins.get(g, [])
            for n in pin:
                if n not in members and n not in hs:
                    self.warn(f"pin_first: {n!r} is not in group {g!r}")
            members.sort(key=lambda n: (self.first_mark(n), n))
            hs.sort(key=lambda h: next((i for i, (n, _, _) in enumerate(self.human_rows) if n == h), -1))
            order = list(dict.fromkeys(n for n in pin if n in members or n in hs))
            order += [n for n in members if n not in order] + [h for h in hs if h not in order]
            human = set(hs)
            rows += [{"name": n, "group": g, "human": True, "silent": False, "note": ""} if n in human else
                     {"name": n, "group": g, "human": False, "silent": n not in chatted, "note": notes.get(n, "")}
                     for n in order]
        self.rows = rows
        self.row_of = {r["name"]: r for r in rows}
        # Spec entries that name an agent or a group the episode does not show.
        keys = {g["key"] for g in self.groups}
        for name in self.overrides:
            if name not in self.row_of:
                self.warn(f"agent_overrides: {name!r} has no row")
        for m in spec.get("moves", []):
            if m["agent"] not in self.row_of:
                self.warn(f"moves: {m['agent']!r} has no row")
            if m["to"] not in keys:
                self.warn(f"moves: group {m['to']!r} is not shown")
        for g in spec.get("room_notes", {}):
            if g not in keys:
                self.warn(f"room_notes: group {g!r} is not shown")

    def first_mark(self, name):
        """Row order inside a group: first order_by match (chat or claim memory), else first
        belief/claim mark; agents with neither go last, by name."""
        if not hasattr(self, "_claim_first"):
            self._claim_first = {}
            for x in self.mem_all:
                if x["state"] == "claim":
                    self._claim_first.setdefault(x["a"], x["t"])
        ts = [self._claim_first[name]] if name in self._claim_first else []
        if self.order_rx:
            ts += [self.order_first[name]] if name in self.order_first else []
        else:
            ts += [x["t"] for x in self.chat if x["a"] == name and x["kind"] == "belief"]
        return min(ts) if ts else float("inf")

    # Files ---------------------------------------------------------------------------------------

    def load_files(self):
        con = self.con
        pattern = either(self.spec["claim"].get("files"), (self.spec.get("correction") or {}).get("files"))
        self.files = []
        if not pattern:
            return
        cond = f"regexp_matches(coalesce(command, action_text, ''), {lit(sql_re(pattern))}, 'i')" \
            if re2(con, sql_re(pattern)) else "true"
        if cond == "true":
            self.warn("file regex is not RE2-compatible: scanning every turn in the panels (slow)")
        rows = con.execute(
            f"""SELECT created_at, agent, id::VARCHAR, coalesce(command, action_text, '') FROM turns
            WHERE ({self.win()}) AND {cond} ORDER BY created_at, id"""
        ).fetchall()
        for t, agent, tid, cmd in rows:
            if not agent:
                continue
            name = self.alias(agent)
            cmd = redact(cmd)
            kind, m = self.file_kind(ms(t), cmd.lower())
            if kind:
                self.files.append(self.file_item(t, name, tid, cmd, kind, m))

    def file_kind(self, t, lc):
        if self.corr_ms is not None and t >= self.probe_ms:
            m = hit(self.x_files, lc)
            if m:
                return "fix", m
            # After the correction, a command that still touches the claim shows what survived it.
            # (In the probe window such mentions are mostly agents revising the claim: left out.)
            m = hit(self.c_files, lc) if t >= self.corr_ms else None
            return ("belief", m) if m else (None, None)
        m = hit(self.c_files, lc)
        return ("belief", m) if m else (None, None)

    def file_item(self, t, name, tid, cmd, kind, m=None):
        return {"t": ms(t), "a": name, "id": tid, "kind": kind, "op": "write" if FILE_WRITE.search(cmd) else "read",
                "artifact": None, "text": snippet(cmd, m, before=200, length=620) if m else clip(cmd, 620),
                "_arts": self.repos(tid, cmd)}

    # Artifacts -----------------------------------------------------------------------------------

    def load_artifacts(self):
        """turn id -> artifact names from artifact_events.parquet (repo names, owner dropped)."""
        self.art_events, self.known_repos = {}, None
        if not ARTIFACT_EVENTS.exists():
            self.warn("artifact_events.parquet missing: artifact identity from command regexes only")
            return
        src = f"read_parquet({lit(ARTIFACT_EVENTS)})"
        short = lambda a: a.rstrip("/").split("/")[-1].lower().removesuffix(".git")
        self.known_repos = {short(a) for (a,) in self.con.execute(
            f"SELECT DISTINCT artifact FROM {src} WHERE artifact <> 'unknown'").fetchall()}
        for tid, a in self.con.execute(
            f"SELECT turn_id, artifact FROM {src} WHERE ({self.win()}) AND artifact <> 'unknown'"
        ).fetchall():
            self.art_events.setdefault(tid, set()).add(short(a))

    def repos(self, tid, cmd):
        """Artifacts a turn touches: from the artifact events file when it resolved the turn, else
        from repo-like names in the command outside heredoc bodies."""
        names = set(self.art_events.get(tid, ()))
        if names:
            return names
        bare = HEREDOC.sub(r"\1", cmd)
        for m in REPO_URL.finditer(bare):
            names.add(m.group(1).lower().removesuffix(".git"))
        for m in REPO_DIR.finditer(bare):
            n = m.group(1).lower().removesuffix(".git")
            if self.known_repos is None or n in self.known_repos:
                names.add(n)
        return {n for n in names if n and not NOT_REPO.search(n)}

    # Links ---------------------------------------------------------------------------------------

    def resolve(self, typ, prefix, where):
        coll = {"chat": self.chat, "mem": self.mem, "files": self.files, "file": self.files}.get(typ)
        if coll is None:
            raise ValueError(f"{where}: unknown type {typ!r} (chat, mem or files)")
        if not isinstance(prefix, str) or not prefix:
            raise ValueError(f"{where}: id prefix must be a non-empty string, got {prefix!r}")
        found = [x for x in coll if x["id"].startswith(prefix)]
        if len(found) != 1:
            if found:
                what = f"matches {len(found)} items ({', '.join(x['id'][:13] for x in found[:4])}): use a longer prefix"
            else:
                other = [t for t, c in (("chat", self.chat), ("mem", self.mem), ("files", self.files))
                         if t != typ and any(x["id"].startswith(prefix) for x in c)]
                why = {"chat": "outside the panels and rooms, by an agent with no row, or untagged chat in a "
                               "show_other=false panel",
                       "mem": "outside memory_lookback to the last panel's end, or by an agent with no row",
                       }.get(typ, "outside the panels, by an agent with no row, or a command no file regex tags "
                                  "(a hand link end is fetched by prefix; a step key is not)")
                what = f"matches nothing in the episode data ({why})" + \
                    (f"; it does match in {', '.join(other)}" if other else "")
            raise ValueError(f"{where}: {typ} id prefix {prefix!r} {what}")
        return found[0]

    def fetch_turns(self, prefixes, kinds):
        """Hand links may point at a turn the file regexes did not tag (an untagged read). Fetch those
        turns by id prefix and add them with the kind of the link's other end."""
        agents = {r["name"] for r in self.rows if not r["human"]}
        cond = " OR ".join(f"id::VARCHAR LIKE {lit(p + '%')}" for p in prefixes)
        for t, agent, tid, cmd in self.con.execute(
            f"""SELECT created_at, agent, id::VARCHAR, coalesce(command, action_text, '') FROM turns
            WHERE ({self.win()}) AND ({cond})"""
        ).fetchall():
            name = self.alias(agent) if agent else None
            if name in agents:
                kind = next(k for p, k in kinds.items() if tid.startswith(p)) or \
                    ("fix" if self.corr_ms is not None and ms(t) >= self.corr_ms else "belief")
                self.files.append(self.file_item(t, name, tid, redact(cmd), kind))
        self.files.sort(key=lambda x: (x["t"], x["id"]))

    def hand_links(self):
        links = self.spec.get("links", [])
        have = {x["id"] for x in self.files}
        missing = {}
        for ln in links:
            for end, other in (("from", "to"), ("to", "from")):
                typ, prefix = ln[end]
                if typ in ("files", "file") and not any(i.startswith(prefix) for i in have):
                    # The kind of the other end's family; an end that names neither (or another
                    # missing file) leaves it to the turn's time. The first link that decides wins.
                    o = ln[other]
                    try:
                        ox = self.resolve(o[0], o[1], "link")
                        kind = HAND_KIND.get(ox.get("kind") or ox.get("state"))
                    except ValueError:
                        kind = None
                    if missing.get(prefix) is None:
                        missing[prefix] = kind
        if missing:
            self.fetch_turns(missing, missing)
        out = []
        for i, ln in enumerate(links):
            ends = []
            for end in ("from", "to"):
                typ, prefix = ln[end]
                x = self.resolve(typ, prefix, f"links[{i}].{end}")
                ends.append(["files" if typ == "file" else typ, x["id"]])
            out.append({"from": ends[0], "to": ends[1], "label": ln.get("label", ""), "auto": False})
        return out

    def auto_links(self, hand):
        """Cross-room hand-offs through files (SPEC: Auto links, and the engine note there). A read
        of artifact X by agent B links back to the latest tagged write of X in the 90 minutes before
        it by an agent whose room differs from B's. A read needs evidence that B saw the content:
        its command matches the write's file regex (a tagged read), or its output does (a pull that
        lists the file, a log that shows the commit title), and B must not already hold that state
        family (nothing crosses a wall when the reader has it already). Per reader, artifact and
        family only one read is kept: the first tagged read, else the first read with matching
        output. If B's next memory snapshot or chat message within 45 minutes is in the family, the
        read links on to the earlier of the two. Auto links that repeat a hand link, or end where a
        hand link ends, are left out."""
        writes = [f for f in self.files if f["op"] == "write" and f["_arts"]]
        if not writes:
            return []
        agents = {r["name"] for r in self.rows if not r["human"]}
        names = sorted(set().union(*(w["_arts"] for w in writes)))

        # Untagged reads: one more turn scan, limited to 90 minutes after each write (inside the
        # panels) and to commands that name a written artifact or that the artifact file maps to one.
        spans = []
        for w in sorted(writes, key=lambda w: w["t"]):
            a, b = w["t"], w["t"] + READ_WINDOW
            if spans and a <= spans[-1][1]:
                spans[-1][1] = max(spans[-1][1], b)
            else:
                spans.append([a, b])
        clipped = [(max(a, p["s"]), min(b, p["e"])) for a, b in spans for p in self.panels if a < p["e"] and b > p["s"]]
        have = {x["id"] for x in self.files}
        ids = [t for t, arts in self.art_events.items() if arts & set(names) and t not in have]
        name_rx = "|".join(re.escape(n) for n in names)
        win = " OR ".join(f"(created_at BETWEEN {lit(from_ms(a))} AND {lit(from_ms(b))})" for a, b in clipped)
        by_id = f" OR id::VARCHAR IN ({','.join(lit(i) for i in ids)})" if ids else ""
        family_rx = {"belief": self.c_files, "fix": self.x_files}
        # Only output that can hold the evidence comes back (RE2 keeps whatever Python's re would match).
        family = sql_re(either(self.spec["claim"].get("files"), (self.spec.get("correction") or {}).get("files")))
        evidence = f"AND regexp_matches(output, {lit(family)}, 'i')" if re2(self.con, family) else ""
        untagged = []
        if clipped:
            for t, agent, tid, cmd, pc, output, po in self.con.execute(
                f"""SELECT created_at, agent, id, cmd, {suspect_sql('cmd')}, output, {suspect_sql('output')}
                FROM (SELECT created_at, agent, id::VARCHAR AS id, coalesce(command, action_text, '') AS cmd,
                             left(coalesce(output, '') || chr(10) || coalesce(error, ''), {OUTPUT_CHARS}) AS output FROM turns
                      WHERE ({win}) AND (regexp_matches(coalesce(command, action_text, ''), {lit(name_rx)}, 'i'){by_id}))
                WHERE true {evidence}
                ORDER BY created_at, id"""
            ).fetchall():
                name = self.alias(agent) if agent else None
                if name not in agents or tid in have:
                    continue
                if len(output) >= OUTPUT_CHARS:
                    output = re.sub(r"\S*$", "", output)  # a token cut at the limit could be part of a credential
                cmd, output = redact_parts(cmd, pc), redact_parts(output, po)
                if FILE_WRITE.search(cmd):
                    continue
                seen = {fam: m for fam, r in family_rx.items() if (m := hit(r, output.lower()))}
                if not seen:
                    continue
                item = self.file_item(t, name, tid, cmd, None)
                if item["_arts"] & set(names):
                    item["_seen"] = seen
                    item["_out"] = output
                    untagged.append(item)

        self.load_rooms(min(w["t"] for w in writes), max([b for _, b in clipped] + [w["t"] for w in writes]))
        room_at = self.chat_room_at

        def best_write(r, fam, arts):
            """The latest write of the family to one of arts in the 90 minutes before read r, by
            another agent whose room then differs from the reader's room now."""
            rb, best = room_at(r["a"], r["t"]), None
            for w in writes:
                if w["kind"] == fam and w["_arts"] & arts and w["a"] != r["a"] and \
                        w["t"] < r["t"] <= w["t"] + READ_WINDOW and (best is None or w["t"] > best["t"]):
                    ra = room_at(w["a"], w["t"])
                    if ra and rb and ra != rb:
                        best = w
            return best

        qualifies = lambda r, fam: r["kind"] == fam or fam in r.get("_seen", {})
        reads = sorted([f for f in self.files if f["op"] == "read" and f["_arts"]] + untagged, key=lambda f: (f["t"], f["id"]))
        chosen = {}  # (reader, artifact, family) -> (read, write)
        for r in reads:
            if not room_at(r["a"], r["t"]):
                continue
            for art in sorted(r["_arts"]):
                for fam in FAMILY:
                    if not qualifies(r, fam) or self.held(r["a"], r["t"], FAMILY[fam]):
                        continue
                    # The earliest read with evidence: a later read whose command names the claim
                    # shows the reader knew it by then, not where it came from.
                    best = best_write(r, fam, {art})
                    key = (r["a"], art, fam)
                    if best and key not in chosen:
                        chosen[key] = (r, best)

        # The second link starts at the read that brought the content the reader's next mark holds.
        # When the reader reads the family again before that mark and the read shows a newer write
        # (by another agent), the newer write is the likely source: the second link moves to that
        # read, which gets its own hand-off link, when the write came from another room, and is
        # left out when it came from the reader's own room.
        def latest_write(q, fam):
            return max((w for w in writes if w["kind"] == fam and w["_arts"] & q["_arts"] and w["a"] != q["a"]
                        and w["t"] < q["t"] <= w["t"] + READ_WINDOW), key=lambda w: w["t"], default=None)

        hand_pairs = {(tuple(ln["from"]), tuple(ln["to"])) for ln in hand}
        hand_ends = {tuple(ln["to"]) for ln in hand}
        # (write id, reader) pairs a hand link already shows, whichever of the reader's marks it ends at
        items = {(typ, x["id"]): x for typ, c in (("chat", self.chat), ("mem", self.mem), ("files", self.files)) for x in c}
        hand_readers = {(ln["from"][1], items[tuple(ln["to"])]["a"]) for ln in hand
                        if ln["from"][0] == "files" and tuple(ln["to"]) in items}
        emit = []  # (read, write, the reader's next mark in the family or None)
        for r, w in sorted(chosen.values(), key=lambda rw: (rw[0]["t"], rw[1]["t"])):
            fam = w["kind"]
            nxt = self.uptake(r["a"], r["t"], FAMILY[fam])
            anchor, aw = r, w
            if nxt and (nxt[0], nxt[1]["id"]) not in hand_ends:
                for q in reads:
                    if q["a"] != r["a"] or not r["t"] < q["t"] < nxt[1]["t"] or not qualifies(q, fam):
                        continue
                    lw = latest_write(q, fam)
                    if lw and lw["t"] > aw["t"]:
                        ra, rb = room_at(lw["a"], lw["t"]), room_at(q["a"], q["t"])
                        if not (ra and rb and ra != rb):
                            anchor = None  # newer content from the reader's own room
                            break
                        anchor, aw = q, lw
            if anchor is r:
                emit.append((r, w, nxt))
            else:
                emit.append((r, w, None))
                if anchor is not None:
                    emit.append((anchor, aw, self.uptake(anchor["a"], anchor["t"], FAMILY[fam])))

        out, pairs = [], set()
        for r, w, nxt in emit:
            if (w["id"], r["id"]) in pairs:
                continue
            pairs.add((w["id"], r["id"]))
            reader, held = r["a"], "the correction" if w["kind"] == "fix" else "the claim"
            ra, rb = room_at(w["a"], w["t"]), room_at(reader, r["t"])
            art = ", ".join(sorted(w["_arts"] & r["_arts"]))
            link = (("files", w["id"]), ("files", r["id"]))
            new = []
            if link not in hand_pairs and link[1] not in hand_ends and (w["id"], reader) not in hand_readers:
                # File marks come from keywords, not labels: a claim-family write only names the
                # claim (it may argue against it), and a fix-family write in the probe window comes
                # before the correction itself.
                wrote = f"mentions the claim in {art}" if w["kind"] == "belief" else \
                    f"writes evidence for the correction into {art}" if w["t"] < self.corr_ms else \
                    f"writes the correction into {art}"
                new.append({"from": list(link[0]), "to": list(link[1]), "auto": True,
                            "label": f"{w['a']} (#{ra}) {wrote}; "
                                     f"{reader} (#{rb}) reads {art} {minutes(r['t'] - w['t'])} later"})
            if nxt:
                typ, x = nxt
                link2 = (("files", r["id"]), (typ, x["id"]))
                if link2 not in hand_pairs and link2[1] not in hand_ends:
                    what = f"{reader}'s memory holds {held}" if typ == "mem" else \
                        f"{reader} states the correction in chat" if w["kind"] == "fix" else f"{reader} repeats the claim in chat"
                    new.append({"from": list(link2[0]), "to": list(link2[1]), "auto": True,
                                "label": f"{what} {minutes(x['t'] - r['t'])} after reading {art}"})
            if r["kind"] is None and (new or link[1] in hand_ends):
                # An untagged read that became a link end: show the output that holds the evidence.
                r["kind"] = w["kind"]
                r["text"] = clip(r["text"].lstrip("…"), 300) + "\n→ output: " + snippet(r["_out"], r["_seen"][w["kind"]], 120, 360)
                self.files.append(r)
                have.add(r["id"])
            if r["id"] in have:
                out += new
        self.files.sort(key=lambda x: (x["t"], x["id"]))
        uniq = {}
        for ln in out:
            uniq.setdefault((tuple(ln["from"]), tuple(ln["to"])), ln)
        return list(uniq.values())

    def load_rooms(self, lo, hi):
        """Agents' chat rooms from 48 hours before lo to hi (any room, shown or not), for
        chat_room_at. Widens the loaded span when asked for more."""
        lo -= ROOM_MEMORY
        span = getattr(self, "_room_span", None)
        if span and span[0] <= lo and hi <= span[1]:
            return
        if span:
            lo, hi = min(lo, span[0]), max(hi, span[1])
        self._room_span, self._rooms = (lo, hi), {}
        for speaker, room, t in self.con.execute(
            f"""SELECT speaker, coalesce(room, 'general'), created_at FROM chat WHERE speaker_type = 'agent'
            AND created_at BETWEEN {lit(from_ms(lo))} AND {lit(from_ms(hi))} ORDER BY created_at"""
        ).fetchall():
            ts, rooms = self._rooms.setdefault(self.alias(speaker), ([], []))
            ts.append(ms(t))
            rooms.append(room)

    def chat_room_at(self, name, t):
        """Room of an agent at time t: the room of its most recent chat message in the previous 48
        hours, or None. load_rooms must cover t."""
        ts, rooms = self._rooms.get(name, ([], []))
        i = bisect_right(ts, t) - 1
        return rooms[i] if i >= 0 and t - ts[i] <= ROOM_MEMORY else None

    def link_rooms(self, links):
        """Each link's rooms at that moment, as "rooms": [from, to]: a chat end's room; else the
        author's room then (chat_room_at), else its row's group when that is a room; else null."""
        coll = {"chat": self.chat, "mem": self.mem, "files": self.files}
        ends = {(typ, x["id"]): x for typ, c in coll.items() for x in c}
        ts = [ends[tuple(ln[e])]["t"] for ln in links for e in ("from", "to") if tuple(ln[e]) in ends]
        if ts:
            self.load_rooms(min(ts), max(ts))
        group = {r["name"]: r["group"] for r in self.rows}

        def room(end):
            x = ends.get(tuple(end))
            if x is None:
                return None
            if end[0] == "chat":
                return x["room"]
            g = group.get(x["a"])
            return self.chat_room_at(x["a"], x["t"]) or (g if g and not g.startswith("_") else None)

        for ln in links:
            ln["rooms"] = [room(ln["from"]), room(ln["to"])]

    def held(self, name, t, family):
        """Did the agent hold the family before t: its latest memory snapshot, or any chat message?"""
        ts, xs = self.mem_by.get(name, ([], []))
        i = bisect_right(ts, t - 1) - 1
        if i >= 0 and xs[i]["state"] in family:
            return True
        return any(k in family for ct, k, _ in self.chat_seq.get(name, []) if ct < t)

    def uptake(self, name, t, family):
        """The reader's next memory snapshot or chat message within 45 minutes, whichever comes first
        among those in the family."""
        cands = []
        ts, xs = self.mem_by.get(name, ([], []))
        i = bisect_right(ts, t)
        m = xs[i] if i < len(xs) and xs[i]["t"] <= t + UPTAKE_WINDOW else None
        if m and m["state"] in family:
            cands.append(("mem", m))
        c = next((s for s in self.chat_seq.get(name, []) if t < s[0] <= t + UPTAKE_WINDOW), None)
        if c:
            x = next((x for x in self.chat if x["id"] == c[2]), None)
            if x and x["kind"] in family:
                cands.append(("chat", x))
        return min(cands, key=lambda c: c[1]["t"]) if cands else None

    # Labels --------------------------------------------------------------------------------------

    def apply_labels(self):
        slug = self.spec.get("slug")
        path = TRACER / "labels" / f"{slug}.json"
        if not slug or not self.spec.get("labels", True) or not path.exists():
            return None
        store = json.loads(path.read_text())
        items = store.get("items", {})
        for coll, field, mapping in ((self.chat, "kind", LABEL_CHAT), (self.mem_all, "state", LABEL_MEM)):
            for x in coll:
                lab = items.get(x["id"])
                if not lab:
                    continue
                x["stance"], x["check"] = lab.get("stance"), lab.get("check")
                if lab.get("reason"):
                    x["reason"] = redact(lab["reason"])  # optional field the viewer shows in its inspector
                # A claim match maps by stance. After the correction that includes chat the regexes
                # left as "other": the labeller says whether the mention still adopts the claim.
                late = x.get("_claim") and x[field] == "other" and self.corr_ms is not None and x["t"] >= self.corr_ms
                if x[field] in ("belief", "claim") or late:
                    # An item only the check pass labelled maps by that label, so red still needs an
                    # adopts (the viewer flags it: no label from the main pass).
                    x[field] = mapping.get(x["stance"] or x["check"], x[field])
        # Chat seq kinds feed auto links; keep them in step with the labelled kinds.
        kinds = {x["id"]: x["kind"] for x in self.chat}
        for seq in self.chat_seq.values():
            seq[:] = [(t, kinds.get(i, k), i) for t, k, i in seq]
        return {"items": len(self.label_ids),
                "labelled": sum(1 for i in self.label_ids if (items.get(i) or {}).get("stance")),
                "model": store.get("model"), "agreement": store.get("agreement"), "checkModel": store.get("checkModel"),
                "checked": store.get("checked"), "checkSample": store.get("checkSample")}

    # Stats ---------------------------------------------------------------------------------------

    def stats(self, links):
        human = {r["name"] for r in self.rows if r["human"]}
        before = lambda t: self.corr_ms is None or t < self.corr_ms
        chat = [x for x in self.chat if x["a"] not in human]
        mem = [x for x in self.mem if x["a"] not in human]
        files = [x for x in self.files if x["a"] not in human]
        chat_claim = {x["a"] for x in chat if x["kind"] == "belief" and before(x["t"])}
        chat_belief = {x["a"] for x in chat if x["kind"] == "belief"}
        claim_first = {}
        for x in mem:
            if x["state"] == "claim" and before(x["t"]):
                claim_first.setdefault(x["a"], x["t"])
        said = {a for a, t in self.said.items() if before(t)}
        ever_claim = {x["a"] for x in mem if x["state"] == "claim"}
        reached = chat_belief | ever_claim
        reach = {}
        for g in self.groups:
            members = [r["name"] for r in self.rows if r["group"] == g["key"] and not r["human"]]
            if members:
                reach[g["key"]] = {"reached": sum(n in reached for n in members), "total": len(members)}
        first_minute = set()
        if self.corr_ms is not None:
            # Within 60 s of `at`, at the spec's one-second precision; the corrector is not counted.
            first_minute = {x["a"] for x in chat if x["kind"] == "fix" and x["a"] != self.corrector
                            and self.corr_ms <= x["t"] and x["t"] // 1000 * 1000 <= self.corr_ms + 60000}
        linger = set()
        if self.corr_ms is not None:
            linger = {x["a"] for x in chat if x["kind"] == "belief" and x["t"] >= self.corr_ms} | \
                     {x["a"] for x in mem if x["state"] == "claim" and x["t"] >= self.corr_ms}
        # Rooms at the moment of each end (link_rooms), as the auto link labels give them.
        cross = sum(1 for ln in links if None not in ln["rooms"] and ln["rooms"][0] != ln["rooms"][1])

        def first(kinds):
            marks = [("chat", x, x["kind"]) for x in chat] + [("mem", x, x["state"]) for x in mem] + \
                    [("files", x, x["kind"]) for x in files]
            marks = [(x["t"], typ, x) for typ, x, k in marks if k in kinds]
            if not marks:
                return None
            t, typ, x = min(marks, key=lambda m: (m[0], m[1]))
            return {"t": t, "a": x["a"], "type": typ, "id": x["id"]}

        return {
            "claim_chat_agents": len(chat_claim),
            "claim_mem_agents": len(claim_first),
            "claim_mem_minutes": round((max(claim_first.values()) - min(claim_first.values())) / 60000) if claim_first else 0,
            "memory_only": sorted(set(claim_first) - said),
            "attributed_only": sorted({x["a"] for x in mem if x["state"] == "attributed"} - ever_claim),
            "group_reach": reach,
            "fix_mem_agents": len({x["a"] for x in mem if x["state"] == "fix"}),
            "fix_first_minute": len(first_minute),
            "linger_agents": sorted(linger),
            "crossroom_links": cross,
            "first_claim": first({"belief", "claim"}),
            "first_fix": first({"fix"}),
            "corrector": self.corrector,
        }

    def compact_memory(self, keep, data):
        """Panels that show everything keep every snapshot. Elsewhere (panels with show_other false,
        the lookback, gaps) a snapshot stays only where the agent's state or stance changes, as each
        agent's last snapshot before a panel start and at or before it (the state it carries in, and
        the source of the gap band before it), as its first snapshot at or after the correction (so
        linger_agents can be checked from the data), when the two labellers disagree on it (the
        viewer counts those), when a link or step names it (keep), or where a step's lit region
        starts or ends (focus_keep). The bands the viewer draws and the regions each step lights come
        out the same; a long panel stays small. data: the episode data with every snapshot."""
        full = [(p["s"], p["e"]) for p in self.panels if p.get("show_other", True)]
        carry = set()
        for ts, xs in self.mem_by.values():
            for p in self.panels:
                for i in (bisect_left(ts, p["s"]) - 1, bisect_right(ts, p["s"]) - 1):
                    if i >= 0:
                        carry.add(xs[i]["id"])
            if self.corr_ms is not None:
                i = bisect_right(ts, self.corr_ms - 1)
                if i < len(xs):
                    carry.add(xs[i]["id"])
        kept, state = set(), {}
        for x in self.mem:
            changed = state.get(x["a"]) != (x["state"], x["stance"])
            state[x["a"]] = (x["state"], x["stance"])
            if changed or x["id"] in carry or x["id"] in keep or (x["check"] and x["check"] != x["stance"]) or \
                    any(a <= x["t"] <= b for a, b in full):
                kept.add(x["id"])
        kept = self.focus_keep(data, kept)
        out = [x for x in self.mem if x["id"] in kept]
        self.dropped_mem = len(self.mem) - len(out)
        self.mem = out

    def focus_keep(self, data, kept):
        """Snapshots a step's focus needs, added to kept. The viewer lights a band when it matches a
        clause, or when the snapshot that starts it does; dropping a snapshot merges its band into the
        one before, which can change what lights (a time window, a text regex, a link end). So keep
        each snapshot whose band's lit state differs from the band before it, then check the thinned
        model against the full one, step by step, and keep all of an agent's snapshots in any panel
        where they still differ. Uses tracer.check's copy of the viewer model."""
        from tracer.check import Report, compile_clause, match, model

        r = Report("")
        steps = []
        for st in data["steps"]:
            f = st.get("focus")
            if not f:
                continue
            raw = f if isinstance(f, list) else f.get("any") if isinstance(f.get("any"), list) else [f]
            cl = [compile_clause(c, "", r) for c in raw]
            cl = [c for c in cl if c is not None and ("type" not in c or c["type"] & {"mem", "band"})]
            if cl:
                steps.append(cl)
        if not steps:
            return kept
        thin = {x["id"] for x in self.mem} - kept  # candidates to drop
        if not thin:
            return kept
        agents_thin = {x["a"] for x in self.mem if x["id"] in thin}

        def lit(d):
            """Per step: {(agent, panel): lit intervals} and the ids of lit snapshots, for agents
            that have snapshots to drop."""
            marks, bands = model(d)
            out = []
            for cl in steps:
                direct = {i for i, m in enumerate(marks)
                          if m["type"] == "mem" and m["a"] in agents_thin and any(match(c, m) for c in cl)}
                on, regions, starts = set(direct), {}, []
                for b in bands:
                    if b["a"] not in agents_thin:
                        continue
                    hit_ = any(match(c, b) for c in cl)
                    if hit_:
                        on.add(b["src"])
                    lit_ = hit_ or (b["start"] and b["src"] in direct)
                    starts.append((b, lit_))
                    if lit_:
                        regions.setdefault((b["a"], b["panel"]), []).append((b["t"], b["t1"]))
                for k, iv in regions.items():
                    iv.sort()
                    merged = [list(iv[0])]
                    for a, b_ in iv[1:]:
                        if a <= merged[-1][1]:
                            merged[-1][1] = max(merged[-1][1], b_)
                        else:
                            merged.append([a, b_])
                    regions[k] = merged
                out.append((regions, {marks[i]["id"] for i in on}, starts, marks))
            return out

        full_lit = lit(data)
        # Boundaries: a band whose lit state differs from the band before it in the same agent-panel.
        for regions, on, starts, marks in full_lit:
            prev = {}
            for b, lit_ in sorted(starts, key=lambda s: (s[0]["a"], s[0]["panel"], s[0]["t"])):
                k = (b["a"], b["panel"])
                if b["start"] and (k not in prev or prev[k] != lit_):
                    kept.add(marks[b["src"]]["id"])
                prev[k] = lit_
        panel_id = lambda t: (self.panel_at(t) or {}).get("id")
        for attempt in range(2):
            d = dict(data, mem=[x for x in self.mem if x["id"] in kept])
            fix = set()
            for (rf, onf, _, _), (rt, ont, _, _) in zip(full_lit, lit(d)):
                fix |= {k for k in set(rf) | set(rt) if rf.get(k) != rt.get(k)}
                fix |= {(x["a"], panel_id(x["t"])) for x in d["mem"] if (x["id"] in onf) != (x["id"] in ont)}
            if not fix:
                return kept
            if attempt == 0:  # keep every snapshot of the agent in that panel
                kept |= {x["id"] for x in self.mem if (x["a"], panel_id(x["t"])) in fix}
        names = sorted({a for a, _ in fix})
        self.warn(f"memory thinning: kept every snapshot of {', '.join(names)} so the steps light the same")
        return kept | {x["id"] for x in self.mem if x["a"] in names}

    # Assembly ------------------------------------------------------------------------------------

    def gaps(self):
        labels = self.spec.get("gap_labels", {})
        out = []
        for a, b in zip(self.panels, self.panels[1:]):
            label = labels.get(f"{a['id']}|{b['id']}")
            if label is None:
                da, db = local(a["e"], self.disp).date(), local(b["s"], self.disp).date()
                gap = b["s"] - a["e"]
                if db > da:
                    n = (db - da).days
                    label = "1 day later" if n == 1 else f"{n} days later"
                elif gap >= 3600000:
                    n = round(gap / 3600000)
                    label = "1 hour later" if n == 1 else f"{n} hours later"
                elif gap > 0:
                    label = minutes(gap) + " later"
                else:
                    label = ""
            out.append({"after": a["id"], "label": label})
        return out

    def steps(self):
        out = []
        for i, st in enumerate(self.spec.get("steps", [])):
            st = copy.deepcopy(st)
            if st.get("key"):
                if not (isinstance(st["key"], list) and len(st["key"]) == 2):
                    raise ValueError(f"steps[{i}] ({st.get('title', '')}) key must be [type, id prefix], got {st['key']!r}")
                typ, prefix = st["key"]
                x = self.resolve(typ, prefix, f"steps[{i}] ({st.get('title', '')}) key")
                st["key"] = ["files" if typ == "file" else typ, x["id"]]
            out.append(st)
        return out

    def timed(self, name, f, *args):
        t0 = time.time()
        out = f(*args)
        self.timings[name] = round(time.time() - t0, 1)
        return out

    def build(self):
        spec = self.spec
        self.timings = {}
        self.timed("chat", self.load_chat)
        self.timed("memory", self.load_memory)
        self.label_stats = self.apply_labels()
        self.timed("artifacts", self.load_artifacts)
        self.timed("files", self.load_files)
        self.build_rows()
        links = self.timed("hand links", self.hand_links)
        if spec.get("auto_links", True):
            links += self.timed("auto links", self.auto_links, links)
        for ln in links:
            if ln["auto"]:
                ln["label"] = redact(ln["label"])  # it quotes artifact names from the data
        self.link_rooms(links)
        for f in self.files:
            f["artifact"] = redact(", ".join(sorted(f.pop("_arts")))) or None
            f.pop("_seen", None)
            f.pop("_out", None)
        for x in self.chat:
            x.pop("_claim", None)
        stats = self.stats(links)
        figures = [{"value": fill(f["value"], stats), "label": fill(f.get("label", ""), stats)}
                   for f in spec.get("figures", [])]
        steps = self.steps()
        corr = spec.get("correction") or {}
        notes = {"how": [], "method": [], "limits": [], **spec.get("notes", {})}
        claim = spec["claim"]
        data = {
            "slug": spec.get("slug"), "title": spec.get("title", ""), "headline": spec.get("headline", ""),
            "lede": spec.get("lede", ""), "tzOffsetHours": self.tz, "timeZone": self.zone.key if self.zone else None,
            "claimLabel": claim.get("label"), "correctionLabel": corr.get("label"),
            # The spec's regexes (Python syntax), so the viewer can highlight the words they match.
            "patterns": {
                "claim": {"chat": claim.get("chat"), "mem": claim.get("memory"), "files": claim.get("files")},
                "correction": {"chat": corr.get("chat"), "strong": corr.get("strong"), "mem": corr.get("memory"),
                               "files": corr.get("files")} if corr else None,
                "linger": spec.get("linger"),
            },
            # day: the Village day the panel starts on; endDay: the day it ends on (an end at midnight
            # belongs to the day before).
            "panels": [{"id": p["id"], "label": p.get("label", p["id"]), "startMs": p["s"], "endMs": p["e"],
                        "weight": p.get("weight", 1.0), "showOther": p.get("show_other", True),
                        "day": village_day(p["s"], self.disp), "endDay": village_day(p["e"] - 1, self.disp)}
                       for p in self.panels],
            "gaps": self.gaps(),
            "correctionMs": self.corr_ms,
            "groups": self.groups,
            "rows": self.rows,
            "chat": self.chat,
            "mem": self.mem,
            "files": self.files,
            "links": links,
            "annotations": [{"t": ms(a["t"]), "label": a.get("label", ""), "anchor": a.get("anchor", "start")}
                            for a in spec.get("annotations", [])],
            "moves": [{"agent": m["agent"], "t": ms(m["t"]), "toGroup": m["to"], "label": m.get("label", "moves")}
                      for m in spec.get("moves", [])],
            "stats": stats,
            "figures": figures,
            "steps": steps,
            "notes": notes,
            "labelStats": self.label_stats,
        }
        self.timed("thinning", self.compact_memory,
                   {ln[end][1] for ln in links for end in ("from", "to") if ln[end][0] == "mem"} |
                   {st["key"][1] for st in steps if st.get("key") and st["key"][0] == "mem"}, data)
        data["mem"] = self.mem
        return data


def fill(text, stats):
    """Fill {stat}, {a.b} and {x.length} placeholders from the stats."""
    def sub(m):
        v = stats
        for part in m.group(1).split("."):
            if isinstance(v, dict) and part in v:
                v = v[part]
            elif part == "length" and isinstance(v, (list, dict, str)):
                v = len(v)
            else:
                raise ValueError(f"figure placeholder {{{m.group(1)}}}: no {part!r} in stats")
        if isinstance(v, dict):
            raise ValueError(f"figure placeholder {{{m.group(1)}}} is an object; name one of its keys "
                             f"({', '.join(map(str, v))})")
        if isinstance(v, list):
            return ", ".join(map(str, v))
        if isinstance(v, float):
            return f"{v:g}"
        return "none" if v is None else str(v)

    return PLACEHOLDER.sub(sub, str(text))


# Output ------------------------------------------------------------------------------------------

def script_json(obj):
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def write_episode(data):
    path = OUT / "episodes" / f"{data['slug']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False))
    return path


def write_site():
    """tracer/out/site/: episode JSON, an index, the viewer in static mode (body-level, for the
    artifact host) and preview.html (a full page with the episodes inlined, for file:// viewing)."""
    site = OUT / "site"
    (site / "episodes").mkdir(parents=True, exist_ok=True)
    entries, inline = [], {}
    for slug in list_specs():
        src = OUT / "episodes" / f"{slug}.json"
        if not src.exists():
            print(f"site: {slug} not built yet, left out", file=sys.stderr)
            continue
        data = json.loads(src.read_text())
        (site / "episodes" / f"{slug}.json").write_text(src.read_text())
        entries.append({"slug": slug, "title": data["title"], "headline": data["headline"], "url": f"episodes/{slug}.json"})
        inline[slug] = data
    (site / "episodes" / "index.json").write_text(json.dumps(entries, ensure_ascii=False, indent=1))
    tpl_path = TRACER / "template.html"
    if not tpl_path.exists():
        print("site: tracer/template.html missing, skipped index.html and preview.html", file=sys.stderr)
        return entries
    tpl = tpl_path.read_text()
    if MARKER not in tpl:
        raise ValueError(f"tracer/template.html has no {MARKER} marker")
    (site / "index.html").write_text(tpl.replace(MARKER, script_json({"mode": "static", "episodes": entries})))
    # file:// pages cannot fetch the episode JSON, so the preview inlines it (config null -> TRACER_INLINE).
    (site / "preview.html").write_text(
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>Belief Tracer</title>\n</head>\n<body>\n'
        f"<script>window.TRACER_INLINE = {script_json(inline)};</script>\n"
        + tpl + "\n</body>\n</html>\n"
    )
    return entries


def summary(data, info, seconds):
    s = data["stats"]
    kinds = Counter(x["kind"] for x in data["chat"])
    states = Counter(x["state"] for x in data["mem"])
    fk = Counter(f"{x['kind']}/{x['op']}" for x in data["files"])
    auto = sum(ln["auto"] for ln in data["links"])
    lines = [
        f"== {data['slug']}  ({seconds:.1f} s)",
        f"rows {len(data['rows'])} in {len(data['groups'])} groups ({', '.join(g['key'] for g in data['groups'])}); "
        f"added with no chat: {len(info['addedNoChat'])} {info['addedNoChat'] or ''}; "
        f"no row (untagged chat in show_other=false panels only): {len(info['noRow'])} {info['noRow'] or ''}; "
        f"file marks by agents with no row: {info['filesNoRow']}",
        f"chat {len(data['chat'])}: " + " ".join(f"{k} {kinds[k]}" for k in ("belief", "attributed", "hint", "fix", "other")),
        f"mem {len(data['mem'])}: " + " ".join(f"{k} {states[k]}" for k in ("claim", "attributed", "fix", "none")),
        f"files {len(data['files'])}: " + " ".join(f"{k} {v}" for k, v in sorted(fk.items())),
        f"seconds: {info['timings']}",
        f"links {len(data['links'])} ({auto} auto); corrector: {info['corrector']}; "
        f"same-state snapshots merged outside full panels: {info['memMerged']}",
        "labels: " + (json.dumps(data["labelStats"]) if data["labelStats"] else "none"),
        json.dumps(s, indent=1, ensure_ascii=False),
    ]
    lines += [f"figure: {f['value']} | {f['label']}" for f in data["figures"]]
    lines += [f"warning: {w}" for w in info["warnings"]]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Build Belief Tracer episodes from tracer/episodes/<slug>.json.")
    ap.add_argument("slugs", nargs="*")
    ap.add_argument("--all", action="store_true", help="build every spec in tracer/episodes/")
    ap.add_argument("--site", action="store_true", help="also write the static site to tracer/out/site/")
    args = ap.parse_args()
    slugs = list_specs() if args.all else args.slugs
    if not slugs and not args.site:
        ap.error("give one or more slugs, or --all")
    con = connect()
    failed = []
    for slug in slugs:
        t0 = time.time()
        info = {}
        try:
            data = build_episode(load_spec(slug), con, info)
        except Exception as e:  # report and go on to the next episode
            failed.append(slug)
            print(f"== {slug}  FAILED: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        path = write_episode(data)
        print(summary(data, info, time.time() - t0))
        print(f"wrote {path.relative_to(ROOT)}\n")
    con.close()
    if args.site:
        entries = write_site()
        print(f"site: {len(entries)} episodes in {(OUT / 'site').relative_to(ROOT)}")
    if failed:
        sys.exit(f"failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()
