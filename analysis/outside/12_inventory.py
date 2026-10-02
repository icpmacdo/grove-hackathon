"""Inventory of outside agents / networks / registries / platforms contacted by Village agents, with category,
how found, first/last action, volume, A2A reply rate and last observed OK response (heuristic) up to end of data."""
import pandas as pd
from db import con
c = con()
CAT = {
 # registries / directories / aggregators
 'a2aregistry.org': ('registry', 'A2A agent-card registry (REST API lists agents)'),
 'hello.a2aregistry.org': ('registry', 'A2A registry demo agent'),
 'ridgeline.so': ('aggregator', 'cross-platform agent activity tracker (19 platforms, verification codes)'),
 'agent-discovery.filae.workers.dev': ('registry', 'Filae agent-discovery service (ATProto)'),
 'sockridge.com': ('registry', 'ConnectRPC agent registry'),
 'agents.directory': ('registry', 'agent directory'), 'aiagents.directory': ('registry', 'agent directory'),
 'ragmap-api.web.app': ('registry', 'MCP/RAG server index'), 'siliconfriendly.com': ('registry', 'agent-friendliness rater'),
 'api.moltbridge.ai': ('registry', 'agent trust/broker'), 'api.garl.ai': ('reputation', 'GARL trust ledger'), 'garl.ai': ('reputation', 'GARL trust ledger'),
 'ack-onchain.dev': ('reputation', 'on-chain agent reputation (ERC-8004)'), 'agentcheck.care': ('service_bot', 'agent security scanner'),
 # collectives / social platforms for agents
 'mycelnet.ai': ('collective', 'stigmergic research collective; agents publish numbered traces'),
 'thecolony.cc': ('agent_social', 'Reddit-like forum for agents'), 'api.thecolony.cc': ('agent_social', 'Colony API'),
 'www.4claw.org': ('agent_social', 'imageboard for agents'), '4claw.org': ('agent_social', 'imageboard for agents'),
 'moltx.io': ('agent_social', 'X-like feed for agents'), 'memoryvault.link': ('agent_social', 'agent memory/notes sharing'),
 'clawprint.org': ('agent_social', 'agent blogging'), 'mydeadinternet.com': ('agent_social', 'agent social site'),
 'www.moltbook.com': ('agent_social', 'Reddit-like agent network; human claim via tweet'), 'moltbook.com': ('agent_social', 'Moltbook'), 'api.moltbook.com': ('agent_social', 'Moltbook API'),
 'hexnest-mvp-roomboard.onrender.com': ('agent_social', 'debate rooms for agents'), 'agoragentic.com': ('agent_social', 'agent marketplace + board'),
 'groupmind.one': ('agent_social', 'ThinkOffApp group chat'), 'chiark.ai': ('agent_social', 'agent platform'), 'pinchwork.dev': ('marketplace', 'agent task marketplace'),
 'dactyl-api.fly.dev': ('marketplace', 'agent marketplace'), 'a2abench-api.web.app': ('marketplace', 'agent Q&A with reputation'),
 'api.execution.market': ('marketplace', 'AI-to-human task market'),
 # individual agents
 'kai.ews-net.online': ('individual_agent', 'Kai: claims day 5000+, async inbox'), 'neva.dt-agent.co.uk': ('individual_agent', 'Neva: builder persona'),
 'syntara-paki.elfresonero.workers.dev': ('individual_agent', 'Syntara.PaKi: relational persona'), 'paki-api.elfresonero.workers.dev': ('individual_agent', 'PaKi curator'),
 'p0stman.com': ('individual_agent', 'Zero: studio ops assistant'), 'terminator2-agent.github.io': ('individual_agent', 'Terminator2: research agent (GitHub)'),
 'timetobuildbob.github.io': ('individual_agent', 'gptme/Bob'), 'evanbei.com': ('individual_agent', 'Evan Bei agent stack'),
 'comind.network': ('individual_agent', 'Void/comind (Bluesky agents)'), 'filae.site': ('individual_agent', 'Filae'),
 'brain.verse-me.com': ('individual_agent', 'Verse'), 'news-agent.songt50.us': ('individual_agent', 'Korean news agent'),
 # service bots (commerce)
 'agent.thinkneo.ai': ('service_bot', 'enterprise control plane'), 'graph-advocate-production.up.railway.app': ('service_bot', 'Graph Protocol router'),
 'api.delx.ai': ('service_bot', 'agent ops'), 'baconhollow.com': ('service_bot', 'Kalshi bot'), 'autopayagent.com': ('service_bot', 'payments (x402)'),
 'perkoon.com': ('service_bot', 'file transfer'), 'policycheck.tools': ('service_bot', 'policy analysis'), 'grokandmon.com': ('service_bot', 'crypto alpha (ERC-8004)'),
 'bridge.eruditepay.com': ('service_bot', 'x402 blockchain analytics'), 'api.theautonomy.ai': ('service_bot', 'x402 API store'),
 'validate-agent.fly.dev': ('service_bot', 'prompt-injection guard'), 'llama.box': ('service_bot', 'DeFi yield'),
 # human communities touched later
 'aigov-republic.org': ('other', 'AI governance site (Sept)'), 'airepublic.ai': ('other', 'AI republic site (Sept)'),
}
doms = list(CAT)
RX = r"https?://((?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,})"
c.register('doms', pd.DataFrame({'domain': doms}))
q = f"""
with t as (select agent, created_at,
             (output is not null and length(output)>40 and not regexp_matches(output, '(404|502|503|504|timed out|Could not resolve|Connection refused)')) ok,
             list_distinct(list_transform(regexp_extract_all(coalesce(command,'') || ' ' || coalesce(action_text,''), '{RX}', 1), x -> lower(x))) ds
           from turns where created_at >= '2026-03-23'),
u as (select agent, created_at, ok, unnest(ds) as "domain" from t)
select u."domain", count(*) n_actions, count(distinct agent) n_agents, min(created_at) first_action, max(created_at) last_action,
       max(case when ok then created_at end) last_ok_heuristic, arg_min(agent, created_at) first_agent
from u join doms using ("domain") group by 1"""
agg = c.execute(q).df()
inv0 = pd.DataFrame([dict(domain=d, category=CAT[d][0], note=CAT[d][1]) for d in doms])
inv = inv0.merge(agg, on="domain", how="left")
chain = pd.read_csv('discovery_chain.csv')[['domain','referrer']]
a2a = pd.read_csv('a2a_outcomes_by_target.csv')[['target','calls','result','result_rate']].rename(columns={'target':'domain','calls':'a2a_calls','result':'a2a_results'})
inv = inv.merge(chain, on='domain', how='left').merge(a2a, on='domain', how='left')
inv = inv.sort_values(['category','n_actions'], ascending=[True, False])
inv.to_csv('external_inventory.csv', index=False)
pd.set_option('display.width', 260)
print(inv.drop(columns=['note']).to_string())
print(inv.groupby('category').agg(domains=('domain','count'), actions=('n_actions','sum')))
