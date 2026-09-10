import puppeteer from 'puppeteer'
import fs from 'fs'
import path from 'path'

const VIEWPORTS = [
  { width: 1440, height: 900, name: '1440x900' },
  { width: 1920, height: 1080, name: '1920x1080' },
  { width: 1280, height: 800, name: '1280x800' },
  { width: 768, height: 1024, name: '768x1024' },
  { width: 390, height: 844, name: '390x844' },
]

const ARTIFACTS_DIR = '/Users/ayushmudgal/.gemini/antigravity/brain/098ef0e6-34d5-4c1c-b18a-ecd567ffc636'

async function run() {
  const browser = await puppeteer.launch({
    headless: true,
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  })

  try {
    for (const vp of VIEWPORTS) {
      const page = await browser.newPage()
      await page.setViewport({ width: vp.width, height: vp.height })
      
      // Photonic master standalone preview
      await page.goto('http://127.0.0.1:3000/preview/photonic', { waitUntil: 'domcontentloaded', timeout: 60000 })
      await new Promise(r => setTimeout(r, 3500))
      const photonicPath = path.join(ARTIFACTS_DIR, `photonic_live_price_arch_${vp.name}.png`)
      await page.screenshot({ path: photonicPath, fullPage: false })
      console.log(`Captured Photonic ${vp.name} -> ${photonicPath}`)

      // Legacy fallback check on /oracle?vobUi=legacy
      if (vp.name === '1440x900') {
        await page.goto('http://127.0.0.1:3000/oracle?vobUi=legacy', { waitUntil: 'domcontentloaded', timeout: 60000 })
        await new Promise(r => setTimeout(r, 2000))
        const legacyPath = path.join(ARTIFACTS_DIR, `legacy_fallback_preserved_${vp.name}.png`)
        await page.screenshot({ path: legacyPath, fullPage: false })
        console.log(`Captured Legacy ${vp.name} -> ${legacyPath}`)
      }

      await page.close()
    }
  } finally {
    await browser.close()
  }
}

run().catch((err) => {
  console.error(err)
  process.exit(1)
})
