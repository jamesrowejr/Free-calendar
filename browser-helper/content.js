(() => {
  const EVENT_WORDS = /\b(event|festival|concert|show|meet|meetup|cars?\s*(?:&|and)\s*coffee|cruise[- ]?in|birthday|debut|baby|feeding|keeper talk|open house|grand opening|free|admission|tickets?|party|market|movie|workshop|class|tour|demo|giveaway|beer|food|music|Saturday|Sunday|Monday|Tuesday|Wednesday|Thursday|Friday)\b/i;
  const DATE_WORDS = /\b(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\b|\b\d{1,2}[\/-]\d{1,2}(?:[\/-]\d{2,4})?\b|\b(today|tomorrow|tonight|this weekend|next weekend)\b/i;
  const TIME_WORDS = /\b\d{1,2}(?::\d{2})?\s?(?:am|pm)\b/i;

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
      if (count >= 150) break;
      const label = (el.innerText || el.getAttribute('aria-label') || '').trim().toLowerCase();
      if (label === 'see more' && visible(el)) {
        try { el.click(); count++; } catch (_) {}
      }
    }
    return count;
  }

  function canonicalPostUrl(article, platform) {
    const anchors = [...article.querySelectorAll('a[href]')];
    const rules = platform === 'instagram'
      ? [/\/p\//i, /\/reel\//i]
      : [/\/posts\//i, /\/permalink\//i, /story_fbid=/i, /\/events\/\d+/i, /\/photos\//i];
    for (const a of anchors) {
      const href = a.href || '';
      if (rules.some(r => r.test(href))) return href.split('&__cft__')[0];
    }
    return '';
  }

  function collectMedia(article) {
    const out = [];
    for (const img of [...article.querySelectorAll('img')].slice(0, 12)) {
      const alt = (img.alt || '').trim();
      const src = (img.currentSrc || img.src || '').trim();
      if (!alt && !src) continue;
      out.push({type: 'image', alt: alt.slice(0, 1000), url: src.slice(0, 4000)});
    }
    return out;
  }

  function candidateArticles(platform) {
    const selector = platform === 'instagram' ? 'article' : '[role="article"], article';
    const nodes = [...document.querySelectorAll(selector)];
    if (nodes.length) return nodes;
    return [...document.querySelectorAll('div')].filter(el => {
      const text = (el.innerText || '').trim();
      return text.length > 120 && text.length < 12000 && EVENT_WORDS.test(text) && (DATE_WORDS.test(text) || TIME_WORDS.test(text));
    }).slice(0, 80);
  }

  function scan() {
    const host = location.hostname.toLowerCase();
    const platform = host.includes('instagram.com') ? 'instagram' : host.includes('facebook.com') ? 'facebook' : '';
    if (!platform) return {error: 'Open Facebook or Instagram first.'};
    const sourceName = (document.querySelector('h1')?.innerText || document.title || '').trim().slice(0, 250);
    const sourceUrl = location.href;
    const seen = new Set();
    const captures = [];
    for (const article of candidateArticles(platform)) {
      let text = (article.innerText || '').replace(/\n{3,}/g, '\n\n').trim();
      if (text.length < 50 || text.length > 50000) continue;
      if (!EVENT_WORDS.test(text)) continue;
      if (!(DATE_WORDS.test(text) || TIME_WORDS.test(text) || /\bfree\b/i.test(text))) continue;
      const postUrl = canonicalPostUrl(article, platform);
      const key = postUrl || text.slice(0, 500);
      if (seen.has(key)) continue;
      seen.add(key);
      captures.push({platform, source_url: sourceUrl, source_name: sourceName, post_url: postUrl, text, media: collectMedia(article)});
      if (captures.length >= 50) break;
    }
    return {captures, platform, sourceName};
  }

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg?.type === 'FREECAL_EXPAND') return sendResponse({expanded: expandSeeMore()});
    if (msg?.type === 'FREECAL_SCAN') return sendResponse(scan());
  });
})();
