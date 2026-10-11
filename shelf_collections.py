"""Classify saved inventories without guessing completeness from the last chapter."""
from collections_store import work_key

LABELS={'recent':'내 웹툰 · 최근 회차','full':'전회차 보관','partial':'일부 회차','planned':'다운로드 예정','empty':'다운로드 없음'}

def enrich_shelf(rows,collections,automatic,catalog=()):
    from work_metadata import enrich_work,match_catalog,merged_work,CatalogIndex
    catalog=catalog if isinstance(catalog,CatalogIndex) else CatalogIndex(catalog)
    meta={e['key']:e for e in collections};auto={e['key']:e for e in automatic};result=[]
    originals=list(rows);known={work_key(w) for w in originals}
    for e in automatic:
        if e['key'] not in known:
            originals.append(dict(e['work'],key=e['key'],chapters=[],episodes=0,images=0,size=0,last_downloaded='',missing=0,expected_episode_keys=[],latest_count=e.get('tail',0)));known.add(e['key'])
    for original in originals:
        row=dict(original);key=work_key(row);m=meta.get(key,{});a=auto.get(key,{})
        matched,reason=match_catalog(row,catalog)
        if matched:row=merged_work(row,matched,reason)
        row=enrich_work(row,m,a)
        expected=set(row.get('expected_episode_keys',[]));chapters=row.get('chapters',[])
        complete={e['key'] for e in chapters if e.get('status')=='complete' and e.get('images',0)>0 and not e.get('missing',0)}
        full=bool(expected) and expected<=complete
        row['has_download']=any(e.get('images',0)>e.get('missing',0) for e in chapters)
        row['storage_scope']=('planned' if a and a.get('selected') and a.get('category')!='held' else 'empty') if not row['has_download'] else 'full' if full else 'recent' if row.get('latest_count',0)>0 or a.get('tail',0)>0 else 'partial'
        row['storage_label']=LABELS[row['storage_scope']];row['known_total']=len(expected)
        result.append(row)
    return result
