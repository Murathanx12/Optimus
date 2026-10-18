// Uses the existing OpenClaw Playwright dependency; no browser profile or session reuse.
const path = require('node:path');
const fs = require('node:fs');
const { chromium } = require(process.env.PLAYWRIGHT_CORE_PATH || path.join(process.env.APPDATA, 'npm/node_modules/openclaw/node_modules/playwright-core'));

(async () => {
  fs.mkdirSync(path.join(__dirname, 'validation'), { recursive: true });
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
  try {
    for (const [name, width, height] of [['desktop', 1440, 1100], ['mobile', 390, 1100]]) {
      const page = await browser.newPage({ viewport: { width, height } });
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(process.env.SHOWCASE_URL || require('node:url').pathToFileURL(path.join(__dirname, 'index.html')).href);
      for (const [button, expected] of [['Verify', 'Completion has to be demonstrated.'], ['Retrieve', 'Give the next assistant the relevant part.'], ['Capture', 'Save the source, not just the summary.']]) {
        await page.getByRole('button', { name: button, exact: true }).click();
        if (!await page.getByText(expected, { exact: true }).isVisible()) throw new Error(`${button} interaction failed`);
      }
      const dimensions = await page.evaluate(() => ({ viewport: innerWidth, width: document.documentElement.scrollWidth }));
      if (dimensions.width > width || errors.length) throw new Error(JSON.stringify({ name, dimensions, errors }));
      await page.screenshot({ path: path.join(__dirname, 'validation', `${name}.png`), fullPage: true });
      console.log(JSON.stringify({ name, dimensions, errors }));
      await page.close();
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
