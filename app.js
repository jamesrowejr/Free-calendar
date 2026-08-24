let events = [];
let sources = [];
let reviewRows = [];
let fbStats = {captures:0,event_candidates:0,published:0,review:0,ignored:0,duplicate_sightings:0};
let maxCost = 20;
let hideUnknown = false;

const ymd = d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
const nowLocal = new Date();
const today = ymd(nowLocal);
let cursor = new Date(nowLocal.getFullYear(), nowLocal.getMonth(), 1, 12, 0, 0);
let selected = today;

const fmtDate = d => new Intl.DateTimeFormat('en-US',{weekday:'long',month:'long',day:'numeric'}).format(d);
const fmtTime = iso => iso ? new Intl.DateTimeFormat('en-US',{hour:'numeric',minute:'2-digit'}).format(new Date(iso)) : 'Time TBA';
const escapeHtml = (value='') => String(value).replace(/[&<>'"]/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
function allowed(e){ if(e.cost == null) return !hideUnknown; return e.cost <= maxCost; }
function occursOn(e,date){ const start=e.start.slice(0,10); const end=(e.end||e.start).slice(0,10); return date>=start && date<=end; }
function eventsOn(date){ return events.filter(e => occursOn(e,date) && allowed(e)).sort((a,b)=>b.score-a.score); }
function monthEvents(){ return events.filter(e => { const d=new Date(e.start); return d.getFullYear()===cursor.getFullYear() && d.getMonth()===cursor.getMonth() && allowed(e); }).sort((a,b)=>new Date(a.start)-new Date(b.start)); }
function renderCalendar(){document.getElementById('monthLabel').textContent=new Intl.DateTimeFormat('en-US',{month:'long',year:'numeric'}).format(cursor);const cal=document.getElementById('calendar');cal.innerHTML='';const first=new Date(cursor.getFullYear(),cursor.getMonth(),1);const gridStart=new Date(first);gridStart.setDate(1-first.getDay());for(let i=0;i<42;i++){const d=new Date(gridStart);d.setDate(gridStart.getDate()+i);const key=ymd(d);const ev=eventsOn(key);const cell=document.createElement('div');cell.className='day'+(d.getMonth()!==cursor.getMonth()?' outside':'')+(key===selected?' selected':'')+(key===today?' today':'');const previews=ev.slice(0,2).map(x=>`<div class="mini-event ${x.cost===0?'':'cheap'}" title="${escapeHtml(x.title)}">${escapeHtml(x.title)}</div>`).join('');cell.innerHTML=`<span class="num">${d.getDate()}</span><div class="day-events">${previews}${ev.length>2?`<div class="more">+${ev.length-2} more</div>`:''}</div>`;cell.onclick=()=>{selected=key;render();};cal.appendChild(cell);}}
function badges(e){const out=[];if(e.cost===0)out.push('<span class="badge free">FREE</span>');if((e.categories||[]).includes('cars'))out.push('<span class="badge car">CAR EVENT</span>');if((e.perks||[]).some(p=>/bite|food|cocktail|drink|wine|beer|refreshment/i.test(p)))out.push('<span class="badge food">FOOD / DRINK</span>');(e.perks||[]).slice(0,3).forEach(p=>out.push(`<span class="badge">${escapeHtml(String(p).toUpperCase())}</span>`));return out.join('');}
function renderList(all=false){const list=document.getElementById('eventList');const chosen=all?monthEvents():eventsOn(selected);document.getElementById('selectedDate').textContent=all?new Intl.DateTimeFormat('en-US',{month:'long',year:'numeric'}).format(cursor):fmtDate(new Date(`${selected}T12:00:00`));if(!chosen.length){list.innerHTML='<div class="empty">No matching indexed events on this date.</div>';return;}list.innerHTML=chosen.map(e=>{const sourceLinks=(e.sources||[]).map(s=>`<a target="_blank" rel="noreferrer" href="${escapeHtml(s.url||'')}">${escapeHtml(s.name||'Source')}</a>`).join(' · ');const timeRange=e.allDay?'Multi-day · times vary':(e.end?`${fmtTime(e.start)}–${fmtTime(e.end)}`:fmtTime(e.start));return `<article class="card"><div class="card-top"><div><h3>${escapeHtml(e.title)}</h3><div class="meta">${timeRange}<br>${escapeHtml(e.location)}<br><strong>${escapeHtml(e.costLabel)}</strong></div></div><div class="score">${Number(e.score||0).toFixed(1)}</div></div><div class="badges">${badges(e)}</div><p class="description">${escapeHtml(e.description||'')}</p><div class="sources">Sources: ${sourceLinks}</div></article>`;}).join('');}
function renderSummary(){const free=events.filter(e=>e.cost===0).length;const tierOne=sources.filter(s=>s.tier===1).length;document.getElementById('summary').innerHTML=`<strong>${events.length}</strong> indexed events · <strong>${free}</strong> free<br><strong>${sources.length}</strong> sources · <strong>${tierOne}</strong> Tier-1`;}
function renderReview(){const target=document.getElementById('facebookImports');if(target)target.innerHTML='<div class="import-empty">Hosted Facebook ingestion will be reconnected after deployment and persistent storage are in place.</div>';}
function render(){renderCalendar();renderList(false);renderSummary();renderReview();}
async function loadData(){try{const [er,sr]=await Promise.all([fetch('/api/events',{cache:'no-store'}),fetch('/api/sources',{cache:'no-store'})]);events=await er.json();sources=await sr.json();render();}catch(err){document.getElementById('eventList').innerHTML=`<div class="error">Could not load event data: ${escapeHtml(err.message)}</div>`;}}
document.getElementById('prevMonth').onclick=()=>{cursor=new Date(cursor.getFullYear(),cursor.getMonth()-1,1,12);selected=ymd(cursor);render();};
document.getElementById('nextMonth').onclick=()=>{cursor=new Date(cursor.getFullYear(),cursor.getMonth()+1,1,12);selected=ymd(cursor);render();};
document.getElementById('todayBtn').onclick=()=>{const d=new Date();cursor=new Date(d.getFullYear(),d.getMonth(),1,12);selected=ymd(d);render();};
document.getElementById('showAll').onclick=()=>renderList(true);
document.querySelectorAll('input[name="cost"]').forEach(r=>r.onchange=e=>{maxCost=Number(e.target.value);render();});
document.getElementById('hideUnknown').onchange=e=>{hideUnknown=e.target.checked;render();};
loadData();
