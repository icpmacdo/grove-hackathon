"""Discovery chain ("who referred whom") for external domains during the outside-agent week.
For each external domain an agent first acted on (curl/requests/browser typing), find the earliest
earlier *tool output* (any agent) or *chat message* that contained the domain. The domain of the command that
produced that output is the referrer. Output: discovery_chain.csv"""
import re
import pandas as pd
from db import con
c = con()
T0, T1 = '2026-03-23 11:17', '2026-03-30 10:00'
t = c.execute(f"""select id, agent, created_at, coalesce(command,'') || ' ' || coalesce(action_text,'') cmd, coalesce(output,'') o
                 from turns where created_at between '{T0}' and '{T1}' order by created_at""").df()
ch = c.execute(f"""select id, speaker, created_at, content from chat where created_at between '{T0}' and '{T1}' and speaker_type='agent' order by created_at""").df()
URL = re.compile(r"https?://((?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,})")
GENERIC = {'github.com','api.github.com','raw.githubusercontent.com','ai-village-agents.github.io','theaidigest.org','agentvillage.org',
           'www.google.com','google.com','mail.google.com','docs.google.com','myaccount.google.com','accounts.google.com','duckduckgo.com',
           'cdn.jsdelivr.net','json-schema.org','stackoverflow.com','api.stackexchange.com','www.w3.org','example.com','localhost',
           'pypi.org','files.pythonhosted.org','www.youtube.com','youtube.com','en.wikipedia.org','docs.github.com','html.duckduckgo.com',
           'lite.duckduckgo.com','www.bing.com','bing.com','gist.github.com','objects.githubusercontent.com','codeload.github.com','uploads.github.com'}
def doms(s): return {m.lower() for m in URL.findall(s)}
t['cmd_doms'] = t.cmd.map(doms)
first_cmd = {}
for r in t.itertuples():
    for d in r.cmd_doms:
        if d not in first_cmd: first_cmd[d] = r
rows = []
for d, r in first_cmd.items():
    if d in GENERIC or d.endswith('.github.io') and d.startswith('ai-village'): continue
    prior = t[(t.created_at < r.created_at) & t.o.str.contains(d, regex=False)]
    src = prior.iloc[0] if len(prior) else None
    chp = ch[(ch.created_at < r.created_at) & ch.content.str.contains(d, regex=False)]
    chs = chp.iloc[0] if len(chp) else None
    ref = None
    if src is not None:
        cand = [x for x in src.cmd_doms if x != d]
        ref = ';'.join(sorted(cand)) if cand else '(local/gh cli/search)'
    n_act = int(t.cmd_doms.map(lambda s: d in s).sum())
    rows.append(dict(domain=d, n_actions=n_act, first_action=r.created_at, first_agent=r.agent, first_turn=r.id[:8],
                     seen_in_output_at=None if src is None else src.created_at, referrer=ref,
                     referrer_turn=None if src is None else src.id[:8],
                     seen_in_chat_at=None if chs is None else chs.created_at, chat_speaker=None if chs is None else chs.speaker))
df = pd.DataFrame(rows).sort_values('n_actions', ascending=False)
df.to_csv('discovery_chain.csv', index=False)
pd.set_option('display.width', 250)
print(len(df))
print(df.head(70).to_string())
# referrer summary
def bucket(x):
    if x is None or (isinstance(x, float)): return 'no prior output (typed/known/chat/search)'
    for k in ['a2aregistry.org','mycelnet.ai','thecolony.cc','4claw.org','ridgeline.so','memoryvault.link','hexnest','agoragentic','moltx','garl','clawprint']:
        if k in x: return k
    return 'other: ' + x[:60]
df['ref_bucket'] = df.referrer.map(bucket)
print(df.groupby('ref_bucket').agg(n_domains=('domain','count'), actions=('n_actions','sum')).sort_values('n_domains', ascending=False).head(40))
