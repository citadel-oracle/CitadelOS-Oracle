export const spacing = {
  0: 'var(--cds-space-0)',
  1: 'var(--cds-space-1)',
  2: 'var(--cds-space-2)',
  3: 'var(--cds-space-3)',
  4: 'var(--cds-space-4)',
  5: 'var(--cds-space-5)',
  6: 'var(--cds-space-6)',
  8: 'var(--cds-space-8)',
} as const

export const colors = {
  background: 'var(--cds-color-bg)',
  surface: 'var(--cds-color-surface)',
  surfaceStrong: 'var(--cds-color-surface-strong)',
  surfaceInset: 'var(--cds-color-surface-inset)',
  text: 'var(--cds-color-text)',
  textSoft: 'var(--cds-color-text-soft)',
  textMuted: 'var(--cds-color-text-muted)',
  textSubtle: 'var(--cds-color-text-subtle)',
  brand: 'var(--cds-color-brand)',
  brandSoft: 'var(--cds-color-brand-soft)',
  positive: 'var(--cds-color-positive)',
  negative: 'var(--cds-color-negative)',
  info: 'var(--cds-color-info)',
  warning: 'var(--cds-color-warning)',
  borderSubtle: 'var(--cds-color-border-subtle)',
  borderDefault: 'var(--cds-color-border-default)',
  borderStrong: 'var(--cds-color-border-strong)',
} as const

export const rowHeights = {
  compact: 'var(--cds-row-compact)',
  default: 'var(--cds-row-default)',
  comfortable: 'var(--cds-row-comfortable)',
} as const

export type CitadelTone = 'neutral' | 'brand' | 'positive' | 'negative' | 'info' | 'warning'
export type CitadelDensity = 'compact' | 'default' | 'comfortable'
