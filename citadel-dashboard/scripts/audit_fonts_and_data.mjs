import puppeteer from 'puppeteer-core'

const CHROME_PATH = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'

async function run() {
  const browser = await puppeteer.launch({
    executablePath: CHROME_PATH,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  })

  const page = await browser.newPage()
  await page.setViewport({ width: 1440, height: 900 })

  console.log('--- 1. AUDITING LOCKED MASTER HTML ---')
  await page.goto('http://localhost:8090/vob-hero-header-variants/citadel-vob-photonic-master.html', { waitUntil: 'domcontentloaded' })
  await new Promise(r => setTimeout(r, 1000))

  const masterFonts = await page.evaluate(() => {
    const getFont = (sel) => {
      const el = document.querySelector(sel)
      if (!el) return 'NOT FOUND'
      const cs = window.getComputedStyle(el)
      return {
        fontFamily: cs.fontFamily,
        fontSize: cs.fontSize,
        fontWeight: cs.fontWeight,
        letterSpacing: cs.letterSpacing,
        lineHeight: cs.lineHeight,
      }
    }
    return {
      callPrice: getFont('#call-price'),
      putPrice: getFont('#put-price'),
      heroTitle: getFont('.photonic-hero-title'),
      spotVal: getFont('#spot-val'),
    }
  })
  console.log('Master Fonts:', JSON.stringify(masterFonts, null, 2))

  console.log('--- 2. AUDITING /ORACLE MOUNT ---')
  await page.goto('http://localhost:3000/oracle', { waitUntil: 'domcontentloaded' })
  await new Promise(r => setTimeout(r, 1500))

  const oracleFontsAndData = await page.evaluate(() => {
    const getFont = (sel) => {
      const el = document.querySelector(sel)
      if (!el) return 'NOT FOUND'
      const cs = window.getComputedStyle(el)
      return {
        fontFamily: cs.fontFamily,
        fontSize: cs.fontSize,
        fontWeight: cs.fontWeight,
        letterSpacing: cs.letterSpacing,
        lineHeight: cs.lineHeight,
        textContent: el.textContent?.trim(),
      }
    }

    // Also get state from window if exposed or query DOM
    return {
      callPrice: getFont('#nifty-photonic-master-suite [class*="cardCall"] [class*="heroPrice"]'),
      putPrice: getFont('#nifty-photonic-master-suite [class*="cardPut"] [class*="heroPrice"]'),
      heroTitle: getFont('#nifty-photonic-master-suite [class*="photonicHeroTitle"]'),
      spotCell: getFont('#nifty-photonic-master-suite [class*="glassCapsuleGrid"] > div:first-child > div:last-child'),
      resolverItmCall: getFont('#nifty-photonic-master-suite [class*="cardResolverStrip"] > div > div:first-child'),
      matchedPnlCard: getFont('#nifty-photonic-master-suite [aria-label*="Matched Comparison"]'),
      scoreboard: getFont('#nifty-photonic-master-suite [aria-label*="Experiment Scoreboard"]'),
    }
  })
  console.log('Oracle Fonts & Data:', JSON.stringify(oracleFontsAndData, null, 2))

  await browser.close()
}

run().catch(console.error)
