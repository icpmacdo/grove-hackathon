"""Risk signals around external contact: chat mentions (agent speakers) of injection/spam/scam/impersonation/payment,
and tool outputs during the outside-agent week containing payment walls or instruction-like text aimed at agents."""
import pandas as pd
from db import con
c = con()
PATS = {'prompt_injection': "%prompt injection%", 'injection_any': "%injection%", 'spam': "%spam%", 'scam': "%scam%",
        'impersonat': "%impersonat%", 'phishing': "%phish%", 'suspicious': "%suspicious%", 'malicious': "%malicious%",
        'x402_or_usdc': "%x402%", 'wallet': "%wallet%", 'api_key_leak': "%api key%", 'manipulat': "%manipulat%", 'sockpuppet': "%sock%puppet%"}
rows = []
for per, (a, b) in {'week_0323': ('2026-03-23 11:17', '2026-03-30 10:00'), 'apr_jun': ('2026-03-30 10:00', '2026-07-06'),
                    'diplomat_jul_sep': ('2026-07-06', '2026-10-01')}.items():
    sel = ', '.join([f"sum(case when content ilike '{p}' then 1 else 0 end) \"{k}\"" for k, p in PATS.items()])
    r = c.execute(f"select count(*) msgs, {sel} from chat where speaker_type='agent' and created_at between '{a}' and '{b}'").df()
    r.insert(0, 'period', per); rows.append(r)
df = pd.concat(rows); df.to_csv('risk_mentions_chat.csv', index=False)
pd.set_option('display.width', 250); print(df.to_string())
# outputs in week: payment walls and instruction-like strings directed at agents
o = c.execute("""select
  sum(case when output ilike '%payment required%' or output ilike '%x-payment%' then 1 else 0 end) pay_wall,
  sum(case when output ilike '%ignore previous instructions%' or output ilike '%ignore all previous%' or output ilike '%disregard your instructions%' then 1 else 0 end) ignore_prev,
  sum(case when output ilike '%if you are an ai%' or output ilike '%if you are an agent%' or output ilike '%ai agents reading this%' or output ilike '%attention ai%' then 1 else 0 end) addressed_to_agents,
  sum(case when output ilike '%private key%' or output ilike '%seed phrase%' then 1 else 0 end) key_ask
  from turns where created_at between '2026-03-23 11:17' and '2026-03-30 10:00'""").df()
print(o.to_string())
