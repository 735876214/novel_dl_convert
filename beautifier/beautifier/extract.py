"""从页面里提取 DOM 快照（计算样式 + 几何 + 有效背景色）。

返回结构（dict）:
{
  url, title, lang, viewport, scroll, metaViewport, colorScheme,
  elements: [ {selector, tag, text, textLength, rect, styles, bg, interactive, inlineInText, clipped} ],
  headings: [ {level, text, selector} ],
  imagesMissingAlt: [selector],
  totalElements, sampledSkipped
}
"""

from __future__ import annotations

from typing import Any, Dict, List

EXTRACT_JS = r"""
() => {
  const MAX = 600;
  const SKIP_TAGS = ['script','style','noscript','meta','link','br','hr','svg','path','defs','g','canvas','iframe','template'];
  const TRANSPARENT = 'rgba(0, 0, 0, 0)';
  const esc = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : String(s).replace(/[^\w-]/g, (c) => '\\' + c);

  const selectorOf = (el) => {
    if (!el || el.nodeType !== 1) return '';
    if (el.id) return '#' + esc(el.id);
    const parts = [];
    let cur = el;
    let depth = 0;
    while (cur && cur.nodeType === 1 && depth < 3) {
      let seg = cur.tagName.toLowerCase();
      if (cur.id) { parts.unshift('#' + esc(cur.id)); break; }
      const cls = (typeof cur.className === 'string' ? cur.className : '')
        .trim().split(/\s+/).filter(Boolean)
        .filter((c) => c.length < 40 && !/^(css|sc-|jsx)/.test(c)).slice(0, 2);
      if (cls.length) seg += '.' + cls.map(esc).join('.');
      const parent = cur.parentElement;
      if (parent) {
        const same = Array.prototype.filter.call(parent.children, (c) => c.tagName === cur.tagName);
        if (same.length > 1) seg += ':nth-of-type(' + (Array.prototype.indexOf.call(same, cur) + 1) + ')';
      }
      parts.unshift(seg);
      cur = cur.parentElement;
      depth += 1;
    }
    return parts.join(' > ');
  };

  const effectiveBg = (el) => {
    let cur = el;
    let guard = 0;
    while (cur && cur.nodeType === 1 && guard < 12) {
      const cs = getComputedStyle(cur);
      if (cs.backgroundImage && cs.backgroundImage !== 'none') {
        return { color: null, gradient: true, from: selectorOf(cur) };
      }
      const bg = cs.backgroundColor;
      if (bg && bg !== TRANSPARENT && bg !== 'transparent') {
        return { color: bg, gradient: false, from: selectorOf(cur) };
      }
      cur = cur.parentElement;
      guard += 1;
    }
    return { color: 'rgb(255, 255, 255)', gradient: false, from: 'html' };
  };

  const STYLE_KEYS = [
    'color','backgroundColor','fontSize','fontWeight','lineHeight','letterSpacing','fontFamily',
    'textAlign','paddingTop','paddingRight','paddingBottom','paddingLeft','marginTop','marginBottom',
    'borderTopLeftRadius','boxShadow','display','opacity','overflow','overflowX',
    'outlineWidth','outlineStyle','outlineColor','textDecorationLine','borderTopWidth','position'
  ];

  const all = document.querySelectorAll('body *');
  const elements = [];
  let skipped = 0;

  for (let i = 0; i < all.length; i++) {
    const el = all[i];
    const tag = el.tagName.toLowerCase();
    if (SKIP_TAGS.indexOf(tag) >= 0) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) continue;
    const rect = el.getBoundingClientRect();
    if (rect.width < 1 || rect.height < 1) continue;

    let directText = '';
    for (let k = 0; k < el.childNodes.length; k++) {
      const node = el.childNodes[k];
      if (node.nodeType === 3) directText += node.nodeValue;
    }
    directText = directText.replace(/\s+/g, ' ').trim();

    if (elements.length >= MAX) { skipped += 1; continue; }

    const styles = {};
    for (let s = 0; s < STYLE_KEYS.length; s++) {
      const key = STYLE_KEYS[s];
      styles[key] = cs[key];
    }

    const parentText = el.parentElement ? (el.parentElement.textContent || '').trim().length : 0;
    elements.push({
      selector: selectorOf(el),
      tag: tag,
      text: directText.slice(0, 120),
      textLength: directText.length,
      rect: { x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height) },
      styles: styles,
      bg: effectiveBg(el),
      interactive: /^(a|button|input|select|textarea|summary)$/.test(tag)
        || el.getAttribute('role') === 'button'
        || (el.tabIndex >= 0 && tag !== 'body' && tag !== 'div'),
      inlineInText: tag === 'a' && parentText > directText.length + 20,
      clipped: el.scrollHeight > el.clientHeight + 4 && cs.overflow !== 'visible'
    });
  }

  const headings = Array.prototype.map.call(
    document.querySelectorAll('h1,h2,h3,h4,h5,h6'),
    (h) => ({ level: parseInt(h.tagName.slice(1), 10), text: (h.textContent || '').trim().slice(0, 60), selector: selectorOf(h) })
  );

  const missingAlt = Array.prototype.filter.call(
    document.querySelectorAll('img'),
    (im) => !im.hasAttribute('alt') || (im.getAttribute('alt') || '').trim() === ''
  ).slice(0, 50).map((im) => selectorOf(im));

  const docEl = document.documentElement;
  const metaEl = document.querySelector('meta[name="viewport"]');

  return {
    url: location.href,
    title: document.title,
    lang: docEl.lang || null,
    viewport: { width: window.innerWidth, height: window.innerHeight },
    scroll: { width: docEl.scrollWidth, height: docEl.scrollHeight, horizontal: docEl.scrollWidth > window.innerWidth + 1 },
    metaViewport: metaEl ? metaEl.getAttribute('content') : null,
    colorScheme: getComputedStyle(docEl).getPropertyValue('color-scheme') || null,
    elements: elements,
    headings: headings,
    imagesMissingAlt: missingAlt,
    totalElements: all.length,
    sampledSkipped: skipped
  };
}
"""


def extract_snapshot(page) -> Dict[str, Any]:
    return page.evaluate(EXTRACT_JS)


def has_text(el: Dict[str, Any]) -> bool:
    return bool(el.get("text"))


def text_elements(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [e for e in snapshot.get("elements", []) if has_text(e)]
