'use client'

import Link from 'next/link'

import styles from './CitadelPrimaryNavigation.module.css'

export type CitadelPrimaryRoute =
  | 'production'
  | 'workspace'
  | 'strategies'
  | 'oracle'
  | 'oracle-development'

export interface CitadelPrimaryNavigationProps {
  active: CitadelPrimaryRoute
  instrument: string
  marketStatus: string
  title?: string
  appearance?: 'default' | 'oracle'
}

export function CitadelPrimaryNavigation({
  active,
  instrument,
  marketStatus,
  title = 'CITADEL OS',
  appearance = 'default',
}: CitadelPrimaryNavigationProps) {
  const openDashboard = (mode: 'production' | 'workspace') => {
    window.sessionStorage.setItem('citadelDashboardMode', mode)
    window.location.assign(`/?mode=${mode}`)
  }

  return (
    <header className={`${styles.shell} ${appearance === 'oracle' ? styles.oracleShell : ''}`} aria-label="CITADEL application header">
      <div className={styles.identity}>
        <span className={styles.mark} aria-hidden="true">C</span>
        <div>
          <strong>{title}</strong>
          <span>{instrument}</span>
        </div>
        <em>{marketStatus}</em>
      </div>

      <div className={styles.navigationGroup}>
        <button
          type="button"
          className={`${styles.environment} ${active === 'production' ? styles.environmentActive : ''}`}
          aria-label="Production dashboard"
          aria-current={active === 'production' ? 'page' : undefined}
          onClick={() => openDashboard('production')}
        >
          <i aria-hidden="true" /> PROD
        </button>
        <nav className={styles.routes} aria-label="Primary navigation">
          <button
            type="button"
            className={active === 'workspace' ? styles.active : ''}
            aria-current={active === 'workspace' ? 'page' : undefined}
            onClick={() => openDashboard('workspace')}
          >
            WORKSPACE
          </button>
          <Link className={active === 'strategies' ? styles.active : ''} aria-current={active === 'strategies' ? 'page' : undefined} href="/strategies">STRATEGIES</Link>
          <Link className={active === 'oracle' ? styles.active : ''} aria-current={active === 'oracle' ? 'page' : undefined} href="/oracle">ORACLE</Link>
          <Link className={active === 'oracle-development' ? styles.active : ''} aria-current={active === 'oracle-development' ? 'page' : undefined} href="/oracle-development">ORACLE DEVELOPMENT</Link>
        </nav>
      </div>
    </header>
  )
}
