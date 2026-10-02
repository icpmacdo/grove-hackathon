"""Rank coined-term candidates from ngram_candidates.parquet (output of 01).
Filters out agent names, tooling words and goal/human-seeded phrases; splits into
Title-Case names vs lowercase concept phrases. Writes coinages_titlecase.csv / coinages_lowercase.csv."""
import os, re
import pandas as pd
OUT = os.path.dirname(os.path.abspath(__file__))
pd.set_option('display.width', 250); pd.set_option('display.max_colwidth', 70); pd.set_option('display.max_rows', 300)
df = pd.read_parquet(os.path.join(OUT, 'ngram_candidates.parquet'))
BLOCK = set("""claude haiku sonnet opus fable gemini gpt deepseek deepseek-v3 deepseek-v4-pro grok kimi glm o3 o1 gpt-5 gpt-5.1 gpt-5.2 gpt-5.4 gpt-5.5
pr prs day days git gh github api ci yaml npm node url sha256 commit commits repo repos issue issues mr glab gitlab json html http https
cli test tests pages session sessions email gmail docs doc readme md py js css p0 p1 p2 utc pt am pm thanks thank chat
monday tuesday wednesday thursday friday i'm minuteandone nervli wave pro flash k2 k3 v3 leader goal goals""".split())
def ok(g):
    t = g.split()
    if any(w in BLOCK or re.match(r'^(gpt|claude|gemini|opus|deepseek|kimi|glm)', w) for w in t):
        return False
    if t[0] in ('and','or','to','of','the','for','in','on','with','by','from','a','is') and len(t) == 2:
        return False
    if t[-1] in ('and','or','to','of','the','for','in','on','with','by','from','a','is','i','we','it','my'):
        return False
    return True
d = df[df.ngram.map(ok) & ~df.in_goal & ~df.human_before].copy()
# drop n-grams that are strict sub-phrases of a longer candidate with the same first use & agents
d = d.sort_values(['n_agents','n'], ascending=[False, False])
keep = []
seen = {}   # first_ts -> list of (ngram, n_agents): sub-phrases share the coiner's first message
for _, r in d.iterrows():
    grp = seen.setdefault(r.first_msg, [])
    if any(r.ngram in s and r.n_agents <= na + 1 for s, na in grp):
        continue
    keep.append(r); grp.append((r.ngram, r.n_agents))
d = pd.DataFrame(keep)
cols = ['ngram','n_agents','n_families','uses','first_utc','first_agent','first_room','hours_to_5','cap_frac','order']
tc = d[d.cap_frac >= 0.7].sort_values('n_agents', ascending=False)
lc = d[(d.cap_frac < 0.4)].sort_values('n_agents', ascending=False)
tc.to_csv(os.path.join(OUT, 'coinages_titlecase.csv'), index=False)
lc.to_csv(os.path.join(OUT, 'coinages_lowercase.csv'), index=False)
print(len(d), len(tc), len(lc))
print(tc[cols].head(60).to_string())
print(lc[cols].head(70).to_string())
