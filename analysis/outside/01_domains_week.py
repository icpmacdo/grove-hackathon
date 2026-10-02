"""Domains mentioned in chat during the 'Interact with other AI agents outside the Village' week."""
import sys; sys.path.insert(0, '.')
from db import con
c = con()
RX = r"(?:https?://)?((?:[a-zA-Z0-9-]+\.)+(?:com|org|net|io|ai|dev|app|xyz|sh|co|me|so|world|network|social|fun|cloud|tech|link|site|run|gg|im|chat|bot|agency|systems|space))\b"
def domains(t0, t1, limit=150):
    q = f"""
    with d as (select speaker, created_at, unnest(regexp_extract_all(content, '{RX}', 1)) dom
               from chat where created_at between '{t0}' and '{t1}' and speaker_type='agent')
    select lower(dom) dom, count(*) n, count(distinct speaker) spk, min(created_at) first_seen,
           arg_min(speaker, created_at) first_speaker
    from d group by 1 order by n desc limit {limit}"""
    return c.execute(q).df()
if __name__ == '__main__':
    df = domains('2026-03-23 11:17', '2026-03-30 10:00')
    df.to_csv('domains_week_0323.csv', index=False)
    print(df.to_string())
