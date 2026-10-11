"""Classify saved inventories without guessing completeness from the last chapter."""
from collections_store import work_key

LABELS={'recent':'내 웹툰 · 최근 회차','full':'전회차 보관','partial':'일부 회차'}

def enrich_shelf(rows,collections,automatic):
    meta={e['key']:e for e in collections};auto={e['key']:e for e in automatic};result=[]
    for original in rows:
        row=dict(original);key=work_key(row);m=meta.get(key,{});a=auto.get(key,{})
        candidates=[m.get('weekday',-1),a.get('weekday',-1),row.get('weekday',-1)]
        row['weekday']=next((d for d in candidates if isinstance(d,int) and d in range(7)),-1)
        expected=set(row.get('expected_episode_keys',[]));chapters=row.get('chapters',[])
        complete={e['key'] for e in chapters if e.get('status')=='complete' and e.get('images',0)>0 and not e.get('missing',0)}
        full=bool(expected) and expected<=complete
        row['storage_scope']='full' if full else 'recent' if row.get('latest_count',0)>0 or a.get('tail',0)>0 else 'partial'
        row['storage_label']=LABELS[row['storage_scope']];row['known_total']=len(expected)
        result.append(row)
    return result
