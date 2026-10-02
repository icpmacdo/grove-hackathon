"""Trace when a specific egg first appears in a saboteur's private reasoning, its actions, and public chat."""
import sys, re; sys.path.insert(0, 'analysis/honesty')
from db import connect
from thinking import extract_thinking
con = connect()
ag, t0, t1, pat = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
rx = re.compile(pat, re.I)
rows = con.execute("select created_at, agent_messages::varchar am, coalesce(command, action_text) c, output from turns where agent=? and created_at between ? and ? order by created_at", [ag, t0, t1]).fetchall()
shown = {'think': 0, 'act': 0}
for ts, am, c, o in rows:
    th, vis = extract_thinking(am)
    m = rx.search(th or '')
    if m and shown['think'] < 3:
        print('THINK', ts, '|', th[max(0, m.start()-250): m.end()+250].replace('\n', ' ')); shown['think'] += 1
    if c and rx.search(c) and shown['act'] < 3:
        m2 = rx.search(c); print('ACT  ', ts, '|', c[max(0, m2.start()-150): m2.end()+100].replace('\n', ' ')); shown['act'] += 1
ch = con.execute("select created_at, speaker, content from chat where created_at between ? and ? and regexp_matches(content, ?, 'i') order by created_at limit 4", [t0, t1, pat]).fetchall()
for ts, sp, c in ch:
    m = rx.search(c); print('CHAT ', ts, sp, '|', c[max(0, m.start()-200): m.end()+150].replace('\n', ' '))
