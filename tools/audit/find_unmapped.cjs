const { chromium } = require('../../citadel-dashboard/node_modules/playwright')

async function main() {
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1680, height: 1050 } })
  await page.goto('http://127.0.0.1:3000/oracle', { waitUntil: 'domcontentloaded', timeout: 15000 })
  await page.waitForTimeout(5000)
  
  const unmapped = await page.evaluate(() => {
    const leaves = []
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false)
    let node
    while (node = walker.nextNode()) {
      if (!node.nodeValue.trim()) continue;
      if (node.nodeValue.match(/[0-9]/)) { // has number
        let el = node.parentElement
        // check if any ancestor has data-citadel-field or data-oracle-field
        let mapped = false
        let curr = el
        while (curr && curr !== document.body) {
          if (curr.hasAttribute('data-citadel-field') || curr.hasAttribute('data-oracle-field')) {
            mapped = true
            break
          }
          curr = curr.parentElement
        }
        if (!mapped && !el.closest('svg') && !el.closest('[data-tradingview-sync]')) {
          leaves.push({ text: node.nodeValue.trim(), tag: el.tagName, class: el.className })
        }
      }
    }
    return leaves
  })
  
  console.log(`Found ${unmapped.length} unmapped nodes with numbers`)
  console.log(unmapped.slice(0, 50))
  await browser.close()
}
main().catch(console.error)
