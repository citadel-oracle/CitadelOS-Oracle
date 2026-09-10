import puppeteer from 'puppeteer-core'
import fs from 'fs'
import path from 'path'

const CHROME_PATH = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const ARTIFACT_DIR = '/Users/ayushmudgal/.gemini/antigravity/brain/098ef0e6-34d5-4c1c-b18a-ecd567ffc636'

async function run() {
  console.log('Launching headless Chrome for Photonic Parity Verification...')
  const browser = await puppeteer.launch({
    executablePath: CHROME_PATH,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  })

  const page = await browser.newPage()

  const viewports = [
    { width: 1440, height: 900, name: '1440' },
    { width: 1920, height: 1080, name: '1920' },
    { width: 1280, height: 800, name: '1280' },
    { width: 768, height: 1024, name: '768' },
    { width: 390, height: 844, name: '390' }
  ]

  // 1. Capture Locked Visual Master at 1440
  console.log('Capturing locked master HTML at 1440...')
  await page.setViewport({ width: 1440, height: 900 })
  await page.goto('http://localhost:8090/vob-hero-header-variants/citadel-vob-photonic-master.html', { waitUntil: 'domcontentloaded' })
  await new Promise(r => setTimeout(r, 1000))
  await page.screenshot({ path: path.join(ARTIFACT_DIR, 'locked_master_photonic_1440.png'), fullPage: false })

  // 2. Capture /oracle across all viewports
  const consoleErrors = []
  page.on('console', msg => {
    if (msg.type() === 'error') {
      consoleErrors.push(msg.text())
    }
  })

  for (const vp of viewports) {
    console.log(`Auditing /oracle at ${vp.width}x${vp.height}...`)
    await page.setViewport({ width: vp.width, height: vp.height })
    await page.goto('http://localhost:3000/oracle', { waitUntil: 'domcontentloaded' })
    await new Promise(r => setTimeout(r, 2000))

    // Check if suite exists
    const suite = await page.$('#nifty-photonic-master-suite')
    if (suite) {
      await suite.screenshot({ path: path.join(ARTIFACT_DIR, `oracle_photonic_suite_${vp.name}.png`) })
    }
    await page.screenshot({ path: path.join(ARTIFACT_DIR, `oracle_photonic_viewport_${vp.name}.png`), fullPage: false })
  }

  // 3. Capture /oracle?vobUi=legacy
  console.log('Auditing legacy fallback /oracle?vobUi=legacy...')
  await page.setViewport({ width: 1440, height: 900 })
  await page.goto('http://localhost:3000/oracle?vobUi=legacy', { waitUntil: 'domcontentloaded' })
  await new Promise(r => setTimeout(r, 2000))
  await page.screenshot({ path: path.join(ARTIFACT_DIR, 'oracle_legacy_fallback_verified.png'), fullPage: false })

  // 4. Computed Style Audit on /oracle
  console.log('Running computed style audit...')
  await page.goto('http://localhost:3000/oracle', { waitUntil: 'domcontentloaded' })
  await new Promise(r => setTimeout(r, 1500))

  const auditReport = await page.evaluate(() => {
    const suite = document.querySelector('#nifty-photonic-master-suite')
    if (!suite) return { error: 'Photonic suite not found' }

    const getComputed = (sel) => {
      const el = document.querySelector(sel)
      if (!el) return { found: false }
      const cs = window.getComputedStyle(el)
      return {
        found: true,
        display: cs.display,
        position: cs.position,
        width: cs.width,
        height: cs.height,
        padding: cs.padding,
        margin: cs.margin,
        fontFamily: cs.fontFamily,
        fontSize: cs.fontSize,
        fontWeight: cs.fontWeight,
        background: cs.background,
        border: cs.border,
        borderRadius: cs.borderRadius,
        boxShadow: cs.boxShadow,
        opacity: cs.opacity,
        transform: cs.transform,
        overflow: cs.overflow,
        zIndex: cs.zIndex,
        animationName: cs.animationName,
        animationDuration: cs.animationDuration,
        animationPlayState: cs.animationPlayState
      }
    }

    return {
      suite: getComputed('#nifty-photonic-master-suite'),
      heroHeader: getComputed('#nifty-photonic-master-suite [class*="cardPhotonicHeader"]'),
      auroraGlow: getComputed('#nifty-photonic-master-suite [class*="auroraGlowBlob"]'),
      resolverStrip: getComputed('#nifty-photonic-master-suite [class*="cardResolverStrip"]'),
      callCard: getComputed('#nifty-photonic-master-suite [class*="cardCall"]'),
      heroWheel: getComputed('#nifty-photonic-master-suite [class*="cardOracleHero"]'),
      plasmaCore: getComputed('#nifty-photonic-master-suite [class*="liquidColorCore"]'),
      orbitRing1: getComputed('#nifty-photonic-master-suite [class*="orbitFlareRing1"]'),
      putCard: getComputed('#nifty-photonic-master-suite [class*="cardPut"]'),
      recoveryRail: getComputed('#nifty-photonic-master-suite [aria-label*="Recovery Engine"]'),
      argusSupport: getComputed('#nifty-photonic-master-suite [aria-label*="ARGUS"]'),
      evidenceChannels: getComputed('#nifty-photonic-master-suite [aria-label*="Failed Aggression"]'),
      matchedPnl: getComputed('#nifty-photonic-master-suite [aria-label*="Matched Comparison"]'),
      vobLevels: getComputed('#nifty-photonic-master-suite [aria-label*="VOB Key Levels"]'),
      lifecycleStepper: getComputed('#nifty-photonic-master-suite [aria-label*="Lifecycle"]'),
      scoreboard: getComputed('#nifty-photonic-master-suite [aria-label*="Experiment Scoreboard"]')
    }
  })

  console.log('Console Errors:', JSON.stringify(consoleErrors))
  console.log('Audit Report:', JSON.stringify(auditReport, null, 2))

  fs.writeFileSync(
    path.join(ARTIFACT_DIR, 'photonic_computed_style_audit.json'),
    JSON.stringify({ consoleErrors, auditReport }, null, 2)
  )

  await browser.close()
  console.log('Photonic Parity Verification Complete.')
}

run().catch(err => {
  console.error('Verification failed:', err)
  process.exit(1)
})
