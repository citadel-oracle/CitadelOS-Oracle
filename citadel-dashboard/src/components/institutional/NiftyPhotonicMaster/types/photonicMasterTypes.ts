export interface PhotonicResolverQuote {
  strike: number | null
  side: 'CALL' | 'PUT'
  symbol: string
  bid: number | null
  ask: number | null
  quoteId: string
  timestamp: string
}

export interface PhotonicVobLevel {
  timeframe: string
  role: 'SUPPORT' | 'RESISTANCE'
  low: number
  high: number
  status: 'ACTIVE' | 'TESTED' | 'WEAKENING' | 'BROKEN'
  distancePoints: number
}

export interface PhotonicEvidenceItem {
  channel: string
  status: 'CONFIRMED' | 'REJECTED' | 'MONITORING' | 'WAITING'
  details: string
  direction: 'CALL' | 'PUT' | 'NEUTRAL'
}

export interface PhotonicPnlMetrics {
  vobPnl: number
  vobR: number
  vobTarget: number
  confirmedPnl: number
  confirmedR: number
  confirmedTarget: number
  advantagePnl: number
  mfePercent: number
  maePercent: number
  vobEntryTime: string
  confirmedEntryTime: string
}

export interface PhotonicLifecycleNode {
  id: number
  name: string
  status: 'COMPLETED' | 'ACTIVE' | 'PENDING'
  description?: string
}

export interface NiftyPhotonicMasterProps {
  spot?: number | null
  atmStrike?: number | null
  resolvedCall?: PhotonicResolverQuote | null
  resolvedPut?: PhotonicResolverQuote | null
  vobCall?: {
    strike: string
    premium: number
    percentChange: number
    sliderPercent: number
    state: string
    staleText?: string
  } | null
  vobPut?: {
    strike: string
    premium: number
    percentChange: number
    sliderPercent: number
    state: string
    staleText?: string
  } | null
  heroWheel?: {
    actionLabel: string
    turnStrengthScore: number | string
    vobSetupPercent: number
    turnStrPercent: number
    supportPercent: number
    direction: 'CALL' | 'PUT' | 'NEUTRAL'
  } | null
  marketStory?: {
    scanText: string
    signalState: string
  } | null
  recovery?: {
    sellerPercent: number
    buyerPercent: number
    dominantSide: string
  } | null
  argus?: {
    contextMatch: string
    winProbability: number
    supportive: boolean
    notes: string
  } | null
  evidenceChannels?: PhotonicEvidenceItem[] | null
  pnlMetrics?: PhotonicPnlMetrics | null
  vobLevels?: PhotonicVobLevel[] | null
  lifecycleNodes?: PhotonicLifecycleNode[] | null
  scoreboard?: {
    vobAvgR: string
    confirmedAvgR: string
    expectancy: string
    winRate: string
  } | null
  onSimulateTick?: (type: 'CALL' | 'PUT' | 'PULLBACK' | 'SURGE') => void
}
