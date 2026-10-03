"""Belief Tracer local app: the viewer in live mode, the curated episodes, and live traces of any
claim. The contract is tracer/SPEC.md ("Local app").

Usage: uv run python -m tracer.serve [--port 8765]

  GET  /                     the viewer (template.html) with config {"mode": "live"}
  GET  /api/episodes         [{slug, title, headline}] for every curated spec
  GET  /api/episode/<slug>   tracer/out/episodes/<slug>.json while it is newer than the spec and the
                             labels file, else a fresh build (?rebuild=1 forces one)
  GET  /api/scan?q=&regex=   mentions of a phrase per Pacific date, over all time
  POST /api/trace            an ad-hoc episode from chosen days, optionally stance-labelled

Standard library only, bound to 127.0.0.1. One read-only DuckDB connection is opened on first use;
each request works on its own cursor. A build or scan that is already running is never started
twice: a second identical request waits for the first and shares its result. Scans and live traces
are cached in memory. Every excerpt is redacted with the engine's pattern and label.py's extension
of it before it leaves the server.
"""

import argparse
import hashlib
import json
import re
import signal
import sys
import threading
import time
import traceback
from collections import Counter, OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit
from zoneinfo import ZoneInfo

from . import label, trace

PACIFIC = ZoneInfo("America/Los_Angeles")
LIVE = trace.OUT / "live"  # git-ignored: stance labels of live traces
MIN_QUERY = 3        # characters in a scan phrase or a trace pattern
MAX_PATTERN = 500
MAX_DAYS = 10        # panels in a live trace
MAX_SPAN = 31        # days from the first chosen day to the last, when the pattern has no cached scan
MAX_MEM_MATCHES = 15000  # memory snapshots the pattern matches from the day before the first day to the last
LABEL_CAP = 400      # distinct mentions sent to the labeller per live trace
LABEL_MODEL = "haiku"
EXCERPT = 240        # characters in a scan's first-seen excerpt
TOP_AGENTS = 15
MAX_BODY = 64 * 1024
SCAN_CACHE, TRACE_CACHE = 200, 12  # entries kept in memory


