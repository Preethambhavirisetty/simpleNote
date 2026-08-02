/* Render each page in a real browser and fail on any console error.
   Run against a live dev server: node smoke.mjs [baseUrl] */
import { chromium } from 'playwright'

const BASE = process.argv[2] ?? 'http://localhost:5173'
const OUT = process.argv[3] ?? '/tmp/agentlog-shots'

// use the system Chrome so this needs no `playwright install` download
const browser = await chromium.launch({ channel: 'chrome' })
const page = await browser.newPage({ viewport: { width: 1440, height: 950 } })

const errors = []
page.on('console', (m) => {
  if (m.type() === 'error') errors.push(`console: ${m.text()}`)
})
page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))
page.on('requestfailed', (r) => errors.push(`requestfailed: ${r.url()}`))

async function shot(name, path, prep) {
  await page.goto(`${BASE}${path}`, { waitUntil: 'networkidle' })
  if (prep) await prep()
  await page.waitForTimeout(500)
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: false })
  console.log(`  ✓ ${name.padEnd(22)} ${path}`)
}

await shot('01-runs-light', '/')

// grab a run key from the table to visit its detail page
const runHref = await page.evaluate(() => {
  const row = document.querySelector('table.runs tbody tr')
  if (!row) return null
  row.click()
  return location.pathname
})
await page.waitForTimeout(900)
const runKey = (await page.evaluate(() => location.pathname)).split('/').pop()
console.log(`  → detail run: ${runKey}`)

await shot('02-run-detail', `/runs/${runKey}`)
await shot('03-run-detail-errors', `/runs/${runKey}`, async () => {
  const btn = page.locator('button.chip', { hasText: 'ERROR' }).first()
  if (await btn.count()) await btn.click()
})
await shot('04-stats', '/stats')

// dark mode: set the persisted preference, since a reload re-reads it
await page.evaluate(() => localStorage.setItem('theme', 'dark'))
await shot('05-stats-dark', '/stats')
await shot('06-runs-dark', '/')
await shot('07-run-detail-dark', `/runs/${runKey}`)

await browser.close()

if (errors.length) {
  console.error(`\n✗ ${errors.length} browser error(s):`)
  for (const e of [...new Set(errors)].slice(0, 20)) console.error('   ' + e)
  process.exit(1)
}
console.log(`\n✓ all pages rendered with no console errors (shots in ${OUT})`)
