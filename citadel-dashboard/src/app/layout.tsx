import type { Metadata } from 'next'
import { Inter, JetBrains_Mono, Space_Grotesk } from 'next/font/google'
import type { ReactNode } from 'react'
import './globals.css'
import { AppProviders } from '../providers/AppProviders'

const oracleDisplay = Space_Grotesk({
  subsets: ['latin'],
  variable: '--font-oracle-display',
  display: 'swap',
})

const oracleBody = Inter({
  subsets: ['latin'],
  variable: '--font-oracle-body',
  display: 'swap',
})

const oracleData = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-oracle-data',
  display: 'swap',
})

export const metadata: Metadata = {
  title: 'CITADEL OS',
  description: 'Institutional AI Trading Operating System',
}

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html
      lang="en"
      className={`dark ${oracleDisplay.variable} ${oracleBody.variable} ${oracleData.variable}`}
      suppressHydrationWarning
    >
      <body>
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  )
}
