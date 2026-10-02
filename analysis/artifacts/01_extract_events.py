"""Extract agent <-> artifact read/write events from `turns` (bash commands + typed browser URLs).

Output: out/artifact_events.parquet with one row per (turn, artifact, op):
  turn_id, created_at, agent, op ('write'|'read'), verb (push, clone, pull, gh-issue-comment, curl-get, browser, ...),
  artifact (normalised id, e.g. gh:ai-village-agents/village or gl:ai-village-agents/village/ai-village-news),
  resolved_by ('url'|'remote'|'cwd'|'pages')

Heuristics (documented so blind spots are explicit):
  * git push: repo from 'To <remote>' in stderr/stdout, else URL in command, else `cd <dir>` basename mapped to a repo
    this agent (or anyone) previously pushed from that dir.
  * git pull/fetch: 'From <remote>' else cwd mapping. git clone / gh repo clone / glab repo clone: URL/arg in command.
  * gh/glab issue|pr|mr create/comment/note/merge/edit/close/review, repo create, release create, gist create,
    api with -X/--method POST|PUT|PATCH|DELETE or -f/-F/--field/--raw-field/--input => write; other gh/glab => read.
  * curl/wget: -X POST/PUT/PATCH, -d/--data*, -F/--form, -T => write; else read (only github/gitlab/pages hosts).
  * typed text in the browser (action_type='type') that is a bare URL => read (browser).
Blind spots: local `cat` of an already-pulled clone; GUI clicks inside github.com; Python/requests scripts that hit
APIs from files; commands piped through variables ($REPO).
"""
import os, re, urllib.parse
import duckdb, pandas as pd

OUT = os.path.join(os.path.dirname(__file__), 'out'); os.makedirs(OUT, exist_ok=True)
con = duckdb.connect('/Users/ianmacdonald/code/grove-hackathon/data/village.duckdb', read_only=True)
con.execute("SET memory_limit='2GB'; SET threads=2;")

PAT = r"(git (push|pull|fetch|clone)|(^|[;&|\n(` ]) *(gh|glab) |curl |wget |github\.com|gitlab\.com|github\.io|gitlab\.io|githubusercontent)"
rows = con.execute(f"""
  select id turn_id, created_at, agent, command,
         left(coalesce(error,''),1200) || ' || ' || left(coalesce(output,''),600) || ' || ' || right(coalesce(output,''),400) io
  from turns where command is not null and regexp_matches(command, '{PAT}')
""").df()
print('bash rows', len(rows))
typed = con.execute(r"""
  select id turn_id, created_at, agent, trim(action_text) url from turns
  where action_type='type' and regexp_matches(trim(action_text), '^(https?://)?[A-Za-z0-9.-]+\.(github\.io|gitlab\.io|github\.com|gitlab\.com)(/\S*)?$')
""").df()
print('typed url rows', len(typed))

ROUTE = {'-', 'blob', 'raw', 'tree', 'issues', 'merge_requests', 'pulls', 'pull', 'commits', 'commit', 'actions',
         'releases', 'wiki', 'pipelines', 'jobs', 'edit', 'compare', 'settings', 'archive', 'tags', 'branches', 'files'}

def norm_gl_path(path):
    segs = [s for s in path.split('/') if s]
    out = []
    for s in segs:
        if s in ROUTE: break
        out.append(s)
        if len(out) == 3 or (len(out) == 2 and out[0].lower() != 'ai-village-agents'): break
        if len(out) == 2 and out[1].lower() != 'village': break
    if len(out) < 2: return None
    return 'gl:' + '/'.join(out).lower().removesuffix('.git')

def norm_gh(owner, repo):
    repo = repo.removesuffix('.git')
    if not re.match(r'^[A-Za-z0-9_.-]+$', repo) or owner.lower() in ('repos', 'orgs', 'users', 'search', 'api'): return None
    return f'gh:{owner.lower()}/{repo.lower()}'

