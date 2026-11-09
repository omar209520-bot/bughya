// يسجّل الفيديو التعريفيّ لـ«بُغية» من واجهته الحقيقيّة: Chromium بلا نافذة، ومؤشّرٌ ظاهر، وهالةٌ صفراء عند كلّ نقرة،
// وعنوانٌ عربيٌّ قصير لكلّ خطوة. يحفظ الإطاراتِ (JPEG) وأوقاتَها وأوقاتَ النقرات، ثمّ يجمعها build_video.py.
// الاستعمال: node record.js <مجلّد_الإطارات> <ملفّ_الفصل_التجريبيّ.docx> [المنفذ]
const { chromium } = require('playwright');
const fs = require('fs'), path = require('path');

const OUT = path.resolve(process.argv[2]);
const CHAPTER = path.resolve(process.argv[3]);
const PORT = process.argv[4] || '8777';
const URL = `http://127.0.0.1:${PORT}/`;
const LOGO = 'data:image/png;base64,' + fs.readFileSync(path.join(__dirname, '../../assets/bughya.png')).toString('base64');
fs.mkdirSync(OUT, { recursive: true });

const OVERLAY_CSS = `
/* علامةُ ⏎ بين أسطر المقتطف تُرسم في لينكس فوق أوّل حرفٍ من السطر (خطٌّ بديل)، فتُخفى في التسجيل وحده */
.sn .nl{font-size:0}
#vx-cur{position:fixed;left:0;top:0;width:calc(30px / var(--vz));height:calc(30px / var(--vz));z-index:2147483646;pointer-events:none;
  transform-origin:0 0;filter:drop-shadow(0 calc(2px / var(--vz)) calc(3px / var(--vz)) #0007)}
#vx-rip{position:fixed;inset:0;z-index:2147483645;pointer-events:none}
.vx-r{position:absolute;border-radius:50%;background:radial-gradient(circle,#ffd54acc 0%,#ffd54a88 45%,#ffd54a00 72%);
  border:calc(3px / var(--vz)) solid #f5c518;transform:translate(-50%,-50%) scale(.2);opacity:1;
  width:calc(78px / var(--vz));height:calc(78px / var(--vz));animation:vxr .75s ease-out forwards}
@keyframes vxr{to{transform:translate(-50%,-50%) scale(1.15);opacity:0}}
#vx-cap{position:fixed;left:50%;bottom:calc(46px / var(--vz));transform:translateX(-50%);z-index:2147483644;pointer-events:none;
  direction:rtl;white-space:nowrap;font:700 calc(40px / var(--vz))/1.5 "Noto Naskh Arabic",Amiri,serif;color:#fff;
  background:#0a2c21e6;border-bottom:calc(4px / var(--vz)) solid #d4a843;padding:calc(10px / var(--vz)) calc(40px / var(--vz)) calc(14px / var(--vz));
  border-radius:calc(10px / var(--vz));box-shadow:0 calc(8px / var(--vz)) calc(30px / var(--vz)) #0006;opacity:0;transition:opacity .45s}
#vx-cap.on{opacity:1}
#vx-card{position:fixed;inset:0;z-index:2147483643;display:none;flex-direction:column;align-items:center;justify-content:center;
  background:radial-gradient(ellipse at 50% 40%,#1f5a43 0%,#0a2c21 70%);direction:rtl;color:#f3ead2;text-align:center;opacity:0;transition:opacity .8s}
#vx-card.on{opacity:1}
#vx-card img{width:calc(250px / var(--vz));height:calc(250px / var(--vz));border-radius:calc(48px / var(--vz));box-shadow:0 calc(16px / var(--vz)) calc(50px / var(--vz)) #0008}
#vx-card .t{font:700 calc(110px / var(--vz))/1.35 BRuqaa,"Noto Naskh Arabic",serif;color:#e3c069;margin:calc(26px / var(--vz)) 0 0}
#vx-card .t span{font:700 calc(60px / var(--vz))/1.4 "Noto Naskh Arabic",serif;color:#f3ead2}
#vx-card .s{font:500 calc(38px / var(--vz))/1.7 "Noto Naskh Arabic",serif;color:#e8e1cc;margin-top:calc(14px / var(--vz))}
#vx-card .l{width:calc(120px / var(--vz));height:calc(3px / var(--vz));background:#d4a843;margin:calc(26px / var(--vz)) auto 0}
#vx-paste{position:fixed;left:50%;top:calc(170px / var(--vz));transform:translateX(-50%);z-index:2147483644;pointer-events:none;direction:rtl;
  width:calc(1240px / var(--vz));background:#fffdf6;color:#1b2a22;border:calc(2px / var(--vz)) solid #d4a843;border-radius:calc(10px / var(--vz));
  box-shadow:0 calc(10px / var(--vz)) calc(40px / var(--vz)) #0007;padding:calc(18px / var(--vz)) calc(30px / var(--vz));
  font:calc(30px / var(--vz))/1.8 Amiri,"Noto Naskh Arabic",serif;opacity:0;transition:opacity .4s}
#vx-paste.on{opacity:1}
#vx-paste b{display:block;font:700 calc(22px / var(--vz)) "Noto Naskh Arabic",serif;color:#7a5b16;margin-bottom:calc(4px / var(--vz))}
`;
const CURSOR_SVG = `<svg viewBox="0 0 24 24" width="100%" height="100%"><path d="M3 2 L3 20.5 L7.6 16.4 L10.6 23 L13.9 21.6 L10.9 15 L17.2 15 Z"
  fill="#fff" stroke="#111" stroke-width="1.5" stroke-linejoin="round"/></svg>`;

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1, locale: 'ar' });
  await ctx.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: URL.slice(0, -1) });
  const page = await ctx.newPage();
  await page.addInitScript(() => {
    try {
      localStorage.setItem('bughya-updchk', String(Date.now()));   // لا سؤالَ عن التحديث أثناء التسجيل
      localStorage.setItem('bughya-theme', 'light');
      localStorage.setItem('bughya-flow', '0');                     // يبدأ العارضُ بالنصّ المتّصل
      localStorage.setItem('bughya-zoom', '1.47');   // حجمُ الواجهة كما تبدو على شاشة 1440×810 بتكبيرها المعتاد
    } catch (e) {}
  });
  await page.goto(URL);
  await page.waitForTimeout(1200);

  // حالُ المكتبة قبل التسجيل: أصنافٌ لخمسة كتب، ويبقى «اجتماع الجيوش» بلا صنفٍ ليُختار أمام المشاهد
  await page.evaluate(async () => {
    const post = (u, b) => fetch(u, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }).then(r => r.json());
    const cats = await fetch('/api/cats').then(r => r.json());
    if (!cats.includes('الفتاوى')) await post('/api/cats', { cats: [...cats, 'الفتاوى'] });
    const books = await fetch('/api/books').then(r => r.json());
    for (const b of books) {
      const c = /فتاوى/.test(b.title) ? 'الفتاوى' : /اجتماع الجيوش/.test(b.title) ? '' : 'العقيدة';
      await post('/api/book-cat', { b: b.id, fann: c });
    }
  });
  await page.reload();
  await page.waitForTimeout(1200);

  await page.evaluate(([css, svg, logo]) => {
    const z = parseFloat(document.documentElement.style.zoom) || 1;
    document.documentElement.style.setProperty('--vz', z);
    const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
    const mk = (id, html) => { const e = document.createElement('div'); e.id = id; e.innerHTML = html || ''; document.body.appendChild(e); return e; };
    mk('vx-card'); mk('vx-paste'); mk('vx-cap'); mk('vx-rip'); const c = mk('vx-cur', svg);
    window.__vz = z; window.__cx = 960; window.__cy = 1000;
    c.style.left = (window.__cx / z) + 'px'; c.style.top = (window.__cy / z) + 'px';
    window.__logo = logo;
    // حركةٌ ناعمة للمؤشّر (ease-in-out)
    window.__move = (x, y, ms) => new Promise(res => {
      const x0 = window.__cx, y0 = window.__cy, t0 = performance.now();
      const ease = t => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
      const step = now => {
        const t = Math.min(1, (now - t0) / ms), k = ease(t);
        window.__cx = x0 + (x - x0) * k; window.__cy = y0 + (y - y0) * k;
        c.style.left = (window.__cx / z) + 'px'; c.style.top = (window.__cy / z) + 'px';
        if (t < 1) requestAnimationFrame(step); else res();
      };
      requestAnimationFrame(step);
    });
    window.__ripple = () => {
      const r = document.createElement('div'); r.className = 'vx-r';
      r.style.left = (window.__cx / z) + 'px'; r.style.top = (window.__cy / z) + 'px';
      document.getElementById('vx-rip').appendChild(r); setTimeout(() => r.remove(), 900);
      c.animate([{ transform: 'scale(1)' }, { transform: 'scale(.82)' }, { transform: 'scale(1)' }], { duration: 220 });
    };
  }, [OVERLAY_CSS, CURSOR_SVG, LOGO]);

  // ── التقاطُ الإطارات
  const cdp = await ctx.newCDPSession(page);
  const frames = [];
  let fi = 0;
  cdp.on('Page.screencastFrame', async ({ data, metadata, sessionId }) => {
    const name = `f${String(fi++).padStart(6, '0')}.jpg`;
    fs.writeFileSync(path.join(OUT, name), Buffer.from(data, 'base64'));
    frames.push({ name, t: metadata.timestamp });
    try { await cdp.send('Page.screencastFrameAck', { sessionId }); } catch (e) {}
  });
  const clicks = [];
  const now = () => Date.now() / 1000;
  const wait = ms => page.waitForTimeout(ms);

  // ── أدوات المشهد
  const caption = async (text, hold = 0) => {
    await page.evaluate(t => {
      const e = document.getElementById('vx-cap');
      if (!t) { e.classList.remove('on'); return; }
      if (e.classList.contains('on') && e.textContent !== t) {
        e.classList.remove('on'); setTimeout(() => { e.textContent = t; e.classList.add('on'); }, 420);
      } else { e.textContent = t; e.classList.add('on'); }
    }, text);
    if (hold) await wait(hold);
  };
  const center = async (sel, dx = 0, dy = 0) => {
    const el = typeof sel === 'string' ? page.locator(sel).first() : sel;
    await el.scrollIntoViewIfNeeded();
    const b = await el.boundingBox();
    return { x: b.x + b.width / 2 + dx, y: b.y + b.height / 2 + dy };
  };
  const moveTo = async (target, ms) => {
    const p = target.x !== undefined ? target : await center(target);
    const d = await page.evaluate(() => [window.__cx, window.__cy]);
    const dist = Math.hypot(p.x - d[0], p.y - d[1]);
    ms = ms || Math.max(450, Math.min(1100, 350 + dist * 0.75));
    await page.mouse.move(p.x, p.y, { steps: 8 });
    await page.evaluate(([x, y, ms]) => window.__move(x, y, ms), [p.x, p.y, ms]);
    return p;
  };
  const clickAt = async (target, after = 700) => {
    const p = await moveTo(target);
    await wait(180);
    clicks.push(now());
    await page.evaluate(() => window.__ripple());
    await page.mouse.click(p.x, p.y);
    await wait(after);
  };
  const typeText = async (sel, text, keep) => {
    if (!keep) await page.locator(sel).fill('');
    for (const ch of text) { await page.keyboard.type(ch); await wait(ch === ' ' ? 140 : 95); }
  };
  const selectOpt = async (sel, value, after = 900) => {
    await clickAt(sel, 350);
    await page.keyboard.press('Escape').catch(() => {});
    await (typeof sel === 'string' ? page.locator(sel).first() : sel).selectOption(value);
    await wait(after);
  };
  const card = async (html, ms) => {
    await page.evaluate(h => { const c = document.getElementById('vx-card'); c.innerHTML = h.replace('LOGO', window.__logo);
      c.style.display = 'flex'; requestAnimationFrame(() => requestAnimationFrame(() => c.classList.add('on'))); }, html);
    await wait(ms);
  };
  const uncard = async () => {
    await page.evaluate(() => { const c = document.getElementById('vx-card'); c.classList.remove('on'); setTimeout(() => c.style.display = 'none', 850); });
    await wait(900);
  };

  await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 92, maxWidth: 1920, maxHeight: 1080, everyNthFrame: 1 });
  const t0 = now();

  // ١. بطاقةُ العنوان
  await card(`<img src="LOGO"><div class="t">بُغية <span>— باحثٌ في مكتبتك</span></div><div class="l"></div>
    <div class="s">قارئٌ لكتبك على جهازك: تبحث فيها وتنقل منها بعزوٍ كامل</div>`, 5200);
  await uncard();
  await wait(600);

  // ٢. أضف كتبًا
  await caption('أضف كتبك إلى مكتبتك');
  await clickAt('header nav button[data-p=welcome]', 1100);
  await caption('اسحب كتبك أو مجلّدًا إلى هذه المساحة');
  await moveTo('#dz'); await wait(2200);
  await caption('أو اختر مجلّدًا فتُقرأ كتبه من مكانها');
  await moveTo('#pickdir'); await wait(2400);

  // ٣. كتبي
  await caption('كتبي: رفٌّ بأغلفة كتبك');
  await clickAt('header nav button[data-p=books]', 2400);
  await caption('اختر لكلّ كتابٍ صنفَه');
  const catSel = page.locator('#btab select.cat.none').first();
  await selectOpt(catSel, 'العقيدة', 1800);
  await caption('ثمّ اعرض كتب صنفٍ واحد');
  await clickAt('#bchips [data-chip="الفتاوى"]', 2000);
  await clickAt('#bchips [data-chip="العقيدة"]', 2000);
  await clickAt('#bchips .chip >> nth=0', 1500);

  // ٤. البحث
  await caption('ابحث في كتبك بكلمةٍ أو عبارة');
  await clickAt('header nav button[data-p=search]', 700);
  await clickAt('#q', 300);
  await typeText('#q', 'توحيد العبادة');
  await wait(500);
  await clickAt('#sf .btn', 2600);
  await caption('النتائج بعزوٍ كامل: الكتاب والجزء والصفحة');
  await moveTo('#results .card .ct >> nth=0'); await wait(2400);
  await caption('وعلى الجانب: الكتب التي ورد فيها لفظك');
  await moveTo('#facet h3'); await wait(2000);
  await caption('اختر كتابًا لتحصر البحث فيه');
  await clickAt('#facet input[data-b] >> nth=2', 2400);
  await caption('ومن خيارات البحث: البحث في صنفٍ واحد');
  await clickAt('details.more summary', 1200);
  await moveTo('#fann'); await wait(800);
  await selectOpt('#fann', 'العقيدة', 1600);
  await clickAt('details.more summary', 900);

  // ٥. عارضُ الصفحة
  await caption('انقر عنوان النتيجة لتفتح صفحتها');
  await clickAt('#results .card .ct >> nth=0', 2200);
  await caption('نصُّ الصفحة وصورتُها جنبًا إلى جنب');
  await clickAt('#pvimg', 2800);
  await caption('اعرض أسطر الصفحة كما في الكتاب');
  await clickAt('#pvflow', 2200);
  await caption('أو نصًّا متّصلًا يسهل نقله');
  await clickAt('#pvflow', 1800);
  await caption('حدِّد جملةً، ثمّ انسخها مع عزوها');
  // التحديدُ: يتحرّك المؤشّرُ على الجملة، ويتّسع التحديدُ كلمةً كلمة
  const sel = await page.evaluate(() => {
    const target = 'إفراد الله سبحانه وتعالى بالعبادة، وترك عبادة ما سواه';
    const root = document.querySelector('#pv .txt');
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node; while ((node = walker.nextNode())) { const i = node.data.indexOf(target); if (i >= 0) {
      window.__selNode = node; window.__selFrom = i; window.__selTo = i + target.length;
      const r = document.createRange(); r.setStart(node, i); r.setEnd(node, i + 1); const a = r.getBoundingClientRect();
      r.setStart(node, i + target.length - 1); r.setEnd(node, i + target.length); const b = r.getBoundingClientRect();
      return { x0: a.right * window.__vz, y0: (a.top + a.height / 2) * window.__vz, x1: b.left * window.__vz, y1: (b.top + b.height / 2) * window.__vz,
               words: target.split(' ').length };
    } }
    return null;
  });
  if (sel) {
    await moveTo({ x: sel.x0 + 4, y: sel.y0 });
    await wait(300);
    const steps = 14;
    for (let k = 1; k <= steps; k++) {
      await page.evaluate(([k, steps]) => {
        const n = window.__selNode, a = window.__selFrom, b = window.__selTo;
        const end = Math.round(a + (b - a) * k / steps);
        const r = document.createRange(); r.setStart(n, a); r.setEnd(n, end);
        const s = getSelection(); s.removeAllRanges(); s.addRange(r);
      }, [k, steps]);
      await page.evaluate(([x, y]) => window.__move(x, y, 80), [sel.x0 + (sel.x1 - sel.x0) * k / steps, sel.y0 + (sel.y1 - sel.y0) * k / steps]);
    }
    await wait(900);
    await clickAt('#pvcopy', 900);
    const copied = await page.evaluate(() => navigator.clipboard.readText().catch(() => ''));
    await page.evaluate(t => { const e = document.getElementById('vx-paste');
      e.innerHTML = '<b>ما يُلصق في رسالتك:</b>'; e.appendChild(document.createTextNode(t)); e.classList.add('on'); }, copied);
    await caption('يُنسخ النصّ ومعه عزوه كاملًا');
    await wait(4200);
    await page.evaluate(() => document.getElementById('vx-paste').classList.remove('on'));
  }
  await wait(500);
  await clickAt('#pvclose', 1000);

  // ٦. ألفاظٌ مجاورة
  await caption('ألفاظٌ مجاورة: ما يقترن بلفظٍ في كتبك');
  await clickAt('header nav button[data-p=jiwar]', 800);
  await clickAt('#jq', 300);
  await typeText('#jq', 'التوحيد');
  await wait(400);
  await clickAt('#jf .btn', 3600);
  await moveTo('#jres'); await wait(1500);

  // ٧. مجموعات الألفاظ
  await caption('مجموعات الألفاظ: ابحث بألفاظٍ عدّةٍ معًا');
  await clickAt('header nav button[data-p=groups]', 800);
  await clickAt('#gname', 200);
  await typeText('#gname', 'أقسام التوحيد');
  await clickAt('#gterms', 200);
  for (const [i, line] of ['توحيد الربوبية', 'توحيد الألوهية', 'توحيد الأسماء والصفات'].entries()) {
    if (i) await page.keyboard.press('Enter');
    await typeText('#gterms', line, true);
  }
  await wait(500);
  await clickAt('#gsave', 1800);
  await moveTo('#glist'); await wait(1600);
  await caption('واعرف مواضعها في كتبك بنقرة');
  await clickAt('#glist [data-run] >> nth=0', 3200);

  // ٨. مدقّق الإحالات
  await caption('مدقّق الإحالات: يتحقّق من نقول رسالتك');
  await clickAt('header nav button[data-p=audit]', 1600);
  await moveTo('#adz'); await wait(1800);
  await caption('اختر فصلًا من رسالتك (ملفّ وورد)');
  await moveTo('#apick'); await wait(600);
  clicks.push(now()); await page.evaluate(() => window.__ripple());
  // يُسلَّم الملفُّ إلى خانة الاختيار نفسها (setInputFiles لا يقبل اسمًا عربيًّا)، فيجري ما يجري عند اختياره باليد
  await page.evaluate(([b64, name]) => {
    const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
    const dt = new DataTransfer();
    dt.items.add(new File([bytes], name, { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }));
    const inp = document.querySelector('#ainp'); inp.files = dt.files; inp.dispatchEvent(new Event('change', { bubbles: true }));
  }, [fs.readFileSync(CHAPTER).toString('base64'), path.basename(CHAPTER)]);
  await page.waitForFunction(() => /صدّر|إكسل|مطابق|لم يوجد/.test(document.querySelector('#ares').textContent), null, { timeout: 120000 });
  await wait(1200);
  await caption('لكلّ نقلٍ حكمٌ: مطابق، أو صفحةٌ تخالف، أو لم يوجد');
  await moveTo('#ares'); await wait(1200);
  await page.evaluate(() => document.querySelector('#ares').scrollIntoView({ behavior: 'smooth', block: 'start' }));
  await wait(4200);

  // ٩. حالُ المكتبة، وعن البرنامج
  await caption('حال المكتبة: ما قُرئ من كتبك');
  await clickAt('header nav button[data-p=status]', 3000);
  await caption('عن البرنامج');
  await clickAt('#abt', 3400);
  await clickAt('#abtx', 900);
  await caption('');
  await wait(700);

  // ١٠. الخاتمة
  await card(`<img src="LOGO"><div class="t">بُغية</div><div class="l"></div><div class="s">الإصدار ٠٫٩٫٢</div>`, 5200);

  await cdp.send('Page.stopScreencast');
  const t1 = now();
  fs.writeFileSync(path.join(OUT, 'timeline.json'), JSON.stringify({ t0, t1, frames, clicks }, null, 1));
  await browser.close();
  console.log(`frames ${frames.length}, clicks ${clicks.length}, ${(t1 - t0).toFixed(1)}s`);
})().catch(e => { console.error(e); process.exit(1); });
