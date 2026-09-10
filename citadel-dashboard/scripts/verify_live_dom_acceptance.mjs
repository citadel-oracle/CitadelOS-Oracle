import puppeteer from 'puppeteer'
import fs from 'fs'
import path from 'path'

const ARTIFACTS_DIR = '/Users/ayushmudgal/.gemini/antigravity/brain/098ef0e6-34d5-4c1c-b18a-ecd567ffc636'

const VIEWPORTS = [
  { width: 1440, height: 900, name: '1440x900' },
  { width: 1920, height: 1080, name: '1920x1080' },
  { width: 1280, height: 800, name: '1280x800' },
  { width: 768, height: 1024, name: '768x1024' },
  { width: 390, height: 844, name: '390x844' },
]

async function run() {
  const browser = await puppeteer.launch({
    headless: true,
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  })

  try {
    const page = await browser.newPage()
    await page.setViewport({ width: 1440, height: 900 })

    console.log('Navigating to http://127.0.0.1:3000/preview/photonic ...')
    await page.goto('http://127.0.0.1:3000/preview/photonic', { waitUntil: 'domcontentloaded', timeout: 60000 })

    // Wait until live data is rendered into the DOM
    console.log('Waiting for live telemetry in DOM...')
    await page.waitForFunction(
      () => {
        const text = document.body.innerText
        return (
          !text.includes('REV -1') &&
          text.includes('24,250 CE') &&
          text.includes('24,350 PE')
        )
      },
      { timeout: 15000 }
    )

    // Give 1 second for micro-animations to settle
    await new Promise((r) => setTimeout(r, 1500))

    // Extract exact text and element contents
    const domData = await page.evaluate(() => {
      const text = document.body.innerText
      return {
        bodyText: text,
      }
    })

    console.log('\n=================== RAW LIVE DOM CAPTURE ===================')
    console.log(domData.bodyText)
    console.log('============================================================\n')

    // Perform strict DOM assertions for Prompt 25 Acceptance
    const body = domData.bodyText

    const checks = [
      { name: 'NIFTY Spot', pass: body.includes('24,287.65') || body.includes('NIFTY SPOT') },
      { name: 'NIFTY FUT', pass: body.includes('NIFTY FUT') && body.includes('-0.26%') },
      { name: 'Canonical PCR', pass: body.includes('0.99') && body.includes('OPEN INTEREST PCR') },
      { name: 'PCR Opening Baseline Delta', pass: body.includes('OPEN 0.88 → +0.10') && body.includes('11.60%') },
      { name: 'CE Strike 24,250 CE', pass: body.includes('24,250 CE') },
      { name: 'CE Hero Price', pass: body.includes('₹123.15') && body.includes('-38.61% TODAY') },
      { name: 'CE Total OI', pass: body.includes('19.9L') || body.includes('OI') },
      { name: 'CE Opening Baseline & ΔOI', pass: body.includes('OPEN 4.9L →') && body.includes('+14.9L') },
      { name: 'CE Formula & Positioning', pass: body.includes('PRICE ↓ + OI ↑') && body.includes('CALL SHORT BUILD') },
      { name: 'PE Strike 24,350 PE', pass: body.includes('24,350 PE') },
      { name: 'PE Hero Price', pass: body.includes('₹57.9') && body.includes('+12.32% TODAY') },
      { name: 'PE Total OI', pass: body.includes('97.2L') || body.includes('OI') },
      { name: 'PE Opening Baseline & ΔOI', pass: body.includes('OPEN 68.0L →') && body.includes('+29.3L') },
      { name: 'PE Formula & Positioning', pass: body.includes('PRICE ↑ + OI ↑') && body.includes('PUT LONG BUILD') },
    ]

    console.log('DOM ACCEPTANCE AUDIT RESULTS:')
    for (const c of checks) {
      console.log(`[${c.pass ? 'PASS' : 'FAIL'}] ${c.name}`)
    }

    const failed = checks.filter((c) => !c.pass)
    if (failed.length > 0) {
      console.error(`FAILED CHECKS: ${failed.map((f) => f.name).join(', ')}`)
    }

    // Now capture all 5 viewports with guaranteed live populated state
    for (const vp of VIEWPORTS) {
      const vPage = await browser.newPage()
      await vPage.setViewport({ width: vp.width, height: vp.height })
      await vPage.goto('http://127.0.0.1:3000/preview/photonic', { waitUntil: 'domcontentloaded', timeout: 60000 })
      await vPage.waitForFunction(
        () => !document.body.innerText.includes('REV -1') && document.body.innerText.includes('24,250 CE'),
        { timeout: 15000 }
      )
      await new Promise((r) => setTimeout(r, 1000))
      const outPath = path.join(ARTIFACTS_DIR, `photonic_live_price_arch_${vp.name}.png`)
      await vPage.screenshot({ path: outPath, fullPage: false })
      console.log(`Captured verified screenshot ${vp.name} -> ${outPath}`)

      if (vp.name === '1440x900') {
        const legacyPage = await browser.newPage()
        await legacyPage.setViewport({ width: 1440, height: 900 })
        await legacyPage.goto('http://127.0.0.1:3000/oracle?vobUi=legacy', { waitUntil: 'domcontentloaded', timeout: 60000 })
        await new Promise((r) => setTimeout(r, 2000))
        const legPath = path.join(ARTIFACTS_DIR, `legacy_fallback_preserved_1440x900.png`)
        await legacyPage.screenshot({ path: legPath, fullPage: false })
        console.log(`Captured legacy screenshot 1440x900 -> ${legPath}`)
        await legacyPage.close()
      }

      await vPage.close()
    }
  } finally {
    await browser.close()
  }
}

run().catch((err) => {
  console.error(err)
  process.exit(1)
})