class Fail(Exception):
    """An error the client caused: answered as {"error": message} with this status."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def redact(text):
    """The engine's pattern, then label.py's. label.py's added three token shapes the engine's once
    missed; running both keeps the union if either changes."""
    return label.redact(trace.redact(text or ""))


def redact_episode(data):
    """Run redact() over every excerpt and reason in episode data. Returns how many changed."""
    changed = 0
    for coll in ("chat", "mem", "files"):
        for x in data.get(coll) or []:
            for k in ("text", "reason"):
                if x.get(k):
                    r = redact(x[k])
                    if r != x[k]:
                        x[k] = r
                        changed += 1
    return changed


def literal(q):
    """A phrase as a regex, the way the viewer escapes it: lowercased, metacharacters escaped."""
    return re.sub(r"[.*+?^${}()|[\]\\]", r"\\\g<0>", q.lower())


def excerpt(text, r, n=EXCERPT):
    """At most n characters around the first match, whitespace folded, redacted before cutting so
    a cut never leaves half a secret behind."""
    text = " ".join(redact(text).split())
    if len(text) <= n:
        return text
    m = r.search(text)
    a = max(0, m.start() - 70) if m else 0
    b = min(len(text), a + n)
    a = max(0, b - n)
    lead, tail = a > 0, b < len(text)
    return ("…" if lead else "") + text[a + lead : b - tail].strip() + ("…" if tail else "")


@lru_cache(maxsize=None)
def pacific_date(hour):
    """A UTC hour (naive datetime) -> its Pacific date. Offsets are whole hours, so an hour never
    straddles two dates."""
    return hour.replace(tzinfo=timezone.utc).astimezone(PACIFIC).date().isoformat()


def plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def pt_day(utc):
    """UTC "YYYY-MM-DD HH:MM:SS" -> "Sun 9 Aug", the Pacific date."""
    d = trace.parse(utc).replace(tzinfo=timezone.utc).astimezone(PACIFIC)
    return f"{d:%a} {d.day} {d:%b}"


def pt_label(utc):
    """UTC "YYYY-MM-DD HH:MM:SS" -> "Mon 1 Jun, 10:31 AM PT"."""
    d = trace.parse(utc).replace(tzinfo=timezone.utc).astimezone(PACIFIC)
    return f"{d:%a} {d.day} {d:%b}, {d.hour % 12 or 12}:{d:%M} {'AM' if d.hour < 12 else 'PM'} PT"


class LRU:
    """A small least-recently-used cache, safe to share between request threads."""

    def __init__(self, size):
        self.size, self.items, self.lock = size, OrderedDict(), threading.Lock()

    def put(self, key, value):
        with self.lock:
            self.items[key] = value
            self.items.move_to_end(key)
            while len(self.items) > self.size:
                self.items.popitem(last=False)

    def fetch(self, key):
        with self.lock:
            if key not in self.items:
                return None
            self.items.move_to_end(key)
            return self.items[key]


class Flight:
    """Single flight by key: while one thread computes a key, other callers with the same key wait
    for its result (or its exception) instead of computing it again."""

    def __init__(self):
        self.lock = threading.Lock()
        self.running = {}

    def run(self, key, fn):
        with self.lock:
            job = self.running.get(key)
            owner = job is None
            if owner:
                job = self.running[key] = {"done": threading.Event(), "value": None, "error": None}
        if not owner:
            job["done"].wait()
            if job["error"]:
                raise job["error"]
            return job["value"]
        try:
            job["value"] = fn()
            return job["value"]
        except BaseException as e:
            job["error"] = e
            raise
        finally:
            with self.lock:
                del self.running[key]
            job["done"].set()


class App:
    def __init__(self):
        self.db_lock = threading.Lock()
        self.db = None
        self.flight = Flight()
        self.slug_locks, self.locks_lock = {}, threading.Lock()
        self.label_lock = threading.Lock()  # label.py keeps run state in module globals
        self.scans = LRU(SCAN_CACHE)
        self.traces = LRU(TRACE_CACHE)
        self.served = {}  # slug -> (mtime, bytes) of curated episode files already checked
        self.agent_names = None

    def cursor(self):
        with self.db_lock:
            if self.db is None:
                self.db = trace.connect()
            return self.db.cursor()

    def close(self):
        with self.db_lock:
            if self.db is not None:
                self.db.close()
                self.db = None

    def names(self, cur):
        if self.agent_names is None:
            self.agent_names = dict(cur.execute("SELECT id::VARCHAR, name FROM agents").fetchall())
        return self.agent_names

    # Curated episodes ------------------------------------------------------------------------

    def episodes(self):
        out = []
        for slug in trace.list_specs():
            try:
                spec = trace.load_spec(slug)
            except ValueError as e:
                log(f"episodes: skipped {slug}: {e}")
                continue
            out.append({"slug": slug, "title": spec.get("title") or slug, "headline": spec.get("headline", "")})
        return out

    def slug_lock(self, slug):
        with self.locks_lock:
            return self.slug_locks.setdefault(slug, threading.Lock())

    def episode(self, slug, rebuild=False):
        """JSON bytes of one curated episode. The out file is used while it is newer than the spec
        and the labels file; otherwise, or with rebuild, the episode is built and written. A request
        that waited while another built the same slug uses that build. When a build that was not asked
        for fails (a spec in the middle of an edit, say), the last good build is served instead."""
        if slug.startswith("trace-") and self.traces.fetch(slug):
            return self.traces.fetch(slug)
        if slug not in trace.list_specs():
            raise Fail(404, f"There is no episode called “{slug}”.")
        asked = time.time()
        path = trace.OUT / "episodes" / f"{slug}.json"
        with self.slug_lock(slug):
            sources = [trace.spec_path(slug), trace.TRACER / "labels" / f"{slug}.json"]
            newest = max(p.stat().st_mtime for p in sources if p.exists())
            mtime = path.stat().st_mtime if path.exists() else 0
            if mtime > newest and (not rebuild or mtime >= asked):
                body = self.from_file(slug, path, mtime)
                if body is not None:
                    return body
            try:
                return self.build_curated(slug)
            except Exception as e:
                body = None if rebuild or not mtime else self.from_file(slug, path, mtime)
                if body is None:
                    raise
                traceback.print_exc()
                log(f"episode {slug}: build failed ({type(e).__name__}: {e}); serving the older build")
                return body

    def from_file(self, slug, path, mtime):
        hit = self.served.get(slug)
        if hit and hit[0] == mtime:
            return hit[1]
        raw = path.read_bytes()
        try:
            data = json.loads(raw)
        except ValueError:
            log(f"episode {slug}: {path.name} is not valid JSON, rebuilding")
            return None
        n = redact_episode(data)
        if n:
            log(f"episode {slug}: redacted {n} more excerpts than the engine did")
            raw = dumps(data)
        self.served[slug] = (mtime, raw)
        return raw

    def build_curated(self, slug):
        t0 = time.time()
        cur = self.cursor()
        try:
            info = {}
            data = trace.build_episode(trace.load_spec(slug), cur, info)
        finally:
            cur.close()
        n = redact_episode(data)
        path = trace.write_episode(data)
        body = dumps(data)
        self.served[slug] = (path.stat().st_mtime, body)
        log(f"built {slug} in {time.time() - t0:.1f} s: {len(data['chat'])} chat, {len(data['mem'])} mem, "
            f"{len(data['files'])} files; timings {info.get('timings')}"
            + (f"; redacted {n} more excerpts" if n else "")
            + "".join(f"\n  warning: {w}" for w in info.get("warnings", [])))
        return body

    # Scan ------------------------------------------------------------------------------------

    def scan(self, q, regex):
        q = (q or "").strip()
        if len(q) < MIN_QUERY:
            raise Fail(400, f"Type at least {MIN_QUERY} characters to scan for.")
        pattern = q if regex else literal(q)
        self.check_pattern(pattern, "The pattern")
        t0 = time.time()
        computed = []

        def compute():
            hit = self.scans.fetch(pattern)
            if hit is None:
                hit = self.run_scan(pattern)
                computed.append(True)
            return hit

        hit = self.scans.fetch(pattern) or self.flight.run(("scan", pattern), compute)
        self.scans.put(pattern, hit)
        out = {k: v for k, v in hit.items() if not k.startswith("_")}
        return {"q": q, "regex": bool(regex), **out, "seconds": round(time.time() - t0, 2),
                "computeSeconds": hit["_seconds"], "cached": not computed}

    def check_pattern(self, pattern, what):
        """Python's re and DuckDB's RE2 must both accept it: SQL prefilters, Python decides."""
        if len(pattern) > MAX_PATTERN:
            raise Fail(400, f"{what} is too long ({len(pattern)} characters; the limit is {MAX_PATTERN}).")
        try:
            r = re.compile(pattern, re.I)
        except re.error as e:
            raise Fail(400, f"{what} is not a valid regular expression: {e}.")
        if r.search(""):
            raise Fail(400, f"{what} matches empty text, so it would match everything. Make it more specific.")
        cur = self.cursor()
        try:
            ok = trace.re2(cur, pattern)
        finally:
            cur.close()
        if not ok:
            raise Fail(400, f"{what} uses syntax the database cannot run (DuckDB uses RE2, which has no "
                            "lookarounds or backreferences). Rewrite it without them.")
        return r

    def run_scan(self, pattern):
        """Per Pacific date over all time: chat matches and chat agents, memory matches and memory
        agents, matching turn commands, the first match in each channel and the top agents. SQL
        matches the raw text and groups by UTC hour; only the three first matches are fetched and
        redacted."""
        t0 = time.time()
        lp = trace.lit(pattern)
        queries = {
            "chat": f"""SELECT date_trunc('hour', created_at), speaker_type, speaker, count(*), min(created_at),
                        arg_min(id::VARCHAR, created_at) FROM chat
                        WHERE regexp_matches(content, {lp}, 'i') GROUP BY ALL""",
            "mem": f"""SELECT date_trunc('hour', created_at), 'agent', agent_id::VARCHAR, count(*), min(created_at),
                       arg_min(id::VARCHAR, created_at) FROM agent_memories
                       WHERE regexp_matches(content, {lp}, 'i') GROUP BY ALL""",
            "files": f"""SELECT date_trunc('hour', created_at), 'agent', agent, count(*), min(created_at),
                         arg_min(id::VARCHAR, created_at) FROM turns
                         WHERE regexp_matches(coalesce(command, action_text, ''), {lp}, 'i') GROUP BY ALL""",
        }
        timings = {}

        def query(name):
            q0 = time.time()
            cur = self.cursor()
            try:
                rows = cur.execute(queries[name]).fetchall()
            finally:
                cur.close()
            timings[name] = round(time.time() - q0, 2)
            return rows

        # The memory scan dominates; the other two run beside it on their own cursors.
        with ThreadPoolExecutor(3) as pool:
            results = dict(zip(queries, pool.map(query, queries)))
        cur = self.cursor()
        try:
            names = self.names(cur)
            days, top, first = {}, {"chat": Counter(), "mem": Counter()}, {}
            for channel, rows in results.items():
                for hour, stype, who, n, t_min, first_id in rows:
                    d = days.setdefault(pacific_date(hour), {"chat": 0, "chatAgents": set(), "mem": 0, "memAgents": set(), "files": 0})
                    name = names.get(who, who) if channel == "mem" else who
                    d[channel] += n
                    if stype == "agent" and name and channel != "files":
                        d[channel + "Agents"].add(name)
                        top[channel][name] += n
                    if channel not in first or t_min < first[channel][0]:
                        first[channel] = (t_min, first_id)
            r = re.compile(pattern, re.I)
            found = {"chat": self.first_chat(cur, r, *first["chat"]) if "chat" in first else None,
                     "mem": self.first_mem(cur, r, names, *first["mem"]) if "mem" in first else None,
                     "file": self.first_file(cur, r, *first["files"]) if "files" in first else None}
        finally:
            cur.close()
        out_days = [{"date": k, "chat": v["chat"], "chatAgents": len(v["chatAgents"]), "mem": v["mem"],
                     "memAgents": len(v["memAgents"]), "files": v["files"]} for k, v in sorted(days.items())]
        agents = set(top["chat"]) | set(top["mem"])
        ranked = sorted(agents, key=lambda a: (-(top["chat"][a] + top["mem"][a]), a))[:TOP_AGENTS]
        seconds = round(time.time() - t0, 2)
        log(f"scan {pattern!r}: {len(out_days)} days in {seconds} s {timings}")
        return {
            "pattern": pattern,
            "days": out_days,
            "first": found,
            "topAgents": [{"name": a, "chat": top["chat"][a], "mem": top["mem"][a]} for a in ranked],
            "totals": {k: sum(d[k] for d in out_days) for k in ("chat", "mem", "files")},
            "timings": timings,
            "_seconds": seconds,
        }

    def first_chat(self, cur, r, t, mid):
        row = cur.execute(f"""SELECT created_at, speaker_type, speaker, coalesce(room, 'general'), id::VARCHAR,
                              coalesce(content, '') FROM chat WHERE created_at = {trace.lit(t)} AND id::VARCHAR = {trace.lit(mid)}""").fetchone()
        if not row:
            return None
        t, stype, speaker, room, mid, content = row
        name = f"Staff (human) · #{room}" if stype == "user" else speaker
        return {"t": trace.ms(t), "a": name, "id": mid, "room": room, "text": excerpt(content, r)}

    def first_mem(self, cur, r, names, t, mid):
        row = cur.execute(f"""SELECT created_at, agent_id::VARCHAR, id::VARCHAR, coalesce(content, '') FROM agent_memories
                              WHERE created_at = {trace.lit(t)} AND id::VARCHAR = {trace.lit(mid)}""").fetchone()
        if not row:
            return None
        t, aid, mid, content = row
        return {"t": trace.ms(t), "a": names.get(aid, aid), "id": mid, "text": excerpt(content, r)}

    def first_file(self, cur, r, t, tid):
        row = cur.execute(f"""SELECT created_at, agent, id::VARCHAR, coalesce(command, action_text, '') FROM turns
                              WHERE created_at = {trace.lit(t)} AND id::VARCHAR = {trace.lit(tid)}""").fetchone()
        if not row:
            return None
        t, agent, tid, cmd = row
        return {"t": trace.ms(t), "a": agent, "id": tid, "text": excerpt(cmd, r)}

    # Live traces -----------------------------------------------------------------------------

    def trace(self, body):
        claim, correction, days, do_label = self.check_trace(body)
        self.guard(claim, days)
        key = json.dumps([claim, correction, days, do_label], sort_keys=True)
        slug = "trace-" + hashlib.sha1(key.encode()).hexdigest()[:10]
        hit = self.traces.fetch(slug)
        if hit is not None:
            return hit
        body = self.flight.run(("trace", slug), lambda: self.traces.fetch(slug) or
                               self.build_trace(slug, claim, correction, days, do_label))
        self.traces.put(slug, body)
        return body

    def check_trace(self, body):
        if not isinstance(body, dict):
            raise Fail(400, "The request body must be a JSON object.")
        claim = body.get("claim")
        if not isinstance(claim, dict) or not isinstance(claim.get("pattern"), str) or not claim["pattern"].strip():
            raise Fail(400, "The claim needs a pattern.")
        claim = {"label": str(claim.get("label") or claim["pattern"]).strip()[:200], "pattern": claim["pattern"]}
        if len(claim["pattern"]) < MIN_QUERY:
            raise Fail(400, f"The claim pattern needs at least {MIN_QUERY} characters.")
        self.check_pattern(claim["pattern"], "The claim pattern")

        correction = body.get("correction")
        if correction is not None:
            if not isinstance(correction, dict):
                raise Fail(400, "The correction must be an object with a label, a pattern and a time, or null.")
            p, at = correction.get("pattern"), correction.get("at")
            if not isinstance(p, str) or len(p.strip()) < MIN_QUERY:
                raise Fail(400, f"The correction needs a pattern of at least {MIN_QUERY} characters.")
            if not isinstance(at, str) or not at.strip():
                raise Fail(400, "The correction needs a time: \"at\", in UTC as YYYY-MM-DD HH:MM:SS.")
            try:
                t = datetime.fromisoformat(at.strip())
            except ValueError:
                raise Fail(400, f"The correction time “{at}” is not a date and time. Use UTC as YYYY-MM-DD HH:MM:SS.")
            if t.tzinfo is not None:
                t = t.astimezone(timezone.utc).replace(tzinfo=None)
            self.check_pattern(p, "The correction pattern")
            correction = {"label": str(correction.get("label") or p).strip()[:200], "pattern": p,
                          "at": t.strftime("%Y-%m-%d %H:%M:%S")}

        days = body.get("days")
        if not isinstance(days, list) or not days:
            raise Fail(400, "Pick at least one day: \"days\" is a list of dates (YYYY-MM-DD).")
        parsed = set()
        for d in days:
            try:
                if not isinstance(d, str) or not re.fullmatch(r"\d{4}-\d\d-\d\d", d):
                    raise ValueError
                parsed.add(date.fromisoformat(d))
            except ValueError:
                raise Fail(400, f"“{d}” is not a date. Days are YYYY-MM-DD.")
        if len(parsed) > MAX_DAYS:
            raise Fail(400, f"Pick at most {MAX_DAYS} days ({len(parsed)} were picked). Each day becomes a panel, "
                            "and more make a slow, cramped chart.")
        do_label = body.get("label", False)
        if not isinstance(do_label, bool):
            raise Fail(400, "\"label\" must be true or false.")
        return claim, correction, sorted(d.isoformat() for d in parsed), do_label

    def guard(self, claim, days):
        """Refuse builds that would take minutes. A build costs about 3-4 ms per memory snapshot the
        pattern matches from the day before the first day to the end of the last, on a busy machine:
        "github" took 8 s for one day, 35 s for two days 10 apart (about 6,500 matches) and 51 s for
        two days 31 apart (13,780), while a rare phrase took 9 s for two days 171 apart. With a cached
        scan of the pattern (the viewer always scans first) the guard counts those snapshots; without
        one it limits the span."""
        first, last = date.fromisoformat(days[0]), date.fromisoformat(days[-1])
        day = lambda d: f"{d:%a} {d.day} {d:%b} {d.year}"
        scan = self.scans.fetch(claim["pattern"])
        if scan is None:
            span = (last - first).days + 1
            if span > MAX_SPAN:
                raise Fail(400, f"The days picked span {span} days, from {day(first)} to {day(last)}. Scan the phrase "
                                f"first, or keep the days within {MAX_SPAN} days: a trace reads every memory snapshot "
                                "from the day before the first day to the end of the last, and a common phrase over a "
                                "wider span takes minutes to build.")
            return
        lo = first - timedelta(days=1)
        n = sum(d["mem"] for d in scan["days"] if lo.isoformat() <= d["date"] <= last.isoformat())
        if n > MAX_MEM_MATCHES:
            raise Fail(400, f"“{claim['label']}” is in {n:,} memory snapshots from {day(lo)} to {day(last)}. A trace "
                            f"that size takes minutes to build (the limit is {MAX_MEM_MATCHES:,}). Pick days closer "
                            "together, or a more specific phrase.")

    def build_trace(self, slug, claim, correction, days, do_label):
        t0 = time.time()
        cur = self.cursor()
        try:
            try:
                spec = trace.live_spec(claim, correction, days, cur)
            except ValueError as e:  # no chat on any of the days
                raise Fail(400, f"Nothing to trace: {e}. Pick days when the village was running.")
            shown = [p["id"] for p in spec["panels"]]
            warnings = []
            if len(shown) < len(days):
                warnings.append("Days with no chat were left out: " + ", ".join(d for d in days if d not in shown) + ".")
            if correction and not spec["panels"][0]["start"] <= correction["at"] <= spec["panels"][-1]["end"]:
                warnings.append(f"The correction time, {pt_label(correction['at'])}, falls outside the chosen days.")
            spec.update(slug=slug, title=f"Trace: {claim['label']}")
            labelling = self.label_trace(spec, cur, slug, warnings) if do_label else None
            info = {}
            data = trace.build_episode(spec, cur, info)
        finally:
            cur.close()
        data["slug"] = slug  # a labelled build passes the labels file's path as its slug
        if labelling:
            if data.get("labelStats"):
                data["labelStats"].update(costUsd=labelling["costUsd"], calls=labelling["calls"],
                                          distinct=labelling["distinct"], sent=labelling["sent"])
            else:
                warnings.append("The engine did not apply the stance labels; the trace shows keyword matches only.")
        warnings += info.get("warnings", [])
        n = redact_episode(data)
        seconds = round(time.time() - t0, 1)
        data["lede"] = self.lede(data, spec, correction, bool(data.get("labelStats")))
        data["notes"] = self.notes(data, claim, correction, labelling, warnings)
        data["build"] = {"seconds": seconds, "timings": info.get("timings"), "warnings": warnings,
                         "days": days, "shown": shown, "pattern": claim["pattern"],
                         "correctionPattern": (correction or {}).get("pattern")}
        log(f"trace {slug} {claim['pattern']!r} {days}: {seconds} s, {len(data['chat'])} chat, {len(data['mem'])} mem, "
            f"{len(data['files'])} files, {len(data['links'])} links; timings {info.get('timings')}"
            + (f"; redacted {n} more excerpts" if n else "") + "".join(f"\n  warning: {w}" for w in warnings))
        return dumps(data)

    def label_trace(self, spec, cur, slug, warnings):
        """Stance labels for a live trace, merged the way the engine merges curated labels: the
        labels go to a labels file (under the git-ignored tracer/out/live/) and the build reads it.
        label.collect_items picks the claim matches the curated labeller would; at most LABEL_CAP
        distinct ones are sent, chat first, then memory in time order."""
        corr = spec.get("correction") or {}
        items = label.collect_items(spec, cur)
        cms = trace.ms(corr["at"]) if corr.get("at") else None
        reps, same = label.dedupe(items, cms)
        reps.sort(key=lambda x: (label.item_type(x) != "chat", label.t_ms(x)))
        kept = reps[:LABEL_CAP]
        if len(reps) > LABEL_CAP:
            warnings.append(f"Stance labels cover the first {LABEL_CAP} of {len(reps)} distinct mentions (chat first, "
                            "then memory in time order). The rest keep their keyword tags.")
        keep_ids = {i for x in kept for i in same[x["id"]]}
        todo = [x for x in items if x["id"] in keep_ids]
        stats, got = {}, {}
        with self.label_lock:
            try:
                got = label.label_items(todo, spec["claim"]["label"], corr.get("label"), model=LABEL_MODEL,
                                        correction_at=corr.get("at"), on_batch=got.update, stats=stats)
            except Exception as e:  # a usage limit, or no claude CLI: keep what came back
                traceback.print_exc()
                warnings.append(f"Stance labelling stopped early ({type(e).__name__}: {e}). Items it did not reach "
                                "keep their keyword tags.")
        if stats.get("failed"):
            warnings.append(f"The labeller gave no stance for {len(stats['failed'])} items; they keep their keyword tags.")
        by_id = {x["id"]: x for x in items}
        store = {"slug": slug, "claim": spec["claim"]["label"], "correction": corr.get("label"),
                 "model": LABEL_MODEL, "checkModel": None, "agreement": None, "n": len(got),
                 "costUsd": round(stats.get("cost_usd", 0.0), 4),
                 "items": {i: {"type": label.item_type(by_id[i]), "a": by_id[i]["a"], "t": label.utc(by_id[i]["t"]),
                               "stance": lab["stance"], "reason": lab["reason"], "check": None, "checkReason": None}
                           for i, lab in got.items() if i in by_id}}
        path = LIVE / "labels" / f"{slug}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(store, ensure_ascii=False))
        # The engine reads tracer/labels/<slug>.json; this relative slug points it at the file above.
        spec.update(slug=f"../out/live/labels/{slug}", labels=True)
        log(f"labelled {slug}: {len(got)} of {len(todo)} items ({len(kept)} distinct sent of {len(reps)}), "
            f"{stats.get('calls', 0)} calls, ${stats.get('cost_usd', 0.0):.4f}")
        return {"costUsd": store["costUsd"], "calls": stats.get("calls", 0), "distinct": len(reps), "sent": len(kept)}

    def lede(self, data, spec, correction, labelled):
        s = data["stats"]
        chat, mem = plural(s["claim_chat_agents"], "agent"), s["claim_mem_agents"]
        text = "Before the correction, " if correction else ""
        if labelled:
            text += f"{chat} stated it as fact in chat and {mem} held it as fact in memory, by the stance labels."
        else:
            text += f"{chat} mentioned it in chat and {mem} had it in memory."
        text = text[0].upper() + text[1:]
        if correction:
            text += f" {plural(s['fix_mem_agents'], 'agent')} took up the correction in memory."
        text += (f" Chat comes from the chosen days, memory from {pt_day(spec['memory_lookback'])} to "
                 f"{pt_day(spec['panels'][-1]['end'])}.")
        if not labelled:
            text += " These are keyword matches: a mention counts whether or not its author believed it."
        return text

    def notes(self, data, claim, correction, labelling, warnings):
        days = ", ".join(p["label"] for p in data["panels"])
        how = [
            f"This trace was built on request for “{claim['label']}”. Each chosen day is one panel ({days}), from "
            "that day’s first chat message to its last, rounded out to the hour.",
            "Each lane is one agent. Inside a lane, diamonds on top are file reads and writes, dots in the middle are "
            "chat messages, and the bar along the bottom is what the agent’s memory held. Hover over the bar to read "
            "the snapshot from that moment.",
            "Agents only see chat from their own room. The hatched band between rooms is that wall. Turn channels off "
            "with the checkboxes to see what a chat-only monitor would miss.",
        ]
        method = [f"One pattern finds the claim in chat, memory and file commands: {claim['pattern']} (Python regular "
                  "expression, case ignored). A match is tagged as holding the claim."]
        if correction:
            method.append(f"Correction: {correction['pattern']}, from {pt_label(correction['at'])}. After that time a "
                          "match of the correction is tagged as the correction. Memory snapshots and file commands that "
                          "still match the claim keep the claim tag. Chat messages that only match the claim are drawn "
                          "untagged.")
        method += [
            "Memory is read from the day before the first panel, so the state each agent carries into a panel shows.",
            "File hand-offs between rooms are found automatically: a write to a repository, a read of it from "
            "another room within 90 minutes, and the reader’s next memory snapshot or chat message.",
        ]
        if labelling:
            method.append(f"The stance labeller ({LABEL_MODEL}, through the claude CLI) read "
                          f"{plural(labelling['sent'], 'distinct mention')} in {plural(labelling['calls'], 'call')}, for "
                          f"${labelling['costUsd']:.2f}. Adopts keeps the claim tag. Attributes and refutes change it. "
                          "Unclear keeps the keyword tag.")
        else:
            method.append("No stance labels: build again with labels on to sort belief from mention.")
        limits = []
        if not labelling:
            limits.append("Keyword matching cannot tell belief from mention. A message that quotes the claim to reject "
                          "it is tagged as holding it.")
        limits += [
            "Nobody has checked this trace by hand. It has no walkthrough, and every count comes from the pattern.",
            "Only the chosen days are drawn. Between them, memory shows only what each agent carried in.",
            "Messages and memories are what agents said. Check them against the file commands where it matters.",
        ]
        limits += warnings
        return {"how": how, "method": method, "limits": limits}


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


def log(msg):
    sys.stderr.write(f"[{datetime.now():%H:%M:%S}] {msg}\n")
    sys.stderr.flush()


def page():
    """The viewer is body-level (the artifact host wraps it); a doctype skeleton makes it a page."""
    tpl = (trace.TRACER / "template.html").read_text()
    if trace.MARKER not in tpl:
        raise ValueError(f"tracer/template.html has no {trace.MARKER} marker")
    return ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n</head>\n<body>\n'
            + tpl.replace(trace.MARKER, json.dumps({"mode": "live"})) + "\n</body>\n</html>\n").encode("utf-8")


# HTTP -------------------------------------------------------------------------------------------

JSON_TYPE = "application/json; charset=utf-8"


class Handler(BaseHTTPRequestHandler):
    server_version = "BeliefTracer/1"
    app = None  # set in main()

    def do_GET(self):
        self.answer("GET")

    def do_POST(self):
        self.answer("POST")

    def answer(self, method):
        t0 = time.time()
        url = urlsplit(self.path)
        try:
            status, body, ctype = self.route(method, url.path, parse_qs(url.query))
        except Fail as e:
            status, body, ctype = e.status, dumps({"error": str(e)}), JSON_TYPE
        except Exception as e:
            traceback.print_exc()
            status, body, ctype = 500, dumps({"error": f"The server failed: {type(e).__name__}: {e}"}), JSON_TYPE
        try:
            self.send_response(status)
            if body:
                self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            status = f"{status} (client gone)"
        log(f'{self.address_string()} "{method} {self.path}" {status} {len(body)} B {time.time() - t0:.2f} s')

    def route(self, method, path, query):
        app = self.app
        if path in ("/", "/index.html"):
            self.allow(method, "GET")
            return 200, page(), "text/html; charset=utf-8"
        if path == "/favicon.ico":
            return 204, b"", None
        if path == "/api/episodes":
            self.allow(method, "GET")
            return 200, dumps(app.episodes()), JSON_TYPE
        if path.startswith("/api/episode/"):
            self.allow(method, "GET")
            slug = unquote(path[len("/api/episode/"):])
            if not re.fullmatch(r"[\w.-]+", slug) or slug.startswith("."):
                raise Fail(404, f"There is no episode called “{slug}”.")
            return 200, app.episode(slug, rebuild=query.get("rebuild", ["0"])[0] not in ("", "0", "false")), JSON_TYPE
        if path == "/api/scan":
            self.allow(method, "GET")
            q = query.get("q", [""])[0]
            return 200, dumps(app.scan(q, query.get("regex", ["0"])[0] not in ("", "0", "false"))), JSON_TYPE
        if path == "/api/trace":
            self.allow(method, "POST")
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise Fail(413, "The request body is too large.")
            try:
                body = json.loads(self.rfile.read(n) or b"null")
            except ValueError:
                raise Fail(400, "The request body is not valid JSON.")
            return 200, app.trace(body), JSON_TYPE
        raise Fail(404, f"Nothing is served at {path}.")

    def allow(self, method, want):
        if method != want:
            raise Fail(405, f"Use {want} for this address.")

    def log_request(self, code="-", size="-"):
        pass  # answer() logs each request once, with its time

    def log_message(self, fmt, *args):
        log(f"{self.address_string()} {fmt % args}")


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    ap = argparse.ArgumentParser(description="Serve the Belief Tracer viewer in live mode on 127.0.0.1.")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    Handler.app = app = App()
    srv = Server(("127.0.0.1", args.port), Handler)

    def stop(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    log(f"Belief Tracer at http://127.0.0.1:{args.port}/ (Ctrl-C stops it)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        app.close()
        log("stopped")


if __name__ == "__main__":
    main()
