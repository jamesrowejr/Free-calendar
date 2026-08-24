const API='https://free-calendar-production.up.railway.app/api/social/capture';
const statusEl=document.getElementById('status');
function setStatus(text){statusEl.textContent=text;}
async function activeTab(){const [tab]=await chrome.tabs.query({active:true,currentWindow:true});return tab;}
async function ensureScript(tabId){try{await chrome.scripting.executeScript({target:{tabId},files:['content.js']});}catch(e){throw new Error('Could not access this page. Open Facebook or Instagram and try again.');}}
async function send(tabId,type){return await chrome.tabs.sendMessage(tabId,{type});}

document.getElementById('expand').onclick=async()=>{
  try{setStatus('Expanding…');const tab=await activeTab();await ensureScript(tab.id);const result=await send(tab.id,'FREECAL_EXPAND');setStatus(`Expanded ${result?.expanded||0} “See more” controls.`);}catch(e){setStatus(`Error: ${e.message}`);}
};

document.getElementById('scan').onclick=async()=>{
  try{
    setStatus('Scanning loaded posts…');
    const tab=await activeTab();
    await ensureScript(tab.id);
    await send(tab.id,'FREECAL_EXPAND');
    await new Promise(r=>setTimeout(r,650));
    const result=await send(tab.id,'FREECAL_SCAN');
    if(result?.error) throw new Error(result.error);
    const captures=result?.captures||[];
    if(!captures.length){setStatus('No event-like posts found in the currently loaded content. Scroll farther, then scan again.');return;}
    setStatus(`Found ${captures.length} likely posts. Sending…`);
    const resp=await fetch(API,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({captures})});
    const data=await resp.json();
    if(!resp.ok) throw new Error(data?.error||`Server returned ${resp.status}`);
    setStatus(`Captured ${data.saved} new social posts; ${data.duplicates} duplicates skipped. ${data.social?.captures||0} total stored.`);
  }catch(e){setStatus(`Error: ${e.message}`);}
};
