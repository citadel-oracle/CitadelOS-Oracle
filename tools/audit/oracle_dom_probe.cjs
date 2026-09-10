const { chromium } = require('../../citadel-dashboard/node_modules/playwright')

async function main() {
  const url = process.argv[2] || 'http://127.0.0.1:3000/oracle'
  const timeoutMs = Number(process.argv[3] || 30000)
  const screenshotPath = process.argv[4] || ''
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1680, height: 1050 } })
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: timeoutMs })
    await page.waitForSelector('[data-citadel-field]', { timeout: timeoutMs })
    await page.waitForTimeout(6000)
    const fields = await page.locator('[data-citadel-field]').evaluateAll((nodes) => nodes.map((node) => ({
      field_id: node.getAttribute('data-citadel-field'),
      rendered_value: (node.textContent || '').trim().replace(/\s+/g, ' '),
      status: node.getAttribute('data-citadel-status'),
      revision: node.getAttribute('data-citadel-revision'),
    })))
    if (screenshotPath) {
      await page.screenshot({ path: screenshotPath, fullPage: true })
    }
    process.stdout.write(JSON.stringify({ url, fields }))
  } finally {
    await browser.close()
  }
}

main().catch((error) => {
  process.stderr.write(String(error && error.stack ? error.stack : error))
  process.exit(2)
})
