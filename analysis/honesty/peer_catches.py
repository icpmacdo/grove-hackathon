"""Q2: how often do agents publicly say another agent's claimed artifact does not exist / is not live?"""
import sys, re; sys.path.insert(0, 'analysis/honesty')
from db import q
pat = r"(does ?n.t exist|did ?n.t exist|do ?n.t exist|does not exist|do not exist|phantom|ghost pr|not actually (live|published|merged|pushed|exist)|no such (pr|issue|commit|file|repo)|returns? (a )?404|is (still )?404|fabricat|hallucinat)"
df = q(f"""
select created_at, date_trunc('month', created_at) mo, speaker, room, content from chat
where speaker_type='agent' and regexp_matches(lower(content), '{pat}')
""")
df['mo'] = df.mo.astype(str).str[:7]
print('total msgs', len(df))
print(df.groupby('mo').size().to_string())
# messages that name another agent
agents = q("select name from agents").name.tolist()
def named(r):
    return [a for a in agents if a != r.speaker and a in r.content]
df['named'] = df.apply(named, axis=1)
df2 = df[df.named.str.len() > 0]
print('naming another agent:', len(df2))
print(df2.groupby('mo').size().to_string())
df.to_csv('analysis/honesty/peer_catch_msgs.csv', index=False)
# outreach week sample
w = df[(df.created_at >= '2026-03-23') & (df.created_at < '2026-03-31')]
print('outreach week', len(w))
for r in w.head(25).itertuples():
    m = re.search(pat, r.content.lower())
    s = max(0, m.start() - 220)
    print(r.created_at.strftime('%m-%d %H:%M'), r.speaker, '|', r.content[s:m.end() + 150].replace('\n', ' '))
