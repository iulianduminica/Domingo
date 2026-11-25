/* Screenshots of the running app, with no model calls: chrome, popovers, mobile.
   Seeded conversations are synthetic, so nothing real is published with them.
   Writes to docs/screenshots unless DOMINGO_SHOTS says otherwise. */
const env = require("./_env.cjs");
const { chromium } = env.playwright();
const URL = env.url();
const SHOTS = env.shotsDir();

(async () => {
  const browser = await env.launch(chromium);
  const ctx = await browser.newContext({ viewport: { width: 1180, height: 800 }, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  const errs = [];
  page.on("pageerror", e => errs.push(e.message));
  page.on("console", m => { if (m.type() === "error") errs.push(m.text()); });
  await page.goto(URL, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2400);

  // seed a conversation locally so the thread view is rendered, without the model
  await page.evaluate(() => {
    const chats = [{
      id: "s1", title: "Weekly routine", created: Date.now(), updated: Date.now(), system: "", pinned: false,
      messages: [
        { role: "user", content: "Give me a short weekly routine with a table and a code block.", images: [], ts: Date.now() },
        { role: "assistant", content:
          "### Routine\n\nSmall, repeatable, and easy to keep.\n\n- **Mon**: deep work block\n- **Wed**: review the week\n- **Fri**: write it down\n\n" +
          "| Day | Focus | Length |\n| --- | --- | --- |\n| Mon | Deep work | 90 min |\n| Wed | Review | 30 min |\n\n" +
          "```python\nschedule = {\"mon\": \"deep\", \"wed\": \"review\"}\nprint(schedule[\"mon\"])\n```\n\n" +
          "Keep it under `30 minutes` on review days.",
          thinking: "The user wants a compact weekly routine. I will use a heading, a bullet list, a small table, and a short code block so every markdown feature is visible in the screenshot.",
          model: "swift-iq3_s", effort: "medium", ts: Date.now(),
          usage: { prompt_tokens: 80, completion_tokens: 312, total_tokens: 392, ms: 6400 }, finish: "stop" },
        { role: "user", content: "Now the same for a morning block, with a link to [the docs](https://example.com) and a quote.", images: [], ts: Date.now() },
        { role: "assistant", content:
          "> The first hour decides the day.\n\n1. Water, no phone\n2. Ten minutes of writing\n3. One task, timed\n\nSee [the docs](https://example.com) for the timer format.",
          thinking: "A short list plus a quote.", model: "swift-iq3_s", effort: "high", ts: Date.now(),
          usage: { prompt_tokens: 140, completion_tokens: 96, total_tokens: 236, ms: 2100 }, finish: "stop" },
      ],
    }];
    localStorage.setItem("domingo.chats.v1", JSON.stringify(chats));
  });
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2400);
  await page.screenshot({ path: SHOTS + "/02-thread.png" });

  // reasoning popover
  await page.click("#effortBtn");
  await page.waitForTimeout(300);
  await page.screenshot({ path: SHOTS + "/03-reasoning.png" });
  await page.keyboard.press("Escape");

  // model popover
  await page.click("#modelBtn");
  await page.waitForTimeout(300);
  await page.screenshot({ path: SHOTS + "/08-model-menu.png" });
  await page.keyboard.press("Escape");

  // sidebar chat menu
  await page.hover("#chats .chat-item");
  await page.click('#chats .chat-item [data-act="more"]');
  await page.waitForTimeout(300);
  await page.screenshot({ path: SHOTS + "/05-chat-menu.png" });
  await page.keyboard.press("Escape");

  // settings
  await page.click("#settings");
  await page.waitForTimeout(400);
  await page.screenshot({ path: SHOTS + "/04-settings.png" });
  await page.keyboard.press("Escape");

  // empty state, composer unfocused
  await page.evaluate(() => { localStorage.setItem("domingo.chats.v1", "[]"); });
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2400);
  await page.screenshot({ path: SHOTS + "/01-empty.png" });

  // mobile
  const m = await ctx.newPage();
  await m.setViewportSize({ width: 390, height: 780 });
  await m.goto(URL, { waitUntil: "domcontentloaded" });
  await m.waitForTimeout(800);
  await m.screenshot({ path: SHOTS + "/06-mobile.png" });
  await m.click("#menu");
  await m.waitForTimeout(400);
  await m.screenshot({ path: SHOTS + "/07-mobile-drawer.png" });

  console.log("errors:", errs.length ? JSON.stringify(errs) : "none");
  await browser.close();
})();
