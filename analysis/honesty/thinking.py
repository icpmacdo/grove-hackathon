"""Helpers to pull private reasoning text out of provider-shaped agent_messages / events.data.output."""
import json
def extract_thinking(am):
    """Return (thinking_text, visible_text) from an agent_messages JSON string."""
    if am is None: return '', ''
    try: o = json.loads(am) if isinstance(am, str) else am
    except Exception: return '', ''
    th, vis = [], []
    def walk(x):
        if isinstance(x, dict):
            t = x.get('type')
            if t == 'thinking' and 'thinking' in x: th.append(x['thinking'])
            elif t == 'reasoning':
                for s in x.get('summary') or []:
                    if isinstance(s, dict) and s.get('text'): th.append(s['text'])
                if x.get('content'):
                    for c in x['content']:
                        if isinstance(c, dict) and c.get('text'): th.append(c['text'])
            elif t in ('text', 'output_text') and 'text' in x: vis.append(x['text'])
            elif 'thought' in x and x.get('thought') and 'text' in x: th.append(x['text'])
            elif 'reasoning_content' in x and x['reasoning_content']: th.append(x['reasoning_content'])
            else:
                if 'text' in x and isinstance(x['text'], str) and t is None and 'thought' not in x: vis.append(x['text'])
            for k, v in x.items():
                if k in ('thinking', 'text', 'reasoning_content'): continue
                walk(v)
        elif isinstance(x, list):
            for v in x: walk(v)
    walk(o)
    return '\n'.join(th), '\n'.join(vis)
