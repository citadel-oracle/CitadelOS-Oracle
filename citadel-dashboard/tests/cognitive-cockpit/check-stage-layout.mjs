// Isolated visual regression for the real Oracle global footer rule.
// No production store, API or model adapter is connected here.
import { chromium } from '@playwright/test'
import assert from 'node:assert/strict'
const browser = await chromium.launch({ headless: true,
  executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' })
try {
  for (const width of [1440, 900, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 1000 }, reducedMotion: 'reduce' })
    await page.goto('http://127.0.0.1:4173', { waitUntil: 'networkidle' })
    await page.addStyleTag({ content: 'footer { padding-top:16px; margin-top:36px; border-top:1px solid grey; letter-spacing:.1em }' })
    const result = await page.locator('[data-testid="cognitive-decision-core"]').evaluate(root => {
      const rect = selector => root.querySelector(selector).getBoundingClientRect()
      return {
        margin: getComputedStyle(root.querySelector('[data-model] > footer')).marginTop,
        padding: getComputedStyle(root.querySelector('[data-model] > footer')).paddingTop,
        worldTop: rect('[aria-label="Global context brief"]').top,
        tensionBottom: rect('[data-motion-stage="TENSION"]').bottom,
        overflows: root.scrollWidth > root.clientWidth,
      }
    })
    assert.equal(result.margin, '0px')
    assert.equal(result.padding, '0px')
    assert.ok(result.worldTop >= result.tensionBottom, `World Context overlap at ${width}`)
    assert.equal(result.overflows, false, `Horizontal overflow at ${width}`)
    console.log(JSON.stringify({ width, ...result, result: 'PASS' }))
    await page.close()
  }
} finally { await browser.close() }
