import { chromium } from '@playwright/test'
import { mkdir } from 'node:fs/promises'

const output = process.env.CITADEL_COCKPIT_PROOF || '/tmp/citadel-cognitive-proof'
await mkdir(output, { recursive: true })
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.CITADEL_BROWSER_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
})
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
})
const page = await context.newPage()
const consoleErrors = []
const pageErrors = []
const failedRequests = []
page.on('console', message => {
  if (message.type() === 'error') consoleErrors.push(message.text())
})
page.on('pageerror', error => pageErrors.push(error.message))
page.on('requestfailed', request => failedRequests.push(`${request.method()} ${request.url()}`))
await page.goto('http://127.0.0.1:4173', { waitUntil: 'networkidle' })
const clickFixture = label => page.evaluate(value => {
  const button = [...document.querySelectorAll('button')].find(node => node.textContent?.trim() === value)
  if (!(button instanceof HTMLButtonElement)) throw new Error(`Fixture control not found: ${value}`)
  button.click()
}, label)
const rootTop = await page.locator('[data-testid="cognitive-decision-core"]').evaluate(node => node.getBoundingClientRect().top + scrollY)
const stageStart = Math.max(0, rootTop - 45)
await page.waitForFunction(() => document.querySelector('[data-testid="cognitive-decision-core"]')?.getAttribute('data-scroll-mode') !== 'loading')
const desktopScrollMode = await page.locator('[data-testid="cognitive-decision-core"]').getAttribute('data-scroll-mode')
const desktopPinSpacers = await page.locator('.pin-spacer').count()

await page.screenshot({ path: `${output}/01-market-closed.png` })
await page.getByRole('button', { name: 'CALL', exact: true }).click()
await page.evaluate(y => scrollTo({ top: y, behavior: 'instant' }), stageStart)
await page.waitForTimeout(450)
await page.screenshot({ path: `${output}/02-call-core.png` })

let scrollFrame = 0
for (const offset of [140, 300, 500, 720, 930]) {
  await page.evaluate(y => scrollTo({ top: y, behavior: 'smooth' }), stageStart + offset)
  await page.waitForTimeout(260)
  await page.screenshot({ path: `${output}/scroll-${String(++scrollFrame).padStart(2, '0')}-${offset}.png` })
  await page.waitForTimeout(290)
}
await page.screenshot({ path: `${output}/03-settled-call.png` })

await clickFixture('Qwen receipt')
let previousDelay = 0
for (const delay of [80, 180, 320, 620, 1180]) {
  await page.waitForTimeout(delay - previousDelay)
  await page.screenshot({ path: `${output}/qwen-beam-${String(delay).padStart(4, '0')}ms.png` })
  previousDelay = delay
}
await clickFixture('Gemini receipt')
previousDelay = 0
for (const delay of [80, 180, 320, 620, 1180]) {
  await page.waitForTimeout(delay - previousDelay)
  await page.screenshot({ path: `${output}/gemini-beam-${String(delay).padStart(4, '0')}ms.png` })
  previousDelay = delay
}

await clickFixture('Disagreement')
await page.waitForTimeout(550)
await page.screenshot({ path: `${output}/06-model-disagreement.png` })
await clickFixture('Reversal watch')
await page.waitForTimeout(550)
await page.screenshot({ path: `${output}/07-reversal-watch.png` })
await clickFixture('World fresh')
await clickFixture('External refresh')
await page.waitForTimeout(350)
await page.screenshot({ path: `${output}/08-world-receipt.png` })
await page.waitForTimeout(1100)

await page.getByRole('button', { name: 'Five hypotheses' }).click()
await page.waitForTimeout(350)
await page.screenshot({ path: `${output}/09-drawer-open.png`, fullPage: true })

for (const [name, label] of [
  ['10-put-ready', 'PUT'], ['11-call-developing', 'CALL developing'],
  ['12-put-developing', 'PUT developing'], ['13-no-trade', 'NO TRADE'],
  ['14-gemini-unavailable', 'Gemini unavailable'], ['15-world-unavailable', 'World unavailable'],
]) {
  await clickFixture(label)
  await page.evaluate(y => scrollTo({ top: y, behavior: 'instant' }), stageStart + 930)
  await page.waitForTimeout(170)
  await page.screenshot({ path: `${output}/${name}.png` })
}

const before = await page.getByLabel('Animation proof').textContent()
await clickFixture('Same receipt')
await page.waitForTimeout(250)
const after = await page.getByLabel('Animation proof').textContent()
await clickFixture('World unavailable')
await page.waitForTimeout(1400)
const beforeUnverifiedRefresh = await page.getByLabel('Animation proof').textContent()
await clickFixture('External refresh')
await page.waitForTimeout(250)
const afterUnverifiedRefresh = await page.getByLabel('Animation proof').textContent()
await page.evaluate(y => scrollTo({ top: y, behavior: 'instant' }), stageStart)
await page.waitForTimeout(100)
await page.evaluate(y => scrollTo({ top: y, behavior: 'instant' }), stageStart + 930)
await page.waitForTimeout(100)
await page.evaluate(y => scrollTo({ top: y, behavior: 'instant' }), stageStart)
await page.waitForTimeout(100)
const pinSpacersAfterFastReverse = await page.locator('.pin-spacer').count()
await context.close()

const staticContext = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' })
const staticPage = await staticContext.newPage()
await staticPage.goto('http://127.0.0.1:4173', { waitUntil: 'networkidle' })
await staticPage.getByRole('button', { name: 'CALL', exact: true }).click()
await staticPage.screenshot({ path: `${output}/16-protected-boundaries-reduced-motion.png`, fullPage: true })
const reducedScrollMode = await staticPage.locator('[data-testid="cognitive-decision-core"]').getAttribute('data-scroll-mode')
const reducedPinSpacers = await staticPage.locator('.pin-spacer').count()
await staticContext.close()

const narrowContext = await browser.newContext({ viewport: { width: 900, height: 900 } })
const narrowPage = await narrowContext.newPage()
await narrowPage.goto('http://127.0.0.1:4173', { waitUntil: 'networkidle' })
const narrowScrollMode = await narrowPage.locator('[data-testid="cognitive-decision-core"]').getAttribute('data-scroll-mode')
const narrowPinSpacers = await narrowPage.locator('.pin-spacer').count()
await narrowContext.close()

console.log(JSON.stringify({
  output,
  before,
  after,
  duplicateReceiptReplayed: before !== after,
  unverifiedWorldReceiptAnimated: beforeUnverifiedRefresh !== afterUnverifiedRefresh,
  desktopScrollMode,
  desktopPinSpacers,
  pinSpacersAfterFastReverse,
  reducedScrollMode,
  reducedPinSpacers,
  narrowScrollMode,
  narrowPinSpacers,
  consoleErrors,
  pageErrors,
  failedRequests,
}))
await browser.close()
