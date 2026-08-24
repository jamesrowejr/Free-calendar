const API='https://free-calendar-production.up.railway.app/api/social/capture';
const statusEl=document.getElementById('status');
function setStatus(text){statusEl.textContent=text;}
async function activeTab(){const [tab]=await chrome.tabs.query({active:true,currentWindow:true});return tab;}
async function ensureScript(tabId){try{await chrome.scripting.executeScript({target:{tabId},files:['content.js']});}catch(e){throw new Error('Could not access this page. Open Facebook or Instagram and try again.');}}
async function send(tabId,type){return await chrome.tabs.sendMessage(tabId,{type});}
async function upload(captures){
  if(!captures?.length){setStatus('No useful social posts found. Scroll farther or use Deep scan.');return;}
  setStatus(`Collected ${captures.length} posts. Sending to Free Calendar…`);
  const resp=await fetch(API,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({captures})});
  const data=await resp.json();
  if(!resp.ok) throw new Error(data?.error||`Server returned ${resp.status}`);
  const ai=data.social_ai_enabled?` ${data.queued_for_ai||0} queued for AI interpretation.`:' AI interpretation is waiting for an API key.';
  setStatus(`Saved ${data.saved} new posts; ${data.duplicates} duplicates skipped.${ai}`);
}

document.getElementById('expand').onclick=async()=>{
  try{setStatus('Expanding…');const tab=await activeTab();await ensureScript(tab.id);const result=await send(tab.id,'FREECAL_EXPAND');setStatus(`Expanded ${result?.expanded||0} “See more” controls.`);}catch(e){setStatus(`Error: ${e.message}`);}
};

document.getElementById('scan').onclick=async()=>{
  try{setStatus('Scanning loaded posts…');const tab=await activeTab();await ensureScript(tab.id);await send(tab.id,'FREECAL_EXPAND');await new Promise(r=>setTimeout(r,500));const result=await send(tab.id,'FREECAL_SCAN');if(result?.error)throw new Error(result.error);await upload(result?.captures||[]);}catch(e){setStatus(`Error: ${e.message}`);}
};

document.getElementById('deep').onclick=async()=>{
  try{setStatus('Deep scanning… this takes about 10 seconds.');const tab=await activeTab();await ensureScript(tab.id);const result=await send(tab.id,'FREECAL_DEEP_SCAN');if(result?.error)throw new Error(result.error);await upload(result?.captures||[]);}catch(e){setStatus(`Error: ${e.message}`);}
};
