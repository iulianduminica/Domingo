/* Geometry probes: control overflow, and the left-edge grid across the app. */
const env = require("./_env.cjs");
const { chromium } = env.playwright();
const URL = env.url();

(async () => {
  const browser = await env.launch(chromium);
  for (const [label, w, h] of [["desktop", 1180, 800], ["phone", 390, 780]]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h } });
    const page = await ctx.newPage();
    await page.goto(URL, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(900);

    const bar = await page.evaluate(() => {
      const rect = el => (el ? Math.round(el.getBoundingClientRect().width) : null);
      const svgs = [...document.querySelectorAll("#send svg")];
      const send = document.querySelector("#send");
      const b = document.querySelector("#bar");
      const box = b.getBoundingClientRect();
      return {
        sendIcons: svgs.map(s => ({ display: getComputedStyle(s).display, w: rect(s) })),
        sendBox: { w: rect(send), h: Math.round(send.getBoundingClientRect().height) },
        barOverflow: b.scrollWidth > b.clientWidth + 1,
        clipped: [...b.children].map(c => ({ id: c.id || String(c.className),
          right: Math.round(c.getBoundingClientRect().right) }))
          .filter(x => x.right > Math.round(box.right) + 1),
        effortLabel: document.querySelector("#effortLbl").textContent,
        pageOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      };
    });
    console.log(label + " bar:", JSON.stringify(bar));

    // the left-edge grid: what column does each element actually start in?
    const edges = await page.evaluate(() => {
      const x = sel => { const e = document.querySelector(sel); return e ? Math.round(e.getBoundingClientRect().left) : null; };
      const side = document.querySelector("#side").getBoundingClientRect().width;
      return {
        sidebarWidth: Math.round(side),
        brandMark: x("#side .brand img"),
        rowIcon: Math.round(document.querySelector("#new .i").getBoundingClientRect().left),
        searchIcon: Math.round(document.querySelector(".search .i").getBoundingClientRect().left),
        groupHeader: x("#chats .grp"),
        chatText: x("#chats .chat-item b"),
        modelText: Math.round(document.querySelector("#modelName").getBoundingClientRect().left),
        greeting: x("#empty h1"),
        chips: x("#empty .chip"),
        composerBox: x("#box"),
        inputText: Math.round(document.querySelector("#input").getBoundingClientRect().left),
        plusBtn: Math.round(document.querySelector("#att").getBoundingClientRect().left),
      };
    });
    console.log(label + " edges:", JSON.stringify(edges));

    // the settings dialog grid (the sidebar is a drawer on phones)
    if (w < 881) { await page.click("#menu"); await page.waitForTimeout(400); }
    await page.click("#settings");
    await page.waitForTimeout(400);
    const dlg = await page.evaluate(() => {
      const r = el => { const b = el.getBoundingClientRect(); return { l: Math.round(b.left), r: Math.round(b.right), h: Math.round(b.height) }; };
      const q = s => r(document.querySelector(s));
      const btns = [...document.querySelectorAll("#eps .btn, #ep-add")].map(b => ({ t: b.textContent, ...r(b) }));
      const hist = [...document.querySelectorAll(".btnrow .btn")].map(b => ({ t: b.textContent, ...r(b) }));
      return {
        dialog: r(document.querySelector("#dlg-settings")),
        label: q("#dlg-settings .field > label"),
        textarea: q("#s-system"),
        select: q("#s-effort"),
        tokenInput: q("#s-token"),
        endpoint: q("#eps .endpoint"),
        addInput: q("#ep-url"),
        sampling: q("#s-sampling"),
        buttons: btns,
        history: hist,
        historyRows: new Set(hist.map(b => b.h === 0 ? 0 : Math.round(b.l + b.r))).size,
      };
    });
    console.log(label + " dialog:", JSON.stringify(dlg, null, 0));
    await ctx.close();
  }
  await browser.close();
})();
