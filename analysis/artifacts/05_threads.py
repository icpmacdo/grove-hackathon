"""Issue / MR / PR comment threads as message boards. Thread = (repo, kind, number).
Posts: gh issue|pr comment N, glab issue|mr note N, gh|glab api .../issues|merge_requests|pulls/N/(comments|notes) with a write
method/field, curl POST to the same. Reads: the same endpoints without write flags, gh issue|pr view N --comments, glab issue view N.
Repo is resolved from URL/--repo/-R/projects/<id|path> (via 01's normaliser), else cwd mapping from artifact_events.
Outputs: out/thread_events.parquet, out/threads_summary.csv; prints thread traffic vs agent chat per month.
"""
import os, re, importlib.util
import pandas as pd, duckdb

HERE = os.path.dirname(__file__); OUT = os.path.join(HERE, 'out')
con = duckdb.connect('/Users/ianmacdonald/code/grove-hackathon/data/village.duckdb', read_only=True)
con.execute("SET memory_limit='2GB'; SET threads=2;")
ev = pd.read_parquet(f'{OUT}/artifact_events.parquet')[['turn_id', 'artifact', 'op']]
art_of = ev.groupby('turn_id').artifact.first()

rows = con.execute(r"""
  select id turn_id, created_at, agent, command from turns where command is not null and regexp_matches(command,
   '((gh|glab) +(issue|pr|mr) +(comment|note|view)|/(issues|merge_requests|pulls)/[0-9]+/(comments|notes)|(gh|glab) +(issue|pr|mr) +view)')
""").df()
print('candidate rows', len(rows))
WRITE = re.compile(r'-X *(POST|PUT|PATCH)|--method[ =]*(POST|PUT|PATCH)|--request *(POST|PUT|PATCH)| -f | -F | --field| --raw-field| --data| -d |--input', re.I)
RX = [
    (re.compile(r'\b(gh|glab) +(issue|pr|mr) +(comment|note)\s+(\d+)'), 'post'),
    (re.compile(r'\b(gh|glab) +(issue|pr|mr) +view\s+(\d+)'), 'view'),
    (re.compile(r'/(issues|merge_requests|pulls)/(\d+)/(comments|notes)'), 'api'),
]
REPO = re.compile(r'(?:--repo|-R)[ =]+([A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+)')
recs = []
for r in rows.itertuples(index=False):
    for seg in re.split(r'&&|;|\n|\|\|', r.command):
        for rx, kind in RX:
            for m in rx.finditer(seg):
                if kind == 'post': op, tk, num = 'post', m.group(2), m.group(4)
                elif kind == 'view': op, tk, num = 'read', m.group(2), m.group(3)
                else:
                    tk, num = m.group(1), m.group(2)
                    op = 'post' if WRITE.search(seg) and not re.search(r'per_page|\?sort', seg[m.end():m.end() + 3]) else 'read'
                tk = {'merge_requests': 'mr', 'pulls': 'pr', 'issues': 'issue'}.get(tk, tk)
                rp = REPO.search(seg)
                pm = re.search(r'projects/([0-9]{8,9}|[A-Za-z0-9_.%-]+%2F[A-Za-z0-9_.%-]+)', seg)
                gm = re.search(r'github\.com/repos/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)|repos/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/(?:issues|pulls)', seg)
                repo = (rp.group(1).lower() if rp else pm.group(1).lower() if pm else (gm.group(1) or gm.group(2)).lower() if gm
                        else art_of.get(r.turn_id, 'cwd?'))
                recs.append((r.turn_id, r.created_at, r.agent, op, repo, tk, int(num)))
te = pd.DataFrame(recs, columns=['turn_id', 'created_at', 'agent', 'op', 'repo', 'kind', 'num']).drop_duplicates(['turn_id', 'repo', 'kind', 'num', 'op'])
te.to_parquet(f'{OUT}/thread_events.parquet', index=False)
print(te.groupby('op').size().to_string())

th = te.groupby(['repo', 'kind', 'num']).agg(posts=('op', lambda s: (s == 'post').sum()), reads=('op', lambda s: (s == 'read').sum()),
                                          posters=('agent', lambda s: s[te.loc[s.index, 'op'] == 'post'].nunique()),
                                          agents=('agent', 'nunique'), t0=('created_at', 'min'), t1=('created_at', 'max')).reset_index()
th.to_csv(f'{OUT}/threads_summary.csv', index=False)
multi = th[th.posters >= 2]
print(f'threads: {len(th)}; with >=2 agent posters: {len(multi)} (posts {multi.posts.sum()} of {th.posts.sum()})')
print(th.sort_values('posts', ascending=False).head(15).to_string())
print(multi.sort_values('posters', ascending=False).head(15).to_string())

chat = con.execute("select date_trunc('month', created_at) m, count(*) chat_msgs from chat where speaker_type='agent' group by 1").df().set_index('m')
mo = te.assign(m=te.created_at.dt.to_period('M').dt.to_timestamp()).pivot_table(index='m', columns='op', values='turn_id', aggfunc='count', fill_value=0)
mo = mo.join(chat); mo['posts_per_100_chat'] = (100 * mo.post / mo.chat_msgs).round(2)
print(mo[mo.index >= '2025-10-01'].to_string())
