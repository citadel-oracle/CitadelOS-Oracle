'use client'

import {
  SafetyStrip,
  CitadelPrimaryNavigation,
  UnifiedOptionBuyerCommandDeck,
} from '@/components/institutional'

export default function PreviewPage() {
  return (
    <div style={{ minHeight: '100vh', background: '#050608', color: '#F8FAFC', paddingBottom: '40px' }}>
      {/* CITADEL COMMAND SAFETY STRIP */}
      <SafetyStrip />

      {/* CITADEL PRIMARY NAVIGATION */}
      <CitadelPrimaryNavigation active="production" instrument="NIFTY" marketStatus="CLOSED" />

      <main style={{ maxWidth: '1440px', margin: '0 auto', padding: '20px 24px' }}>
        {/* UNIFIED 5-ENGINE OPTION BUYER COMMAND DECK */}
        <section aria-label="Unified Option Buyer Command Deck">
          <UnifiedOptionBuyerCommandDeck />
        </section>
      </main>
    </div>
  )
}
