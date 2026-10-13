export const DAYS=['월','화','수','목','금','토','일'];
export function key(w){try{return new URL(w.url).pathname}catch{return w.key||w.title||''}}
export function weekdays(w){const days=new Set((Array.isArray(w.weekdays)?w.weekdays:[]).filter(d=>Number.isInteger(d)&&d>=0&&d<7));if(Number.isInteger(w.weekday)&&w.weekday>=0&&w.weekday<7)days.add(w.weekday);return [...days].sort()}
export function library(snapshot={},local=[]){
 const result=new Map();const entries=snapshot.lists?.entries||[];const metadata=new Map((snapshot.favorites?.collections||[]).map(e=>[e.key,e]));
 for(const w of snapshot.works||[])result.set(key(w),{...w,chapters:[]});
 for(const e of entries)result.set(e.key||key(e.work),{...(result.get(e.key)||{}),...e.work,auto:e,chapters:[]});
 for(const w of local){const k=w.key||key(w);result.set(k,{...(result.get(k)||{}),...w,chapters:w.chapters||[]})}
 return [...result.entries()].map(([k,w])=>{
  const m=metadata.get(k)||{};const remote=m.work||{};w={...w,...Object.fromEntries(['genre','publisher','updated_date','weekdays','weekday'].filter(f=>remote[f]!==undefined&&remote[f]!=='').map(f=>[f,remote[f]])),genre:m.genre||w.genre||'',publisher:m.publisher||w.publisher||'',key:k};
  const override=m.weekday>=0?m.weekday:w.auto?.weekday;w.weekdays=override>=0?[override]:weekdays(w);
  const count=w.chapters.length;w.scope=count?(w.complete?'full':'recent'):'pending';w.label=count?(w.complete?'전회차 보관':'최근 / 일부 회차'):w.auto?.selected&&w.auto?.category!=='held'?'다운로드 예정':'다운로드 없음';return w;
 });
}
export function filter(rows,{search='',days=null,publisher='',genre='',scope='all',from='',to='',dateKind='updated_date'}={}){
 return rows.filter(w=>{
  const actual=(w[dateKind]||'').slice(0,10);
  return (!search||w.title.toLocaleLowerCase().includes(search.toLocaleLowerCase()))&&(!publisher||w.publisher.toLocaleLowerCase().includes(publisher.toLocaleLowerCase()))&&(!genre||w.genre.toLocaleLowerCase().includes(genre.toLocaleLowerCase()))&&(scope==='all'||w.scope===scope)&&(days===null||days.some(d=>(w.weekdays.length?w.weekdays:[-1]).includes(d)))&&(!from||actual&&actual>=from)&&(!to||actual&&actual<=to)&&!(from&&to&&from>to);
 });
}
export function validateSnapshot(value){
 const p=value?.format==='toonshelf-mobile'?value.payload:value;
 if(!p||typeof p!=='object'||Array.isArray(p)||!['lists','works','favorites'].some(k=>k in p))throw Error('ToonShelf 목록 파일을 선택하세요.');
 if(p.works!==undefined&&!Array.isArray(p.works)||p.lists?.entries!==undefined&&!Array.isArray(p.lists.entries)||p.favorites?.collections!==undefined&&!Array.isArray(p.favorites.collections))throw Error('목록 형식을 확인하세요.');
 const all=[...(p.works||[]),...(p.lists?.entries||[]).map(e=>e.work),...(p.favorites?.collections||[]).map(e=>e.work)];
 if(all.length>30000||all.some(w=>!w||typeof w.title!=='string'||!w.title.trim()||typeof w.url!=='string'))throw Error('작품 정보를 확인하세요.');
 for(const w of all){const u=new URL(w.url);if(!['https:','http:'].includes(u.protocol)||u.username||u.password)throw Error('작품 링크를 확인하세요.')}
 return p;
}
export function natural(a,b){return a.localeCompare(b,'ko',{numeric:true,sensitivity:'base'})}
export function recorded(a,an,b,bn){const x=Number(a)>0?Number(a):Infinity,y=Number(b)>0?Number(b):Infinity;return x===y?natural(an,bn):x<y?-1:1}
export function orderedImages(files,meta){
 if(!Array.isArray(meta.images)||!meta.images.length)return files.slice().sort((a,b)=>natural(a.name,b.name));
 const byName=new Map(files.map(f=>[f.name,f])),seen=new Set(),names=new Set();
 const plan=meta.images.filter(e=>!e.filtered).slice().sort((a,b)=>Number(a.position)-Number(b.position));
 return plan.map((entry,i)=>{const p=Number(entry.position??i+1),name=entry.file;if(!(p>0)||seen.has(p)||names.has(name)||!name||name.includes('/')||name.includes('\\'))throw Error('이미지 순서 기록이 중복되거나 잘못됐습니다. PC에서 순서를 확인하세요.');seen.add(p);names.add(name);const f=byName.get(name);if(!f)throw Error('순서 기록의 이미지가 없습니다: '+name);return f});
}
export function bytes(n){for(const unit of ['B','KB','MB','GB']){if(n<1024||unit==='GB')return n.toFixed(1)+' '+unit;n/=1024}}
