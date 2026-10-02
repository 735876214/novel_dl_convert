// diag-narrow.js - find leaf boxes that render as a tall narrow column (= CJK text
// broken one character per line) and report the CSS that decides line breaking.
// Run through:  $js = Get-Content -Raw .codebuddy\tools\diag-narrow.js; agent-browser eval $js
// (passing a variable avoids the tool layer eating double quotes in the command text)
(function () {
  var out = [], all = document.querySelectorAll('*');
  for (var i = 0; i < all.length && out.length < 6; i++) {
    var e = all[i];
    if (e.children.length) continue;
    var t = (e.textContent || '').trim();
    if (t.length < 2) continue;
    var r = e.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;
    if (r.width < 46 && r.height >= 60) {
      var cs = getComputedStyle(e);
      var p = e.parentElement;
      var pcs = p ? getComputedStyle(p) : null;
      out.push({
        tag: e.tagName,
        txt: t.slice(0, 14),
        w: Math.round(r.width),
        h: Math.round(r.height),
        ws: cs.whiteSpace,
        wb: cs.wordBreak,
        ow: cs.overflowWrap,
        lb: cs.lineBreak,
        wm: cs.writingMode,
        cls: (typeof e.className === 'string' ? e.className : '').slice(0, 80),
        parTag: p ? p.tagName : '',
        parW: p ? Math.round(p.getBoundingClientRect().width) : null,
        parOvX: pcs ? pcs.overflowX : null,
        parWs: pcs ? pcs.whiteSpace : null,
        parCls: p && typeof p.className === 'string' ? p.className.slice(0, 60) : ''
      });
    }
  }
  var as = document.querySelector('aside');
  var mn = document.querySelector('main');
  return JSON.stringify({
    vw: innerWidth,
    sh: document.documentElement.scrollWidth,
    bodyWordBreak: getComputedStyle(document.body).wordBreak,
    bodyOverflowWrap: getComputedStyle(document.body).overflowWrap,
    asideW: as ? Math.round(as.getBoundingClientRect().width) : null,
    mainW: mn ? Math.round(mn.getBoundingClientRect().width) : null,
    tall: out
  });
})()
