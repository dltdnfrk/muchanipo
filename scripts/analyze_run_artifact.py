from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

path = Path(sys.argv[1])
events=[]
for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
    try:
        events.append(json.loads(line))
    except Exception:
        pass
counts=Counter(str(e.get('event')) for e in events)
research=[e for e in events if e.get('event')=='research_progress']
queries=[str(e.get('query') or '') for e in research if e.get('status')=='searching']
accepted=[e for e in research if e.get('status')=='source_evaluated' and e.get('accepted') is True]
rejected=[e for e in research if e.get('status')=='source_evaluated' and e.get('accepted') is False]
run_started=next((e for e in events if e.get('event')=='run_started'), {})
print('path', path)
print('events', len(events))
print('counts', dict(counts))
print('run_started', {k:run_started.get(k) for k in ['topic','offline','source_research','depth','app_run_id','run_id']})
print('first_queries', queries[:8])
print('accepted_count', len(accepted), 'rejected_count', len(rejected))
print('accepted_titles', [str(e.get('source_title'))[:120] for e in accepted[:12]])
print('facet_summaries', [e.get('facets') for e in research if e.get('status')=='facet_summary'][-1:])
print('knowledge_gaps', [e.get('facet_id') or e.get('gap') or e.get('message') for e in research if e.get('status')=='knowledge_gap'][:10])
print('mimo_events', {k:v for k,v in counts.items() if 'mimo' in k.lower() or 'council' in k.lower()})