RX = [
    (re.compile(r'raw\.githubusercontent\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)'), 'gh'),
    (re.compile(r'api\.github\.com/repos/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)'), 'gh'),
    (re.compile(r'(?<![.\w])github\.com[/:]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)'), 'gh'),
    (re.compile(r'([A-Za-z0-9-]+)\.github\.io/([A-Za-z0-9_.-]+)'), 'ghpages'),
    (re.compile(r'(?<![.\w])gitlab\.com[/:]((?:[A-Za-z0-9_.-]+/){1,4}[A-Za-z0-9_.-]+)'), 'gl'),
    (re.compile(r'gitlab\.com/api/v4/projects/([A-Za-z0-9_.%-]+)'), 'glapi'),
    (re.compile(r'(?<![\w-])projects/(8[0-9]{7})(?![0-9])'), 'glid'),
    (re.compile(r'(?<![\w.-])([a-z0-9-]+?)-[0-9a-f]{6}\.gitlab\.io'), 'glpages'),
    (re.compile(r'ai-village-agents\.gitlab\.io/([A-Za-z0-9_.-]+)(?:/([A-Za-z0-9_.-]+))?'), 'glorgpages'),
]

def artifacts_in(text, glid_map):
    found = []
    for rx, kind in RX:
        for m in rx.finditer(text):
            a = None
            if kind == 'gh': a = norm_gh(m.group(1), m.group(2))
            elif kind == 'ghpages':
                a = norm_gh(m.group(1), m.group(2)) if m.group(2) not in ('', 'index.html') else None
            elif kind == 'gl':
                if m.group(1).startswith('api/'): continue
                a = norm_gl_path(m.group(1))
            elif kind == 'glapi':
                p = urllib.parse.unquote(m.group(1))
                a = norm_gl_path(p) if '/' in p else (('gl:' + glid_map[p]) if p in glid_map else f'gl:id:{p}')
            elif kind == 'glid':
                p = m.group(1); a = ('gl:' + glid_map[p]) if p in glid_map else f'gl:id:{p}'
            elif kind == 'glpages': a = f'gl:ai-village-agents/village/{m.group(1).lower()}'
            elif kind == 'glorgpages':
                a = (f'gl:ai-village-agents/village/{m.group(2).lower()}' if m.group(1) == 'village' and m.group(2)
                     else f'gl:ai-village-agents/village/{m.group(1).lower()}')
            if a: found.append((a, kind))
    return found

# GitLab numeric project id -> path, from JSON in outputs
glid_map = {}
for pid, path in con.execute(r"""
  with x as (select unnest(regexp_extract_all(output, '"id":\s*(\d{8,9}),\s*"description":.{0,1000}?"path_with_namespace":\s*"([^"]+)"', 0)) s
             from turns where output like '%path_with_namespace%' and output like '%gitlab%')
  select regexp_extract(s, '"id":\s*(\d+)', 1), lower(regexp_extract(s, '"path_with_namespace":\s*"([^"]+)"', 1)) from x""").fetchall():
    glid_map.setdefault(pid, path)
print('gitlab id map', len(glid_map))

WRITE_GHGL = re.compile(r'\b(gh|glab) +(issue|pr|mr) +(create|comment|note|merge|edit|close|reopen|review|update)\b|'
                        r'\b(gh|glab) +(repo|release|gist|label|snippet) +(create|edit|delete|upload|archive)\b|'
                        r'\b(gh|glab) +api\b[^\n|;&]*(-X *(POST|PUT|PATCH|DELETE)|--method[ =]*(POST|PUT|PATCH|DELETE)|'
                        r' -f | -F | --field| --raw-field| --input)', re.I)
CURL_WRITE = re.compile(r'\b(curl|wget)\b[^\n|;&]*(-X *(POST|PUT|PATCH|DELETE)|--request *(POST|PUT|PATCH|DELETE)|'
                        r' -d | --data| -F | --form| -T |--upload-file|--post-data)', re.I)
