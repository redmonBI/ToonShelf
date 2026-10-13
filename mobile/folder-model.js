import {natural,orderedImages,recorded} from './model.js';
export function folderGroups(files){
 const groups=new Map();
 for(const f of files){const parts=(f.webkitRelativePath||f.name).replaceAll('\\','/').split('/');if(parts.some(p=>p==='..')||parts.some(p=>p.startsWith('.')||['state','Source','Vendor','Updates','PreviousVersion'].includes(p)))continue;if(!/\.(png|jpe?g|webp|gif|avif)$/i.test(f.name))continue;
 const title=parts.length>=4?parts[1]:parts[0],chapter=parts.length>=3?parts.at(-2):'1화',k=title+'\u0000'+chapter;
 if(!groups.has(k))groups.set(k,{title,chapter,files:[]});groups.get(k).files.push(f);
 }
 return [...groups.values()].sort((a,b)=>natural(a.title,b.title)||natural(a.chapter,b.chapter)).map(g=>({...g,files:g.files.sort((a,b)=>natural(a.name,b.name))}));
}
export async function orderedFolderGroups(files){
 const groups=folderGroups(files),metadata=new Map(files.filter(f=>f.name==='_reading_order.json').map(f=>[(f.webkitRelativePath||f.name).replaceAll('\\','/').split('/').slice(0,-1).join('/'),f]));
 for(const group of groups){const parent=(group.files[0].webkitRelativePath||'').replaceAll('\\','/').split('/').slice(0,-1).join('/'),source=metadata.get(parent);if(!source){group.meta={work:group.title,episode:group.chapter,order_source:'filename'};continue}if(source.size>4*1024*1024)throw Error('회차 순서 기록이 너무 큽니다.');group.meta=JSON.parse(await source.text());group.files=orderedImages(group.files,group.meta);}
 return groups.sort((a,b)=>natural(a.title,b.title)||recorded(a.meta.sequence,a.chapter,b.meta.sequence,b.chapter));
}
