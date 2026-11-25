/* Browser regression check for Domingo: a real browser, a real server, real clicks.
   Point it at a running server:  node tests/_browser_test.cjs http://127.0.0.1:8899
   In CI the server and the stand-in engine are started by tools/ci-run.py. */
const path = require("path");
const fs = require("fs");
const env = require("./_env.cjs");
const { chromium } = env.playwright();

const URL = env.url();
const SHOTS = env.shotsDir();
const ICON = path.join(env.ROOT, "static", "icon-192.png");
const location_origin = (URL.match(/^https?:\/\/[^/]+/) || [""])[0];
let ok = 0, fail = 0;
const check = (name, cond, detail = "") => { cond ? ok++ : fail++; console.log((cond ? "PASS  " : "FAIL  ") + name.padEnd(38) + detail); };

(async () => {
  const browser = await env.launch(chromium);
  const ctx = await browser.newContext({ viewport: { width: 1180, height: 800 }, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  const errors = [];
  page.on("console", m => { if (m.type() === "error" && !/status of 400/.test(m.text())) errors.push("console: " + m.text()); });
  page.on("pageerror", e => errors.push("pageerror: " + e.message));
  page.on("response", r => {
    // the suite probes a bad model on purpose; the engine answers that with 400
    if (r.status() === 400 && r.url().endsWith("/api/chat")) return;
    if (r.status() >= 400) errors.push("http " + r.status() + " " + r.url().replace(location_origin, ""));
  });

  await page.goto(URL, { waitUntil: "networkidle" });
  await page.waitForTimeout(900);
  const MODEL = (await page.textContent("#modelName")).trim();
  check("app boots", (await page.textContent("#status")).includes(MODEL),
    JSON.stringify(await page.textContent("#status")) + " model=" + MODEL);
  check("empty state shows", !!(await page.$("#empty")));
  await page.screenshot({ path: SHOTS + "/01-empty.png" });

  // ---------- markdown + thinking + streaming ----------
  await page.fill("#input",
    "Answer in ONE short block, no preamble, using exactly this markdown shape:\n" +
    "### Title\n\nOne sentence. Then a 3-item bullet list. Then a 2-row table with a header.\n" +
    "Then a javascript code block with 2 lines, and inline `code` in the last sentence.");
  await page.press("#input", "Enter");
  await page.waitForTimeout(1000);
  check("send becomes Stop", (await page.getAttribute("#send", "data-state")) === "stop");
  await page.screenshot({ path: SHOTS + "/02-streaming.png" });
  await page.waitForFunction(() => document.querySelector("#send").dataset.state === "send", null, { timeout: 180000 });
  await page.waitForTimeout(400);

  const a = await page.$$eval("#thread .msg", els => {
    const e = els[els.length - 1];
    return {
      code: e.querySelectorAll("pre code").length,
      lists: e.querySelectorAll("ul,ol").length,
      tables: e.querySelectorAll("table").length,
      headings: e.querySelectorAll("h1,h2,h3,h4").length,
      inlineCode: e.querySelectorAll("code:not(pre code)").length,
      copyBtns: e.querySelectorAll("[data-copy]").length,
      think: (e.querySelector("details.think .txt") || {}).textContent || "",
      thinkLabel: (e.querySelector("details.think summary") || {}).innerText || "",
      note: (e.querySelector(".foot-note") || {}).innerText || "",
      badHtml: /<script|\[object Object\]/.test(e.innerHTML),
    };
  });
  check("markdown: code block", a.code === 1, JSON.stringify(a.code));
  check("markdown: list", a.lists === 1);
  check("markdown: table", a.tables === 1);
  check("markdown: heading", a.headings >= 1);
  check("markdown: inline code", a.inlineCode >= 1);
  check("code copy button", a.copyBtns === 1);
  check("thinking captured", a.think.length > 20, a.think.length + " chars, label=" + JSON.stringify(a.thinkLabel));
  check("token/s note", /tok\/s/.test(a.note), JSON.stringify(a.note));
  check("no raw html leakage", !a.badHtml);
  await page.screenshot({ path: SHOTS + "/03-answer.png", fullPage: true });
  await page.click("#thread details.think > summary");
  await page.waitForTimeout(250);
  check("thinking expands", await page.$eval("#thread details.think", d => d.open === true));
  await page.screenshot({ path: SHOTS + "/04-thinking.png", fullPage: true });

  // ---------- sidebar ----------
  await page.click("#new");
  await page.waitForTimeout(300);
  check("new chat in sidebar", (await page.$$eval("#chats .chat-item", i => i.length)) === 2,
    JSON.stringify(await page.$$eval("#chats .chat-item b", b => b.map(x => x.textContent))));

  // ---------- settings + probe ----------
  await page.click("#settings");
  await page.waitForTimeout(350);
  await page.click("#eps .endpoint .btn");
  await page.waitForTimeout(1200);
  const probe = (await page.textContent("#eps .endpoint .st")).trim();
  check("server probe works", /^ok \d+ms$/.test(probe), JSON.stringify(probe));
  await page.screenshot({ path: SHOTS + "/06-settings.png" });
  await page.keyboard.press("Escape");
  await page.waitForTimeout(250);

  // ---------- vision with a real PNG ----------
  await page.setInputFiles("#file", ICON);
  await page.waitForTimeout(500);
  const thumbOk = await page.$eval("#atts img", i => i.complete && i.naturalWidth > 0);
  check("attachment thumbnail renders", thumbOk);
  await page.fill("#input", "One word: what is the main bright colour of the bar in this image?");
  await page.press("#input", "Enter");
  await page.waitForFunction(() => document.querySelector("#send").dataset.state === "send", null, { timeout: 180000 });
  const vision = await page.$$eval("#thread .msg", els => els[els.length - 1].innerText);
  check("vision answers about the image", /orange|amber|yellow/i.test(vision), JSON.stringify(vision.slice(0, 90)));
  await page.screenshot({ path: SHOTS + "/07-vision.png", fullPage: true });

  // ---------- persistence ----------
  const stored = await page.evaluate(() => (localStorage.getItem("domingo.chats.v1") || "").length);
  check("history written to localStorage", stored > 500, stored + " bytes");
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForTimeout(800);
  const after = await page.$$eval("#thread .msg", els => els.length);
  const chatsAfter = await page.$$eval("#chats .chat-item", els => els.length);
  check("history survives reload", after >= 2, after + " messages, " + chatsAfter + " chats in sidebar");
  const imgs = await page.$$eval("#thread .msg.user .imgs img", els => els.map(i => i.complete && i.naturalWidth > 0));
  check("image survives reload (IndexedDB)", imgs.length === 1 && imgs[0] === true, JSON.stringify(imgs));
  await page.screenshot({ path: SHOTS + "/08-reload.png" });

  // ---------- error surfacing ----------
  await page.evaluate(async () => {
    const r = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: [{ role: "user", content: "x" }], model: "does-not-exist", max_tokens: 5 }) });
    window.__code = r.status;
  });
  const badModel = await page.evaluate(() => window.__code);
  check("unknown model answered, not hung", badModel > 0 && badModel < 500, "status " + badModel + " (engine accepts any id)");

  // ---------- migration from the pre-rename app (real user data) ----------
  const legacy = await ctx.newPage();
  await legacy.goto(URL, { waitUntil: "networkidle" });
  await legacy.evaluate(() => {
    localStorage.clear();
    localStorage.setItem("slite.chats.v1", JSON.stringify([{
      id: "old1", title: "Legacy chat", created: 1, updated: Date.now(), system: "", pinned: true,
      messages: [
        { role: "user", content: "from the old app", images: [{ id: "img1", name: "x.png" }] },
        { role: "assistant", content: "hello from before", thinking: "",
          usage: { prompt_tokens: 5, completion_tokens: 7, total_tokens: 12, ms: 100 } }
      ]
    }]));
    localStorage.setItem("slite.prefs.v1", JSON.stringify({ theme: "dark", effort: "low" }));
  });
  await legacy.evaluate(() => new Promise(res => {
    const PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";
    const seed = () => {
      const r = indexedDB.open("slite", 1);
      r.onupgradeneeded = () => r.result.createObjectStore("imgs");
      r.onsuccess = () => {
        const d = r.result;
        const tx = d.transaction("imgs", "readwrite");
        tx.objectStore("imgs").put(PNG, "img1");
        tx.oncomplete = () => { d.close(); res(); };
        tx.onerror = () => { d.close(); res(); };
      };
      r.onerror = () => res();
    };
    const del = indexedDB.deleteDatabase("slite");   // start from a known state
    del.onsuccess = del.onerror = del.onblocked = seed;
  }));
  await legacy.reload({ waitUntil: "networkidle" });
  await legacy.waitForTimeout(1000);
  const legacyTitles = await legacy.$$eval("#chats .chat-item b", b => b.map(x => x.textContent));
  check("old chats carried over", legacyTitles.includes("Legacy chat"), JSON.stringify(legacyTitles));
  check("old prefs carried over", (await legacy.textContent("#effortLbl")).includes("Low"), JSON.stringify(await legacy.textContent("#effortLbl")));
  const legacyImg = await legacy.$$eval("#thread .msg.user .imgs img", els => els.map(i => i.complete && i.naturalWidth > 0));
  check("old images migrated (IndexedDB)", legacyImg.length === 1 && legacyImg[0] === true, JSON.stringify(legacyImg));
  await legacy.screenshot({ path: SHOTS + "/12-legacy.png" });
  await legacy.close();

  // ---------- the Mac case: cookies dropped, token only in localStorage ----------
  // the legacy page cleared storage, so put the token back the way a real visit does
  await page.evaluate(t => {
    const p = JSON.parse(localStorage.getItem("domingo.prefs.v1") || "{}");
    p.token = t; localStorage.setItem("domingo.prefs.v1", JSON.stringify(p));
  }, (URL.match(/[?&]t=([^&]+)/) || [])[1] || "");
  await ctx.clearCookies();
  await page.goto(URL.split("?")[0], { waitUntil: "domcontentloaded" });   // networkidle never settles after a streamed chat
  await page.waitForTimeout(900);
  const noCookie = (await page.textContent("#status")).trim();
  check("works with cookies blocked", noCookie.includes(MODEL), JSON.stringify(noCookie));
  const noCookieChat = await page.evaluate(async () => {
    const r = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json",
      "X-Domingo-Token": JSON.parse(localStorage.getItem("domingo.prefs.v1") || "{}").token || "" },
      body: JSON.stringify({ messages: [{ role: "user", content: "Reply with exactly: COOKIELESS" }],
        stream: false, max_tokens: 30, reasoning_effort: "low" }) });
    return r.status;
  });
  check("chat authenticates without cookies", noCookieChat === 200, "status " + noCookieChat);

  // ---------- sampling belongs to Strata, not to this UI ----------
  const knobs = await page.evaluate(() => ({
    sliders: document.querySelectorAll('#s-temp,#s-topp,#s-max').length,
    inDom: /temperature|top_p/i.test(document.querySelector("#dlg-settings").innerHTML) &&
           !document.querySelector("#s-sampling"),
    shown: (document.querySelector("#s-sampling") || {}).textContent || "",
    controls: (document.querySelector("#s-sampling") || { querySelectorAll: () => [] }).querySelectorAll("input,select,textarea").length,
  }));
  check("no sampling controls in the UI", knobs.sliders === 0 && !knobs.inDom, JSON.stringify(knobs.sliders));
  check("engine defaults shown read-only",
    /context/.test(knobs.shown) && knobs.controls === 0,
    JSON.stringify(knobs.shown.trim().slice(0, 78)));

  const sent = await page.evaluate(async () => {
    const orig = window.fetch;
    let body = null;
    window.fetch = (u, o) => { if (String(u).includes("/api/chat")) body = JSON.parse(o.body); return orig(u, o); };
    document.querySelector("#input").value = "Say OK.";
    document.querySelector("#composer").dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
    await new Promise(r => setTimeout(r, 900));
    window.fetch = orig;
    return body;
  });
  const banned = ["temperature", "top_p", "top_k", "min_p", "max_tokens", "n_predict", "seed", "repeat_penalty"]
    .filter(k => sent && k in sent);
  check("chat payload carries no sampling keys", sent && banned.length === 0,
    "keys: " + Object.keys(sent || {}).join(","));
  check("payload keeps model + reasoning", sent && !!sent.model && !!sent.reasoning_effort,
    "reasoning=" + (sent || {}).reasoning_effort);
  await page.waitForFunction(() => document.querySelector("#send").dataset.state === "send", null, { timeout: 180000 });

  // ---------- motion: the signature animations exist, and reduced motion kills them ----------
  const motion = await page.evaluate(() => {
    const g = document.querySelector("#aurora");
    const cs = g && getComputedStyle(g);
    const msg = document.querySelector("#thread .msg");
    return {
      aurora: !!cs && cs.display !== "none" && cs.opacity !== "0",
      blobs: document.querySelectorAll("#aurora i").length,
      msgAnim: msg ? getComputedStyle(msg).animationName : "none",
      greeting: !!document.querySelector("#empty h1 span"),
    };
  });
  check("aurora layer with drifting lights", motion.aurora && motion.blobs === 3, JSON.stringify(motion));
  check("messages animate in", motion.msgAnim !== "none", JSON.stringify(motion.msgAnim));
  const rmCtx = await browser.newContext({ reducedMotion: "reduce" });
  const rm = await rmCtx.newPage();
  await rm.goto(URL, { waitUntil: "domcontentloaded" });
  await rm.waitForTimeout(700);
  const calm = await rm.evaluate(() => {
    const h = document.querySelector("#empty h1 span");
    return { anim: h ? getComputedStyle(h).animationDuration : "?", opacity: h ? getComputedStyle(h).opacity : "?" };
  });
  check("prefers-reduced-motion is honoured", parseFloat(calm.anim) < 0.01 && calm.opacity === "1", JSON.stringify(calm));
  await rmCtx.close();

  // ---------- mobile ----------
  const m = await ctx.newPage();
  await m.setViewportSize({ width: 390, height: 780 });
  await m.goto(URL, { waitUntil: "networkidle" });
  await m.waitForTimeout(700);
  const overflow = await m.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  check("no horizontal overflow on 390px", overflow <= 0, "overflow " + overflow + "px");
  await m.screenshot({ path: SHOTS + "/09-mobile.png" });
  await m.click("#menu");
  await m.waitForTimeout(350);
  check("drawer opens on mobile", await m.evaluate(() => document.body.classList.contains("side-open")));
  await m.screenshot({ path: SHOTS + "/10-mobile-drawer.png" });

  // ---------- dark theme ----------
  const d = await ctx.newPage();
  await d.emulateMedia({ colorScheme: "dark" });
  await d.goto(URL, { waitUntil: "networkidle" });
  await d.waitForTimeout(600);
  const dark = await d.evaluate(() => ({
    body: getComputedStyle(document.body).backgroundColor,
    side: getComputedStyle(document.querySelector('#side')).backgroundColor,
    box: getComputedStyle(document.querySelector('#box')).backgroundColor,
    ink: getComputedStyle(document.body).color,
  }));
  check("true-black palette",
    dark.body === 'rgb(0, 0, 0)' && dark.side === 'rgb(10, 10, 11)' &&
    dark.box === 'rgb(21, 21, 23)' && dark.ink === 'rgb(243, 243, 244)', JSON.stringify(dark));
  await d.screenshot({ path: SHOTS + "/11-dark.png" });

  console.log("\nerrors seen:", errors.length ? JSON.stringify(errors, null, 1) : "none");
  console.log("%d passed, %d failed", ok, fail);
  await browser.close();
  process.exit(fail ? 1 : 0);
})();
