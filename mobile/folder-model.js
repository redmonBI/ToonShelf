import {natural} from './model.js';
export function folderGroups(files){
 const groups=new Map();
 for(const f of files){const parts=(f.webkitRelativePath||f.name).replaceAll('\\','/').split('/');if(parts.some(p=>p==='..')||parts.some(p=>p.startsWith('.')||['state','Source','Vendor','Updates','PreviousVersion'].includes(p)))continue;if(!/\.(png|jpe?g|webp|gif|avif)$/i.test(f.name))continue;
 const title=parts.length>=4?parts[1]:parts[0],chapter=parts.length>=3?parts.at(-2):'1화',k=title+'\u0000'+chapter;
 if(!groups.has(k))groups.set(k,{title,chapter,files:[]});groups.get(k).files.push(f);
 }
 return [...groups.values()].sort((a,b)=>natural(a.title,b.title)||natural(a.chapter,b.chapter)).map(g=>({...g,files:g.files.sort((a,b)=>natural(a.name,b.name))}));
}
