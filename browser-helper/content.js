(() => {
  if (window.__freecalCollectorLoaded) return;
  window.__freecalCollectorLoaded = true;

  const EVENT_WORDS = /\b(event|festival|concert|show|meet|meetup|cars?\s*(?:&|and)\s*coffee|cruise[- ]?in|autocross|birthday|debut|baby|feeding|keeper talk|open house|grand opening|free|admission|tickets?|party|market|movie|tour|demo|giveaway|beer|food|music|Saturday|Sunday|Monday|Tuesday|Wednesday|Thursday|Friday)\b/i;
  const DATE_WORDS = /\b(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\b|\b\d{1,2}[\/-]\d{1,2}(?:[\/-]\d{2,4})?\b|\b(today|tomorrow|tonight|this weekend|next weekend)\b/i;
  const TIME_WORDS = /\b\d{1,2}(?::\d{2})?\s?(?:am|pm)\b/i;

  const sleep = ms => new Promise(r => setTimeout(r, ms));

  function visible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  }

  function expandSeeMore() {
    let count = 0;
    const nodes = [...document.querySelectorAll('div[role="button"],span[role="button"],button')];
    for (const el of nodes) {
      if (count >= 200) break;
      const label = (el.innerText || el.getAttribute('aria-label') || '').trim().toLowerCase();
      if ((label === 'see more' || label === 'more') && visible(el)) {
        try { el.click(); count++; } catch (_) {}
      }
    }
    return count;
  }

  function canonicalPostUrl(article, platform) {
    const anchors = [...article.querySelectorAll('a[href]')];
    const rules = platform === 'instagram'
      ? [/\/p\//i, /\/reel\//i]
      : [/\/posts\//i, /\/permalink\//i, /story_fbid=/i, /\/events\/\d+/i, /\/photos\//i, /\/videos\//i];
    for (const a of anchors) {
      const href = a.href || '';
      if (rules.some(r => r.test(href))) return href.split('&__cft__')[0].split('?__cft__')[0];
    }
    return '';
  }

  function collectMedia(article) {
    const out = [];
    const seen = new Set();
    for (const img of [...article.querySelectorAll('img')].slice(0, 16)) {
      const alt = (img.alt || '').trim();
      const src = (img.currentSrc || img.src || '').trim();
      if (!alt && !src) continue;
      if (src && seen.has(src)) continue;
      if (src) seen.add(src);
      out.push({type: 'image', alt: alt.slice(0, 1800), url: src.slice(0, 5000)});
    }
    return out;
  }

  function candidateArticles(platform) {
    const selector = platform === 'instagram' ? 'article' : '[role="article"], article';
    const nodes = [...document.querySelectorAll(selector)];
    if (nodes.length) return nodes;
    return [...document.querySelectorAll('div')].filter(el => {
      const text = (el.innerText || '').trim();
      const hasImage = !!el.querySelector('img');
      return text.length > 80 && text.length < 20000 && (hasImage || EVENT_WORDS.test(text));
    }).slice(0, 100);
  }

  function scan() {
    const host = location.hostname.toLowerCase();
    const platform = host.includes('instagram.com') ? 'instagram' : host.includes('facebook.com') ? 'facebook' : '';
    if (!platform) return {error: 'Open Facebook or Instagram first.'};
    const sourceName = (document.querySelector('h1')?.innerText || document.querySelector('header h2')?.innerText || document.title || '').trim().slice(0, 250);
    const sourceUrl = location.href;
    const seen = new Set();
    const captures = [];
    for (const article of candidateArticles(platform)) {
      const media = collectMedia(article);
      let text = (article.innerText || '').replace(/\n{3,}/g, '\n\n').trim();
      if (text.length < 35 || text.length > 50000) continue;
      const strongSignal = EVENT_WORDS.test(text) || DATE_WORDS.test(text) || TIME_WORDS.test(text) || /\bfree\b/i.test(text);
      // On a page/group the user deliberately chose to scan, image-bearing posts are valuable evidence too.
      if (!strongSignal && !media.length) continue;
      const postUrl = canonicalPostUrl(article, platform);
      const key = postUrl || `${text.slice(0, 700)}|${media[0]?.url || ''}`;
      if (seen.has(key)) continue;
      seen.add(key);
      captures.push({platform, source_url: sourceUrl, source_name: sourceName, post_url: postUrl, text, media});
      if (captures.length >= 60) break;
    }
    return {captures, platform, sourceName};
  }

  async function deepScan() {
    const startY = window.scrollY;
    const all = new Map();
    let expanded = 0;
    for (let step = 0; step < 10; step++) {
      expanded += expandSeeMore();
      await sleep(300);
      const result = scan();
      if (result.error) return result;
      for (const cap of result.captures || []) {
        const key = cap.post_url || `${cap.text.slice(0, 700)}|${cap.media?.[0]?.url || ''}`;
        if (!all.has(key) || cap.text.length > all.get(key).text.length) all.set(key, cap);
      }
      window.scrollBy({top: Math.max(window.innerHeight * 1.45, 900), behavior: 'instant'});
      await sleep(800);
    }
    window.scrollTo({top: startY, behavior: 'instant'});
    return {captures: [...all.values()].slice(0, 100), expanded, deep: true};
  }

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg?.type === 'FREECAL_EXPAND') { sendResponse({expanded: expandSeeMore()}); return; }
    if (msg?.type === 'FREECAL_SCAN') { sendResponse(scan()); return; }
    if (msg?.type === 'FREECAL_DEEP_SCAN') {
      deepScan().then(sendResponse).catch(err => sendResponse({error: err.message}));
      return true;
    }
  });
})();
