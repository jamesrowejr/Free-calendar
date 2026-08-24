const API='https://free-calendar-production.up.railway.app/api/social/capture';
chrome.runtime.onMessage.addListener((msg,_sender,sendResponse)=>{
  if(msg?.type!=='FREECAL_AUTO_UPLOAD') return;
  const captures=Array.isArray(msg.captures)?msg.captures.slice(0,40):[];
  if(!captures.length){sendResponse({ok:true,saved:0});return;}
  fetch(API,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({captures})})
    .then(async r=>({ok:r.ok,data:await r.json()}))
    .then(x=>sendResponse(x.data))
    .catch(e=>sendResponse({ok:false,error:e.message}));
  return true;
});