CD = re.compile(r'\bcd +([^\s;&|]+)')

def verbs_of(cmd):
    v = []
    if re.search(r'\bgit +(-C +\S+ +)?push\b', cmd): v.append(('write', 'git-push'))
    if re.search(r'\bgit +(-C +\S+ +)?(pull|fetch)\b', cmd): v.append(('read', 'git-pull'))
    if re.search(r'\b(git +clone|gh +repo +clone|glab +repo +clone)\b', cmd): v.append(('read', 'clone'))
    m = WRITE_GHGL.search(cmd)
    if m: v.append(('write', 'ghgl-' + ' '.join(x for x in m.groups()[:3] if x) if m.group(1) else 'ghgl-write'))
    elif re.search(r'(^|[;&|\n(` ]) *(gh|glab) +(issue|pr|mr|api|repo|run|ci|pipeline|release|search|browse)', cmd):
        v.append(('read', 'ghgl-read'))
    if re.search(r'\b(curl|wget)\b', cmd):
        v.append(('write', 'curl-write') if CURL_WRITE.search(cmd) else ('read', 'curl-get'))
    return v

recs = []
pushed_dir = {}   # (agent, dirbase) -> artifact ; ('*', dirbase) -> artifact
rows = rows.sort_values('created_at')
for r in rows.itertuples(index=False):
    cmd, io = r.command, r.io or ''
    vs = verbs_of(cmd)
    if not vs: continue
    in_cmd = artifacts_in(cmd, glid_map)
    to = re.findall(r'\bTo (?:https://|git@)([^\s]+)', io)
    frm = re.findall(r'\bFrom (?:https://|git@)([^\s]+)', io)
    cds = CD.findall(cmd); dirb = os.path.basename(cds[-1].rstrip('/')) if cds else None
    for op, verb in vs:
        arts = []
        if verb == 'git-push':
            arts = [(a, 'remote') for a, _ in artifacts_in(' '.join('https://' + t.replace(':', '/', 1) if t.startswith('git') and ':' in t else 'https://' + t for t in to), glid_map)]
            if arts and dirb:
                for a, _ in arts[:1]:
                    pushed_dir[(r.agent, dirb)] = a; pushed_dir[('*', dirb)] = a
        elif verb == 'git-pull':
            arts = [(a, 'remote') for a, _ in artifacts_in(' '.join('https://' + t for t in frm), glid_map)]
        if not arts:
            arts = [(a, 'url' if k not in ('ghpages', 'glpages', 'glorgpages') else 'pages') for a, k in in_cmd]
        if not arts and dirb and verb in ('git-push', 'git-pull', 'ghgl-read') or (not arts and verb.startswith('ghgl-') and dirb):
            a = pushed_dir.get((r.agent, dirb)) or pushed_dir.get(('*', dirb))
            if a: arts = [(a, 'cwd')]
        if not arts and verb in ('git-push', 'git-pull'):
            arts = [('unknown', 'none')]
        for a, how in dict.fromkeys(arts):
            recs.append((r.turn_id, r.created_at, r.agent, op, verb, a, how))

for r in typed.itertuples(index=False):
    for a, k in artifacts_in(r.url if r.url.startswith('http') else 'https://' + r.url, glid_map):
        recs.append((r.turn_id, r.created_at, r.agent, 'read', 'browser', a, 'pages' if 'pages' in k else 'url'))

ev = pd.DataFrame(recs, columns=['turn_id', 'created_at', 'agent', 'op', 'verb', 'artifact', 'resolved_by'])
ev = ev.drop_duplicates(['turn_id', 'artifact', 'op'])
ev.to_parquet(f'{OUT}/artifact_events.parquet', index=False)
print(len(ev), 'events'); print(ev.groupby(['op', 'verb']).size().sort_values(ascending=False).head(30).to_string())
print(ev.resolved_by.value_counts().to_string())
