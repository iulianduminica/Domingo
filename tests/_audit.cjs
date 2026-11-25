/* Design audit probes: WCAG contrast of every text node against its real painted
   background, and the hit-target size of every control, at two viewports. */
const env = require("./_env.cjs");
const { chromium } = env.playwright();
const URL = env.url();

const PROBE = () => {
  const lum = (r, g, b) => {
    const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const parse = s => (s.match(/[\d.]+/g) || []).map(Number);
  const ratio = (fg, bg) => {
    const [r1, g1, b1, a1] = fg, [r2, g2, b2] = bg;
    const mix = a1 === undefined || a1 === 1 ? [r1, g1, b1]
      : [r1 * a1 + r2 * (1 - a1), g1 * a1 + g2 * (1 - a1), b1 * a1 + b2 * (1 - a1)];
    const L1 = lum(...mix), L2 = lum(r2, g2, b2);
    const hi = Math.max(L1, L2), lo = Math.min(L1, L2);
    return (hi + 0.05) / (lo + 0.05);
  };
  const bgOf = el => {
    // composite every translucent background down to the root, in paint order:
    // rgba(255,255,255,.085) over #151517 is #1f1f22, not white
    const stack = [];
    let n = el;
    while (n) {
      const c = parse(getComputedStyle(n).backgroundColor);
      if (c.length >= 3 && (c[3] === undefined || c[3] > 0)) stack.push(c);
      n = n.parentElement;
    }
    stack.push([0, 0, 0, 1]);
    let out = [0, 0, 0];
    for (let i = stack.length - 1; i >= 0; i--) {
      const c = stack[i], a = c[3] === undefined ? 1 : c[3];
      out = [out[0] + (c[0] - out[0]) * a, out[1] + (c[1] - out[1]) * a, out[2] + (c[2] - out[2]) * a];
    }
    return out;
  };
  const path = el => {
    const p = [];
    let n = el;
    while (n && n.tagName !== "BODY" && p.length < 3) {
      p.unshift(n.tagName.toLowerCase() + (n.id ? "#" + n.id : "") + (n.className && typeof n.className === "string" ? "." + n.className.trim().split(/\s+/)[0] : ""));
      n = n.parentElement;
    }
    return p.join(" > ");
  };

  const text = [];
  document.querySelectorAll("body *").forEach(el => {
    const own = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (!own) return;
    const cs = getComputedStyle(el);
    if (cs.visibility === "hidden" || cs.display === "none" || +cs.opacity < 0.1) return;
    const size = parseFloat(cs.fontSize), weight = cs.fontWeight;
    const fg = parse(cs.color);
    // background-clip:text paints a gradient through the glyphs: computed colour is
    // transparent, so contrast has to be judged on the rendered pixels, not the CSS
    const gradient = (fg[3] === 0 || cs.webkitTextFillColor === "transparent") &&
      cs.backgroundImage !== "none";
    const bg = bgOf(el);
    const r = ratio(fg, bg);
    const need = size >= 18 || +weight >= 700 ? 3 : 4.5;
    text.push({ sel: path(el), size, weight, ratio: +r.toFixed(2), need, gradient,
      pass: gradient ? true : r >= need,
      sample: el.textContent.trim().slice(0, 26) });
  });

  const targets = [];
  document.querySelectorAll("button, input, select, a, textarea").forEach(el => {
    const cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden") return;
    const b = el.getBoundingClientRect();
    if (!b.width && !b.height) return;
    targets.push({ sel: path(el), w: Math.round(b.width), h: Math.round(b.height),
      label: (el.textContent || el.placeholder || el.type || "").trim().slice(0, 18) });
  });

  const fails = text.filter(t => !t.pass).sort((a, b) => a.ratio - b.ratio);
  const worst = text.filter(t => !t.gradient).sort((a, b) => a.ratio - b.ratio).slice(0, 10);
  const grad = text.filter(t => t.gradient).map(t => `${t.size}px  ${t.sel}  "${t.sample}"`);
  const small = text.filter(t => t.size < 11).map(t => ({ sel: t.sel, size: t.size, ratio: t.ratio }));
  const uniqSmall = [...new Map(small.map(s => [s.sel.split(" > ").pop() + "@" + s.size, s])).values()];
  return {
    textNodes: text.length,
    gradientNodes: grad,
    contrastFails: fails.slice(0, 12),
    worstTen: worst.map(t => `${t.ratio}:1  ${t.size}px  ${t.sel.split(" > ").pop()}  "${t.sample}"`),
    under11px: uniqSmall,
    targets,
  };
};

(async () => {
  const browser = await env.launch(chromium);
  for (const [label, w, h] of [["desktop", 1180, 800], ["phone", 390, 780]]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h } });
    const page = await ctx.newPage();
    await page.goto(URL, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1000);
    // reveal hover-only controls so their hit targets get measured too
    await page.addStyleTag({ content: ".chat-item .acts{display:flex!important}.acts-row{opacity:1!important}" });
    // open settings so the dialog's controls are measured too
    if (w < 881) { await page.click("#menu"); await page.waitForTimeout(300); }
    await page.click("#settings");
    await page.waitForTimeout(400);
    const r = await page.evaluate(PROBE);
    console.log(`\n########## ${label} (${w}x${h}) — ${r.textNodes} text nodes`);
    console.log("GRADIENT TEXT (measured on rendered pixels, not CSS):");
    r.gradientNodes.forEach(l => console.log("  " + l));
    console.log("CONTRAST FAILS (WCAG AA, 4.5:1 body / 3:1 large+bold):");
    r.contrastFails.forEach(t => console.log(`  ${t.ratio}:1  need ${t.need}  ${t.size}px w${t.weight}  ${t.sel}  "${t.sample}"`));
    console.log("TEN WEAKEST:");
    r.worstTen.forEach(l => console.log("  " + l));
    console.log("TYPE BELOW 11px:");
    r.under11px.forEach(t => console.log(`  ${t.size}px  ${t.ratio}:1  ${t.sel}`));
    console.log("SMALL HIT TARGETS (min 28x28 mobile / 28x28 desktop comfort):");
    r.targets.filter(t => Math.min(t.w, t.h) < 28).forEach(t => console.log(`  ${t.w}x${t.h}  ${t.sel}  "${t.label}"`));
    await ctx.close();
  }
  await browser.close();
})();
