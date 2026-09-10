'use client'

import React, { useEffect } from 'react'
import { NiftyPhotonicMaster } from '@/components/institutional/NiftyPhotonicMaster'
import { ingestOracleDashboardSnapshot } from '@/dashboard/store/oracleStore'

const API_URL = process.env.NEXT_PUBLIC_CITADEL_API_URL ?? 'http://127.0.0.1:8000'

export default function PhotonicPreviewPage() {
  useEffect(() => {
    let active = true
    const poll = async () => {
      try {
        const res = await fetch(`${API_URL}/v1/oracle/fast-lane`)
        if (res.ok && active) {
          const data = await res.json()
          ingestOracleDashboardSnapshot(data, new Date().toISOString())
        }
      } catch (err) {
        // Silently ignore network retry errors
      }
    }
    poll()
    const interval = setInterval(poll, 1000)
    return () => {
      active = false
      clearInterval(interval)
    }
  }, [])

  return (
    <main
      style={{
        minHeight: '100vh',
        background: '#04070B',
        color: '#E6EDF3',
        padding: '24px',
        fontFamily: 'var(--font-sans, system-ui, -apple-system, sans-serif)',
      }}
    >
      <div style={{ maxWidth: 1440, margin: '0 auto' }}>
        <header
          style={{
            marginBottom: '20px',
            padding: '12px 16px',
            borderRadius: '8px',
            background: 'rgba(0, 229, 255, 0.05)',
            border: '1px solid rgba(0, 229, 255, 0.2)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <div>
            <h1 style={{ fontSize: '14px', margin: 0, color: 'var(--cyan, #00E5FF)', letterSpacing: '0.08em' }}>
              CITADEL VOB PHOTONIC MASTER · ISOLATED CANONICAL PREVIEW
            </h1>
            <p style={{ fontSize: '11px', margin: '4px 0 0 0', color: 'rgba(255, 255, 255, 0.6)' }}>
              Bound to live canonical Zustand store (oracleStore.ts) · Live Fast-Lane Stream
            </p>
          </div>
          <span
            style={{
              padding: '4px 8px',
              borderRadius: '4px',
              background: 'rgba(0, 255, 157, 0.15)',
              border: '1px solid rgba(0, 255, 157, 0.4)',
              color: 'var(--mint, #00FF9D)',
              fontSize: '10px',
              fontWeight: 800,
              fontFamily: 'monospace',
            }}
          >
            LIVE REFRESH ACTIVE
          </span>
        </header>

        {/* Photonic Master Suite directly bound to canonical store */}
        <NiftyPhotonicMaster />
      </div>
    </main>
  )
}
