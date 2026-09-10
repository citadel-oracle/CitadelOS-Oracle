import puppeteer from 'puppeteer'
import path from 'path'

const artifactDir = '/Users/ayushmudgal/.gemini/antigravity/brain/098ef0e6-34d5-4c1c-b18a-ecd567ffc636'

async function run() {
  const browser = await puppeteer.launch({
    headless: true,
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  })

  try {
    const page = await browser.newPage()
    const consoleErrors = []
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text())
    })
    page.on('pageerror', (err) => {
      consoleErrors.push(err.toString())
    })

    // Test 1: Photonic Master in /oracle @ 1440x900 (Scrolled to Photonic Suite)
    await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 2 })
    const resPhotonic = await page.goto('http://localhost:3000/oracle', { waitUntil: 'networkidle2', timeout: 20000 })
    console.log('Photonic /oracle status:', resPhotonic.status())

    await new Promise((r) => setTimeout(r, 1500))
    const photonicElement = await page.$('#nifty-photonic-master-suite')
    if (photonicElement) {
      await photonicElement.scrollIntoView()
      await new Promise((r) => setTimeout(r, 500))
      await page.screenshot({
        path: path.join(artifactDir, 'oracle_photonic_mount_1440.png'),
        fullPage: false,
      })
      await page.screenshot({
        path: path.join(artifactDir, 'oracle_photonic_mount_fullpage_1440.png'),
        fullPage: true,
      })
    }

    // Test 2: Photonic Master @ 1920x1080
    await page.setViewport({ width: 1920, height: 1080, deviceScaleFactor: 2 })
    await new Promise((r) => setTimeout(r, 600))
    if (photonicElement) {
      await photonicElement.scrollIntoView()
      await new Promise((r) => setTimeout(r, 500))
      await page.screenshot({
        path: path.join(artifactDir, 'oracle_photonic_mount_1920.png'),
        fullPage: false,
      })
    }

    // Test 3: Photonic Master @ 1280x800
    await page.setViewport({ width: 1280, height: 800, deviceScaleFactor: 2 })
    await new Promise((r) => setTimeout(r, 600))
    if (photonicElement) {
      await photonicElement.scrollIntoView()
      await new Promise((r) => setTimeout(r, 500))
      await page.screenshot({
        path: path.join(artifactDir, 'oracle_photonic_mount_1280.png'),
        fullPage: false,
      })
    }

    // Test 4: Original Legacy VOB Fallback @ 1440x900
    await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 2 })
    const resLegacy = await page.goto('http://localhost:3000/oracle?vobUi=legacy', { waitUntil: 'networkidle2', timeout: 20000 })
    console.log('Legacy /oracle?vobUi=legacy status:', resLegacy.status())

    await new Promise((r) => setTimeout(r, 1500))
    const legacyElem = await page.$('[aria-label="CITADEL VOB PULLBACK COMMAND"]')
    if (legacyElem) {
      await legacyElem.scrollIntoView()
      await new Promise((r) => setTimeout(r, 500))
      await page.screenshot({
        path: path.join(artifactDir, 'oracle_legacy_vob_fallback_1440.png'),
        fullPage: false,
      })
    }

    console.log('Console Errors:', consoleErrors)
    console.log('ENHANCED SCROLL SCREENSHOTS COMPLETE.')
  } finally {
    await browser.close()
  }
}

run().catch((err) => {
  console.error('Test script error:', err)
  process.exit(1)
})
