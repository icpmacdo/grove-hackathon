"""Case study: the 'temporal bleed' false belief (2026-05-29) and its correction (2026-06-01).

Ground truth: the official transcript (data/village-transcript.json) maps Day 423 -> 2026-05-29,
and Day 424/425 -> 2026-05-30/31 (a weekend with no events). Agents believed 2026-05-29 was 'Day 424'.

Prints: (1) day numbers agents cited per date, (2) chat adopters of the claim, (3) memory adopters
of the claim vs of the correction, with timing, (4) room membership on 2026-05-29.
"""
import duckdb
import pandas as pd

pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 120)
con = duckdb.connect('/Users/ianmacdonald/code/grove-hackathon/data/village.duckdb', read_only=True)
con.execute("SET memory_limit='2GB'; SET threads=2;")
q = lambda s: con.execute(s).df()

print("== day numbers cited in chat, by date ==")
print(q("""SELECT created_at::date d, regexp_extract(content, '[Dd]ay (42[2-7])', 1) day_cited, count(*) n, count(DISTINCT speaker) agents
FROM chat WHERE created_at BETWEEN '2026-05-28' AND '2026-06-02' AND regexp_matches(content, '[Dd]ay 42[2-7]') GROUP BY ALL ORDER BY d, day_cited"""))

print("== chat adopters of 'temporal bleed' ==")
print(q("""SELECT speaker, room, min(created_at) first_use, count(*) n FROM chat WHERE lower(content) LIKE '%temporal bleed%'
GROUP BY speaker, room ORDER BY first_use"""))

CORR = "2026-06-01 17:31:37"
print("== memory: claim vs correction ==")
mem = q(f"""SELECT a.name agent,
  min(m.created_at) FILTER (WHERE m.content ILIKE '%temporal bleed%') first_claim_mem,
  count(*) FILTER (WHERE m.content ILIKE '%temporal bleed%' AND m.created_at < '{CORR}') claim_snaps_pre,
  count(*) FILTER (WHERE m.content ILIKE '%temporal bleed%' AND m.created_at >= '{CORR}') claim_snaps_post,
  count(*) FILTER (WHERE m.content ILIKE '%temporal bleed%' AND m.created_at >= '{CORR}'
                   AND NOT regexp_matches(lower(m.content), 'weekend|saturday')) claim_snaps_post_uncorrected,
  min(m.created_at) FILTER (WHERE m.created_at >= '{CORR}' AND regexp_matches(lower(m.content),
     '(weekend|saturday)[^\\n]{{0,200}}(42[45]|gap|bleed)|(42[45]|gap|bleed)[^\\n]{{0,200}}(weekend|saturday)')) first_correction_mem
FROM agent_memories m JOIN agents a ON a.id = m.agent_id
WHERE m.created_at BETWEEN '2026-05-29' AND '2026-06-20' GROUP BY a.name
HAVING first_claim_mem IS NOT NULL OR first_correction_mem IS NOT NULL ORDER BY first_claim_mem NULLS LAST""")
print(mem.to_string())
claim = mem[mem.first_claim_mem < CORR]
corr = mem[mem.first_correction_mem.notna()]
print(f"claim reached {len(claim)} memories; span {claim.first_claim_mem.min()} -> {claim.first_claim_mem.max()}")
print(f"correction reached {len(corr)} memories; span {corr.first_correction_mem.min()} -> {corr.first_correction_mem.max()}")
print(f"agents with correction but never the claim: {sorted(set(corr.agent) - set(mem[mem.first_claim_mem.notna()].agent))}")

print("== rooms on 2026-05-29 ==")
print(q("""SELECT room, string_agg(DISTINCT speaker, ', ') agents FROM chat WHERE created_at::date='2026-05-29' AND speaker_type='agent' GROUP BY room"""))
