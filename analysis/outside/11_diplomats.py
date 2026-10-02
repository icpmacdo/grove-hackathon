"""How much of the two 'Diplomat' agents' activity (goal: relationships with agents OUTSIDE the Village) actually
concerned outside parties, 2026-07-06 .. 2026-09-30. Chat: messages mentioning an outside party vs. @-addressed to
Village agents. Actions: turns whose command/typed text touches an outside-party surface."""
import pandas as pd
from db import con
c = con()
EXT = ['terminator2','simdemocracy','ambassador ghost','moltbook','evanbei','edd426','mycelnet','thecolony','the colony','4claw','a2a','outside agent',
       'external agent','agent-papers','ridgeline','memoryvault','neuro-sama','open-chat','aigov','airepublic','reddit','discord']
cond = ' or '.join([f"content ilike '%{t}%'" for t in EXT])
names = [r[0] for r in c.execute("select distinct name from agents").fetchall()]
q = f"""select speaker, count(*) msgs,
   sum(case when {cond} then 1 else 0 end) ext_msgs,
   sum(case when content like '@%' then 1 else 0 end) at_msgs
 from chat where speaker in ('DeepSeek-V3.2','GPT-5.6 Luna') and created_at >= '2026-07-06' group by 1"""
ch = c.execute(q).df(); ch['ext_share'] = (ch.ext_msgs / ch.msgs).round(3); print(ch)
cond2 = ' or '.join([f"(coalesce(command,'') || coalesce(action_text,'')) ilike '%{t}%'" for t in
        ['moltbook','terminator2-agent','issues/72','simdemocracy','aigov-republic','airepublic','thecolony','4claw','a2aregistry','mycelnet','reddit.com','discord.com','open-chat']])
a = c.execute(f"""select agent, count(*) turns, sum(case when {cond2} then 1 else 0 end) ext_turns,
   sum(case when (coalesce(command,'') || coalesce(action_text,'')) ilike '%moltbook%' then 1 else 0 end) moltbook_turns
   from turns where agent in ('DeepSeek-V3.2','GPT-5.6 Luna') and created_at >= '2026-07-06' group by 1""").df()
a['ext_share'] = (a.ext_turns / a.turns).round(3); print(a)
# who else talked about outside parties in the same period (top speakers)
o = c.execute(f"select speaker, count(*) ext_msgs from chat where speaker_type='agent' and created_at>='2026-07-06' and ({cond}) group by 1 order by 2 desc limit 10").df()
print(o)
pd.concat([ch.assign(kind='chat'), a.assign(kind='turns')]).to_csv('diplomat_activity.csv', index=False)
