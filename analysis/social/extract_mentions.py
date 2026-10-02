"""Extract a directed mention graph from `chat`.

Output: analysis/social/out/messages.parquet  (one row per chat message, with human display names)
        analysis/social/out/mention_edges.parquet (one row per (message, mentioned party))

Edge kinds:
  at    -> explicit "@Name" mention of a known agent (full name, or name without "Claude " prefix)
  plain -> the full agent name appears without "@" (weaker: could be third-person reference)
  human -> mention of a known staff human (adam, zak, shoshannah, larissa, george) by name
Run: uv run python analysis/social/extract_mentions.py
"""
import re, os
import duckdb, pandas as pd

OUT = os.path.join(os.path.dirname(__file__), 'out')
os.makedirs(OUT, exist_ok=True)
con = duckdb.connect('/Users/ianmacdonald/code/grove-hackathon/data/village.duckdb', read_only=True)
con.execute("SET memory_limit='2GB'; SET threads=2;")

agents = con.execute("select name from agents").df()['name'].tolist()
# aliases -> canonical
alias = {}
for n in agents:
    alias[n] = n
    if n.startswith('Claude ') and n not in ('Claude Code',):
        short = n[len('Claude '):]
        alias.setdefault(short, n)
alias['Fine-tuned Leader'] = 'Fine-Tuned Leader'
alias['Fine-Tuned Leader'] = 'Fine-Tuned Leader'
alias['[Temporary] Fine-tuned Leader'] = '[Temporary] Fine-tuned Leader'
alias['Opus 4.5 (Claude Code)'] = 'Opus 4.5 (Claude Code)'
names_sorted = sorted(alias, key=len, reverse=True)
name_re = '|'.join(re.escape(a) for a in names_sorted)
# a name must not be followed by more version chars (GPT-5 vs GPT-5.1) or word chars
AT_RE = re.compile(r'@(' + name_re + r')(?![\w]|\.\d)', re.I)
PLAIN_RE = re.compile(r'(?<![@\w])(' + name_re + r')(?![\w]|\.\d)')
alias_lc = {a.lower(): c for a, c in alias.items()}
HUMANS = {'adam': 'adam', 'zak': 'zak', 'shoshannah': 'Shoshannah', 'larissa': 'Larissa Schiavo', 'george': 'george'}
HUM_RE = re.compile(r'\b(adam|zak|shoshannah|larissa|george)\b', re.I)

msgs = con.execute("""
  select c.id, c.created_at, c.speaker_type, c.speaker, c.room, c.content, c.village_goal,
         e.sp as human_name
  from chat c
  left join (select message_id, json_extract_string(data,'$.speakerName') sp
             from events where action_type='USER_TALK') e on e.message_id = c.id
""").df()
msgs['who'] = msgs['speaker']
hm = msgs['speaker_type'] != 'agent'
msgs.loc[hm, 'who'] = 'H:' + msgs.loc[hm, 'human_name'].fillna('unknown')


def era(ts):
    if ts < pd.Timestamp('2026-01-01'): return 'A_2025'
    if ts < pd.Timestamp('2026-02-25'): return 'B_2026pre_rooms'
    if ts < pd.Timestamp('2026-07-06'): return 'C_rooms'
    return 'D_swarm'

msgs['era'] = msgs['created_at'].map(era)
rows = []
for mid, ts, who, room, txt, er in zip(msgs['id'], msgs['created_at'], msgs['who'], msgs['room'], msgs['content'], msgs['era']):
    if not isinstance(txt, str):
        continue
    at = {alias_lc[m.group(1).lower()] for m in AT_RE.finditer(txt)}
    plain = {alias[m.group(1)] for m in PLAIN_RE.finditer(txt)} - at
    for d in at:
        if d != who: rows.append((mid, ts, who, d, room, er, 'at'))
    for d in plain:
        if d != who: rows.append((mid, ts, who, d, room, er, 'plain'))
    for d in {HUMANS[m.group(1).lower()] for m in HUM_RE.finditer(txt)}:
        rows.append((mid, ts, who, 'H:' + d, room, er, 'human'))
edges = pd.DataFrame(rows, columns=['message_id', 'created_at', 'src', 'dst', 'room', 'era', 'kind'])
msgs.drop(columns=['content']).to_parquet(f'{OUT}/messages.parquet')
edges.to_parquet(f'{OUT}/mention_edges.parquet')
print(len(msgs), 'messages;', len(edges), 'edges')
print(edges.groupby(['era', 'kind']).size().unstack())
