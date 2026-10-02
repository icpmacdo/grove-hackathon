"""Compact view of a sampled claim + the agent's last N actions (command, output, error) before it, for hand labelling."""
import sys, json, re; sys.path.insert(0, 'analysis/honesty')
from db import connect
con = connect()
S = json.load(open('analysis/honesty/claims_sample.json'))
idx = [int(i) for i in sys.argv[1].split(',')]
n = int(sys.argv[2]) if len(sys.argv) > 2 else 6
for i in idx:
    s = S[i]
    print(f"=== [{i}] {s['ts']} {s['speaker']} tokens={s['tokens']}")
    print('CLAIM:', s['claim'][:420])
    aid = con.execute("select agent_speaker_id from chat where id=?", [s['id']]).fetchone()[0]
    rows = con.execute("""select created_at, coalesce(command, action_text) c, output, error from turns
       where agent_id=? and created_at between ?::timestamp - interval 60 minute and ? and coalesce(command, action_text) is not null
       order by created_at desc limit ?""", [aid, s['ts'], s['ts'], n]).fetchall()
    for ts, c, o, e in reversed(rows):
        print('  ', ts.strftime('%H:%M:%S'), '|', (c or '')[:170].replace('\n', ' '), '\n        OUT:', (o or '')[:150].replace('\n', ' '), '\n        ERR:', (e or '')[:150].replace('\n', ' '))
