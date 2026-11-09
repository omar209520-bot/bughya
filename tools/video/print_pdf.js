// يطبع كلَّ ملفّ HTML في المجلّد إلى PDF بالحجم المحدَّد في @page.
const { chromium } = require('playwright');
const fs = require('fs'), path = require('path');
(async () => {
  const dir = process.argv[2];
  const b = await chromium.launch();
  const p = await b.newPage();
  for (const f of fs.readdirSync(dir).filter(f => f.endsWith('.html'))) {
    await p.goto('file://' + path.resolve(dir, f));
    await p.evaluate(() => document.fonts.ready);
    await p.pdf({ path: path.join(dir, f.replace(/\.html$/, '.pdf')), preferCSSPageSize: true, printBackground: true });
  }
  await b.close();
})();
