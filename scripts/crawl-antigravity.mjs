// crawl-antigravity.mjs — best-effort mirror of the Antigravity *CLI* docs into docs/agy/.
//
// Antigravity (antigravity.google/docs) is a client-rendered SPA: it serves no
// static markdown and an empty llms.txt, so the clean curl approach used for
// Claude/Codex (scripts/sync-cli-docs.sh) does not work. This crawler renders
// pages with a headless browser and converts the main content to markdown.
//
// Scope: the Antigravity CLI section only, anchored at /docs/cli-getting-started
// (NOT the whole Antigravity site, and NOT the Gemini CLI — see project memory).
//
// Discovery: sitemap.xml (gzip-aware) filtered to CLI paths, plus a BFS fallback
// that follows in-page links from the start page.
//
// This is the fragile piece by design. It runs as a `continue-on-error` step in
// the workflow, so if Google changes their DOM the Claude/Codex sync still
// succeeds. The CONFIG block below is meant to be tweaked when selectors drift.
//
// Deps (installed by the workflow): playwright, turndown.

import { chromium } from 'playwright';
import TurndownService from 'turndown';
import { gunzipSync } from 'node:zlib';
import { mkdir, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';

const CONFIG = {
  base: 'https://antigravity.google',
  start: '/docs/cli-getting-started',
  sitemap: '/sitemap.xml',
  // Which doc paths count as "Antigravity CLI" docs.
  pathFilter: /^\/docs\/cli(\/|-|$)/,
  outDir: 'docs/agy',
  maxPages: 100,
  navTimeoutMs: 30000,
  // First selector that matches is treated as the page's main content.
  contentSelectors: ['main', 'article', '[role="main"]', '#content', '.content', 'body'],
  // Removed from the content before conversion (chrome/navigation noise).
  stripSelectors: ['nav', 'aside', 'header', 'footer', 'script', 'style', 'noscript', 'svg'],
};

const turndown = new TurndownService({ headingStyle: 'atx', codeBlockStyle: 'fenced' });

/** Normalize to an absolute, fragment/query-free URL string, or null if off-scope. */
function normalize(href) {
  let u;
  try {
    u = new URL(href, CONFIG.base);
  } catch {
    return null;
  }
  if (u.origin !== CONFIG.base) return null;
  u.hash = '';
  u.search = '';
  let p = u.pathname.replace(/\/+$/, '');
  if (p === '') p = '/';
  if (!CONFIG.pathFilter.test(p)) return null;
  return CONFIG.base + p;
}

/** Discover CLI doc URLs from sitemap.xml (handles gzip). */
async function discoverFromSitemap() {
  const found = new Set();
  try {
    const res = await fetch(CONFIG.base + CONFIG.sitemap);
    if (!res.ok) return found;
    const buf = Buffer.from(await res.arrayBuffer());
    const isGzip = buf.length > 2 && buf[0] === 0x1f && buf[1] === 0x8b;
    const xml = (isGzip ? gunzipSync(buf) : buf).toString('utf8');
    for (const m of xml.matchAll(/<loc>\s*([^<\s]+)\s*<\/loc>/g)) {
      const n = normalize(m[1]);
      if (n) found.add(n);
    }
  } catch (err) {
    console.warn(`  sitemap discovery failed: ${err.message}`);
  }
  console.log(`  sitemap: ${found.size} CLI page(s)`);
  return found;
}

/** Discover more CLI doc URLs by following links from already-loaded pages. */
async function discoverByCrawl(page, seeds) {
  const queue = [...seeds];
  const seen = new Set(seeds);
  const start = normalize(CONFIG.base + CONFIG.start);
  if (start && !seen.has(start)) {
    seen.add(start);
    queue.push(start);
  }
  const result = new Set(seen);

  while (queue.length > 0 && result.size < CONFIG.maxPages) {
    const url = queue.shift();
    let hrefs = [];
    try {
      await page.goto(url, { waitUntil: 'networkidle', timeout: CONFIG.navTimeoutMs });
      hrefs = await page.$$eval('a[href]', (as) => as.map((a) => a.getAttribute('href')));
    } catch (err) {
      console.warn(`  crawl visit failed (${url}): ${err.message}`);
      continue;
    }
    for (const h of hrefs) {
      const n = normalize(h);
      if (n && !seen.has(n)) {
        seen.add(n);
        result.add(n);
        queue.push(n);
      }
    }
  }
  return result;
}

/** Render a single page and return { title, markdown } or null on failure. */
async function renderPage(page, url) {
  try {
    await page.goto(url, { waitUntil: 'networkidle', timeout: CONFIG.navTimeoutMs });
  } catch (err) {
    console.warn(`  render nav failed (${url}): ${err.message}`);
    return null;
  }
  // Best-effort wait for real content to mount.
  try {
    await page.waitForSelector(CONFIG.contentSelectors[0], { timeout: 5000 });
  } catch { /* fall through to selector list */ }

  const extracted = await page.evaluate((cfg) => {
    let root = null;
    for (const sel of cfg.contentSelectors) {
      const el = document.querySelector(sel);
      if (el && el.textContent && el.textContent.trim().length > 40) {
        root = el;
        break;
      }
    }
    if (!root) return null;
    const clone = root.cloneNode(true);
    for (const sel of cfg.stripSelectors) {
      clone.querySelectorAll(sel).forEach((n) => n.remove());
    }
    return { title: document.title || '', html: clone.innerHTML };
  }, CONFIG);

  if (!extracted || !extracted.html) {
    console.warn(`  no content extracted (${url})`);
    return null;
  }
  const markdown = turndown.turndown(extracted.html).trim();
  if (markdown.length < 20) {
    console.warn(`  content too thin (${url})`);
    return null;
  }
  return { title: extracted.title.trim(), markdown };
}

function relPathFor(url) {
  const p = new URL(url).pathname.replace(/\/+$/, '');
  const rel = p.replace(/^\/docs\//, '');
  return `${rel}.md`;
}

async function main() {
  const stage = `${CONFIG.outDir}.tmp`;
  console.log('Antigravity CLI docs crawl starting…');

  const browser = await chromium.launch();
  const page = await browser.newPage();

  const sitemapUrls = await discoverFromSitemap();
  const allUrls = await discoverByCrawl(page, sitemapUrls);
  const urls = [...allUrls].sort();
  console.log(`Discovered ${urls.length} Antigravity CLI page(s).`);

  if (urls.length === 0) {
    await browser.close();
    console.error('ERROR: no Antigravity CLI pages discovered; leaving docs/agy untouched.');
    process.exit(1);
  }

  await rm(stage, { recursive: true, force: true });
  await mkdir(stage, { recursive: true });

  const pages = [];
  let ok = 0;
  let fail = 0;
  for (const url of urls) {
    const rendered = await renderPage(page, url);
    if (!rendered) {
      fail += 1;
      continue;
    }
    const rel = relPathFor(url);
    const dest = path.join(stage, rel);
    await mkdir(path.dirname(dest), { recursive: true });
    const header =
      `> Source: ${url}\n` +
      '> Mirror maintained by .github/workflows/sync-cli-docs.yml — do not edit by hand.\n\n';
    const titleLine = rendered.title ? `# ${rendered.title}\n\n` : '';
    await writeFile(dest, header + titleLine + rendered.markdown + '\n', 'utf8');
    pages.push(rel);
    ok += 1;
  }

  await browser.close();

  if (ok === 0) {
    await rm(stage, { recursive: true, force: true });
    console.error('ERROR: every page failed to render; leaving docs/agy untouched.');
    process.exit(1);
  }

  const index =
    '# Antigravity CLI — mirrored docs index\n\n' +
    'Auto-generated by `.github/workflows/sync-cli-docs.yml`. Do not edit by hand.\n\n' +
    `Pages: ${pages.length}\n\n` +
    pages.sort().map((p) => `- [${p}](${p})`).join('\n') +
    '\n';
  await writeFile(path.join(stage, 'INDEX.md'), index, 'utf8');

  await rm(CONFIG.outDir, { recursive: true, force: true });
  const { rename } = await import('node:fs/promises');
  await rename(stage, CONFIG.outDir);

  console.log(`Antigravity CLI crawl done: ok=${ok} fail=${fail} -> ${CONFIG.outDir}`);
}

main().catch((err) => {
  console.error(`Antigravity crawl crashed: ${err.stack || err.message}`);
  process.exit(1);
});
