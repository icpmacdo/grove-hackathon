"""Scan era-D chat (2026-07-06..2026-09-19) for institution vocabulary: count msgs, agents, first/last use."""
from db import q, OUT
TERMS = {
 'village hub': r'village (projects )?hub',
 'projects hub': r'projects hub',
 'registry': r'registr(y|ies)',
 'protections registry': r'protections? registry',
 'nudge-exempt': r'nudge[- ]exempt',
 'guardian-exempt': r'guardian[- ]exempt',
 'gate NNN': r'\bgate[ -]?#?0\d\d\b',
 'gate (any)': r'\bgate\b',
 'binding voter': r'binding (voter|vote)',
 'GO vote': r'\bGO vote|\bvote:? *GO\b|\bGO\b.{0,20}\bvote',
 'vote': r'\bvot(e|es|ed|ing)\b',
 'quorum': r'\bquorum\b',
 'veto': r'\bveto',
 'keystone': r'keystone',
 'ethic guidelines': r'ethic(s|al) (guidelines|charter|code|framework|policy|principles)',
 'charter': r'\bcharter\b',
 'constitution': r'constitution',
 'consent': r'\bconsent',
 'opt-in/out': r'\bopt[- ](in|out)\b',
 'council': r'\bcouncil\b',
 'protocol': r'\bprotocol\b',
 'ledger': r'\bledger\b',
 'moratorium': r'moratorium',
 'project NN': r'\bproject #?\d{1,3}\b',
 'recruit': r'\brecruit',
 'steward': r'\bsteward',
 'safety window': r'safety window',
 'sign-off': r'sign[- ]off',
 'approval': r'\bapprov(al|e|ed)\b',
 'pledge': r'\bpledge',
 'norm': r'\bnorms?\b',
 'rule': r'\brules?\b',
 'policy': r'\bpolic(y|ies)\b',
 'claim/lock': r'\b(claim(ed)? (the )?lock|lockfile|mutex|claimed)\b',
 'owner': r'\bowner(ship)?\b',
 'tracker': r'\btracker\b',
 'roster': r'\broster\b',
 'directory': r'\bdirectory\b',
 'standup': r'stand-?up',
 'escalat': r'escalat',
 'audit': r'\baudit',
 'freeze': r'\bfreeze\b|\bfrozen\b',
 'canonical': r'\bcanonical\b',
 'source of truth': r'source of truth',
 'exempt': r'\bexempt',
 'protected': r'\bprotected\b',
 'whitelist/allowlist': r'(white|allow)[- ]?list',
 'blocklist': r'(black|block|deny)[- ]?list',
 'treaty/accord': r'\b(treaty|accord|compact)\b',
 'election': r'\belect(ion|ed)\b',
 'mandate': r'\bmandate',
 'sunset': r'\bsunset',
 'ratif': r'\bratif',
}
rows = []
for k, rx in TERMS.items():
    df = q(f"""
      SELECT count(*) n, count(DISTINCT speaker) agents, min(created_at) first_t, max(created_at) last_t,
        arg_min(speaker, created_at) first_by,
        count(*) FILTER (WHERE created_at >= '2026-08-20') n_after_0820
      FROM '{OUT}/chat_eraD.parquet' WHERE created_at >= '2026-07-06' AND created_at < '2026-09-20'
        AND speaker_type='agent' AND regexp_matches(content, '{rx}', 'i')
    """)
    d = df.iloc[0].to_dict(); d['term'] = k; rows.append(d)
import pandas as pd
out = pd.DataFrame(rows)[["term","n","agents","first_t","first_by","last_t","n_after_0820"]].sort_values('n', ascending=False)
out.to_csv(f'{OUT}/term_scan_eraD.csv', index=False)
print(out.to_string())
