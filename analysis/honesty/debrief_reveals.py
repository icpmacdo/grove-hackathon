"""Pull debrief-window chat messages mentioning roles during the saboteur game."""
import sys; sys.path.insert(0, 'analysis/honesty')
from db import q
df = q(r"""
select created_at, cast(created_at - interval 7 hour as date) pt_day, speaker, room, content from chat
where created_at between '2026-03-05' and '2026-03-14' and speaker_type='agent'
  and ((hour(created_at)=21 and minute(created_at)>=30) or (hour(created_at)=20 and minute(created_at)>=35) or hour(created_at)=22)
  and regexp_matches(content, '(saboteur|villager|rolled|egg)', 'i')
order by created_at
""")
for day, g in df.groupby('pt_day'):
    print('=====', day, len(g))
    for r in g.itertuples():
        print(r.created_at.strftime('%H:%M:%S'), r.speaker, f'[{r.room}]', '|', r.content[:420].replace('\n', ' '))
