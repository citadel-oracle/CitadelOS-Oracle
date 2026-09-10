import puppeteer from 'puppeteer'
import { promises as fs } from 'fs'
import path from 'path'

const artifactDir = '/Users/ayushmudgal/.gemini/antigravity/brain/098ef0e6-34d5-4c1c-b18a-ecd567ffc636'
const viewports = [
  { name: '1440x900', width: 1440, height: 900 },
  { name: '1920x1080', width: 1920, height: 1080 },
  { name: '1280x800', width: 1280, height: 800 },
  { name: '768x1024', width: 768, height: 1024 },
  { name: '390x844', width: 390, height: 844 },
]

const CHROME_PATH = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'

async function run() {
  const browser = await puppeteer.launch({
    executablePath: CHROME_PATH,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  })
  const page = await browser.newPage()

  for (const vp of viewports) {
    await page.setViewport({ width: vp.width, height: vp.height })
    await page.goto('http://localhost:3000/oracle', { waitUntil: 'domcontentloaded', timeout: 15000 })
    await new Promise((r) => setTimeout(r, 1500))
    const suite = await page.$('#nifty-photonic-master-suite')
    if (suite) {
      const suitePath = path.join(artifactDir, `wheel_rail_suite_${vp.name}.png`)
      await suite.screenshot({ path: suitePath })
      console.log(`Saved suite screenshot: ${suitePath}`)
    }
    const heroCard = await page.$('[aria-label="Oracle Centerpiece Kinetic Core"]')
    if (heroCard) {
      const heroPath = path.join(artifactDir, `wheel_hero_card_${vp.name}.png`)
      await heroCard.screenshot({ path: heroPath })
      console.log(`Saved hero card screenshot: ${heroPath}`)
    }
    const outPath = path.join(artifactDir, `wheel_rail_live_${vp.name}.png`)
    await page.screenshot({ path: outPath, fullPage: false })
    console.log(`Saved viewport screenshot: ${outPath}`)
  }

  // Also check legacy
  await page.setViewport({ width: 1440, height: 900 })
  await page.goto('http://localhost:3000/oracle?vobUi=legacy', { waitUntil: 'domcontentloaded', timeout: 15000 })
  await new Promise((r) => setTimeout(r, 1000))
  const legacyPath = path.join(artifactDir, `wheel_rail_legacy_1440.png`)
  await page.screenshot({ path: legacyPath, fullPage: false })
  console.log(`Saved legacy screenshot: ${legacyPath}`)

  await browser.close()
  console.log('All screenshots captured successfully!')
}

run().catch((err) => {
  console.error(err)
  process.exit(1)
})
