import {unzipSync,strFromU8} from './vendor/fflate.js';
self.onmessage=({data})=>{
 try{
  let total=0,count=0;
  const entries=unzipSync(new Uint8Array(data),{filter:file=>{
   const accepted=/\.(png|jpe?g|webp|gif|avif)$/i.test(file.name)||file.name==='_reading_order.json';
   if(accepted){total+=file.originalSize;count++;if(file.originalSize>32*1024*1024||total>200*1024*1024||count>5000)throw Error('회차 파일이 너무 큽니다. PC에서 회차별로 나눠 내보내세요.')}
   return accepted;
  }});
  let metadata={};if(entries['_reading_order.json'])metadata=JSON.parse(strFromU8(entries['_reading_order.json']));delete entries['_reading_order.json'];
  const files=Object.entries(entries).map(([name,bytes])=>({name,bytes}));
  if(!files.length)throw Error('읽을 수 있는 이미지가 없습니다.');
  self.postMessage({metadata,files},files.map(f=>f.bytes.buffer));
 }catch(e){self.postMessage({error:e.message})}
};
