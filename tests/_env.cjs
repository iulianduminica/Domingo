/* Shared test environment: find Playwright, find a browser, resolve paths.
   The suites carry no absolute machine paths, so they run in CI and on any OS.

   Overrides:
     DOMINGO_PLAYWRIGHT     module path or package name for Playwright
     DOMINGO_BROWSER        absolute path to a Chromium/Edge/Chrome executable
     DOMINGO_SHOTS          where screenshots are written
     DOMINGO_URL            app URL when argv[2] is absent
*/
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");

function playwright() {
  const tries = [];
  if (process.env.DOMINGO_PLAYWRIGHT) tries.push(process.env.DOMINGO_PLAYWRIGHT);
  tries.push("playwright", "playwright-core");
  for (const m of tries) {
    try { return require(m); } catch (e) { /* not installed here, keep looking */ }
  }
  if (process.env.DOMINGO_PLAYWRIGHT_DIR) {
    try { return require(path.join(process.env.DOMINGO_PLAYWRIGHT_DIR, "playwright-core")); } catch (e) {}
  }
  throw new Error("Playwright is not installed. Run: npm install\n" +
    "  (or set DOMINGO_PLAYWRIGHT to the module path of an existing install)");
}

async function launch(chromium) {
  const opts = [];
  if (process.env.DOMINGO_BROWSER) opts.push({ executablePath: process.env.DOMINGO_BROWSER });
  opts.push({}, { channel: "msedge" }, { channel: "chrome" });
  const errs = [];
  for (const o of opts) {
    try {
      return await chromium.launch(Object.assign({ headless: true }, o));
    } catch (e) {
      errs.push((o.channel || o.executablePath || "bundled chromium") + ": " + String(e.message).split("\n")[0]);
    }
  }
  throw new Error("no browser could start. " + errs.join(" | ") +
    "\n  install one with: npx playwright install chromium");
}

function shotsDir() {
  const d = process.env.DOMINGO_SHOTS || path.join(ROOT, "docs", "screenshots");
  fs.mkdirSync(d, { recursive: true });
  return d;
}

function url() {
  return process.argv[2] || process.env.DOMINGO_URL || "http://127.0.0.1:8899";
}

module.exports = { playwright, launch, shotsDir, url, ROOT };
