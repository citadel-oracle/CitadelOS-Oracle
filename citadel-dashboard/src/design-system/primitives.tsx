import { createElement, type HTMLAttributes, type ReactNode, type TableHTMLAttributes, type TdHTMLAttributes, type ThHTMLAttributes } from 'react'

import styles from './primitives.module.css'
import type { CitadelDensity, CitadelTone } from './tokens'

function classes(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(' ')
}

const toneClasses: Record<CitadelTone, string> = {
  neutral: '',
  brand: styles.toneBrand,
  positive: styles.tonePositive,
  negative: styles.toneNegative,
  info: styles.toneInfo,
  warning: styles.toneWarning,
}

const textToneClasses = {
  default: '',
  neutral: styles.textNeutral,
  muted: styles.textMuted,
  subtle: styles.textSubtle,
  brand: styles.textBrand,
  positive: styles.textPositive,
  negative: styles.textNegative,
  info: styles.textInfo,
  warning: styles.textWarning,
} as const

export type TypographyVariant = 'hero' | 'sectionTitle' | 'tableHeader' | 'body' | 'caption'
export type TypographyTone = keyof typeof textToneClasses

export interface TypographyProps extends HTMLAttributes<HTMLElement> {
  as?: 'h1' | 'h2' | 'h3' | 'p' | 'span' | 'strong' | 'small' | 'div'
  variant?: TypographyVariant
  tone?: TypographyTone
  mono?: boolean
  numeric?: boolean
  truncate?: boolean
  unstyled?: boolean
}

export function Typography({ as = 'span', variant = 'body', tone = 'default', mono = false, numeric = false, truncate = false, unstyled = false, className, ...props }: TypographyProps) {
  return createElement(as, {
    ...props,
    className: classes(!unstyled && styles.typography, !unstyled && styles[variant], !unstyled && textToneClasses[tone], !unstyled && mono && styles.mono, !unstyled && numeric && styles.numeric, !unstyled && truncate && styles.truncate, className),
  })
}

export type CardVariant = 'default' | 'compact' | 'elevated' | 'inset' | 'metric'

export interface CardProps extends HTMLAttributes<HTMLElement> {
  as?: 'div' | 'article' | 'section'
  variant?: CardVariant
  interactive?: boolean
  unstyled?: boolean
}

const cardVariants: Record<CardVariant, string> = {
  default: styles.cardDefault,
  compact: styles.cardCompact,
  elevated: styles.cardElevated,
  inset: styles.cardInset,
  metric: styles.cardMetric,
}

export function Card({ as = 'div', variant = 'default', interactive = false, unstyled = false, className, ...props }: CardProps) {
  return createElement(as, {
    ...props,
    className: classes(!unstyled && styles.card, !unstyled && cardVariants[variant], !unstyled && interactive && styles.interactive, !unstyled && interactive && styles.focusRing, className),
  })
}

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: CitadelTone
  dot?: boolean
  pill?: boolean
  unstyled?: boolean
}

export function Badge({ tone = 'neutral', dot = false, pill = false, unstyled = false, className, ...props }: BadgeProps) {
  return <span {...props} className={classes(!unstyled && styles.badge, !unstyled && toneClasses[tone], !unstyled && dot && styles.badgeDot, !unstyled && pill && styles.badgePill, className)} />
}

export interface StatusChipProps extends HTMLAttributes<HTMLElement> {
  as?: 'span' | 'div'
  tone?: CitadelTone
  unstyled?: boolean
}

export function StatusChip({ as = 'span', tone = 'neutral', unstyled = false, className, ...props }: StatusChipProps) {
  return createElement(as, { ...props, className: classes(!unstyled && styles.statusChip, !unstyled && toneClasses[tone], className) })
}

export interface SectionHeaderProps extends Omit<HTMLAttributes<HTMLElement>, 'title'> {
  eyebrow?: ReactNode
  title: ReactNode
  description?: ReactNode
  aside?: ReactNode
  headingLevel?: 2 | 3
  as?: 'div' | 'header'
  copyClassName?: string
  eyebrowClassName?: string
  titleClassName?: string
  descriptionClassName?: string
  asideClassName?: string
  unstyled?: boolean
}

export function SectionHeader({ eyebrow, title, description, aside, headingLevel = 2, as = 'header', copyClassName, eyebrowClassName, titleClassName, descriptionClassName, asideClassName, unstyled = false, className, ...props }: SectionHeaderProps) {
  const headingTag = `h${headingLevel}` as 'h2' | 'h3'
  return createElement(
    as,
    { ...props, className: classes(!unstyled && styles.sectionHeader, className) },
    <>
      <div className={classes(!unstyled && styles.sectionHeaderCopy, copyClassName)}>
        {eyebrow ? <Typography variant="caption" tone="brand" mono unstyled={unstyled} className={eyebrowClassName}>{eyebrow}</Typography> : null}
        <Typography as={headingTag} variant="sectionTitle" unstyled={unstyled} className={titleClassName}>{title}</Typography>
        {description ? <Typography variant="caption" tone="subtle" unstyled={unstyled} className={descriptionClassName}>{description}</Typography> : null}
      </div>
      {aside ? <div className={classes(!unstyled && styles.sectionHeaderAside, asideClassName)}>{aside}</div> : null}
    </>,
  )
}

export interface RowProps extends HTMLAttributes<HTMLElement> {
  as?: 'div' | 'article' | 'li'
  density?: CitadelDensity
  align?: 'start' | 'center' | 'end'
  justify?: 'start' | 'between' | 'end'
  divided?: boolean
  interactive?: boolean
  unstyled?: boolean
}

const rowDensityClasses: Record<CitadelDensity, string> = { compact: styles.rowCompact, default: styles.rowDefault, comfortable: styles.rowComfortable }
const rowAlignClasses = { start: styles.alignStart, center: styles.alignCenter, end: styles.alignEnd }
const rowJustifyClasses = { start: styles.justifyStart, between: styles.justifyBetween, end: styles.justifyEnd }

export function Row({ as = 'div', density = 'default', align = 'center', justify = 'start', divided = false, interactive = false, unstyled = false, className, ...props }: RowProps) {
  return createElement(as, { ...props, className: classes(!unstyled && styles.row, !unstyled && rowDensityClasses[density], !unstyled && rowAlignClasses[align], !unstyled && rowJustifyClasses[justify], !unstyled && divided && styles.rowDivided, !unstyled && interactive && styles.interactive, !unstyled && interactive && styles.focusRing, className) })
}

export interface MetricCardProps extends HTMLAttributes<HTMLElement> {
  label: ReactNode
  value: ReactNode
  detail?: ReactNode
  tone?: Exclude<TypographyTone, 'default' | 'muted' | 'subtle'> | 'default'
  layout?: 'inline' | 'stacked'
  as?: 'article' | 'div'
  unstyled?: boolean
  labelClassName?: string
  valueClassName?: string
  detailClassName?: string
}

export function MetricCard({ label, value, detail, tone = 'default', layout = 'stacked', as = 'article', unstyled = false, labelClassName, valueClassName, detailClassName, className, ...props }: MetricCardProps) {
  return createElement(
    as,
    { ...props, className: classes(!unstyled && styles.metricCard, !unstyled && (layout === 'inline' ? styles.metricInline : styles.metricStacked), className) },
    <><span className={classes(!unstyled && styles.metricLabel, labelClassName)}>{label}</span><strong className={classes(!unstyled && styles.metricValue, !unstyled && textToneClasses[tone], valueClassName)}>{value}</strong>{detail ? <small className={classes(!unstyled && styles.metricDetail, detailClassName)}>{detail}</small> : null}</>,
  )
}

export interface DataTableProps extends TableHTMLAttributes<HTMLTableElement> {
  density?: CitadelDensity
  striped?: boolean
  frameClassName?: string
  unstyled?: boolean
}

const tableDensityClasses: Record<CitadelDensity, string> = { compact: styles.tableCompact, default: '', comfortable: styles.tableComfortable }

export function DataTable({ density = 'default', striped = false, unstyled = false, className, frameClassName, children, ...props }: DataTableProps) {
  return <div className={classes(!unstyled && styles.tableFrame, frameClassName)}><table {...props} className={classes(!unstyled && styles.table, !unstyled && tableDensityClasses[density], !unstyled && striped && styles.tableStriped, className)}>{children}</table></div>
}

export interface TableRowProps extends HTMLAttributes<HTMLTableRowElement> { interactive?: boolean; unstyled?: boolean }
export function TableRow({ interactive = false, unstyled = false, className, ...props }: TableRowProps) {
  return <tr {...props} className={classes(!unstyled && interactive && styles.tableRowInteractive, !unstyled && interactive && styles.focusRing, className)} />
}

export interface TableHeaderCellProps extends ThHTMLAttributes<HTMLTableCellElement> { numeric?: boolean; unstyled?: boolean }
export function TableHeaderCell({ numeric = false, unstyled = false, className, ...props }: TableHeaderCellProps) {
  return <th {...props} className={classes(!unstyled && numeric && styles.tableNumeric, className)} />
}

export interface TableCellProps extends TdHTMLAttributes<HTMLTableCellElement> { numeric?: boolean; unstyled?: boolean }
export function TableCell({ numeric = false, unstyled = false, className, ...props }: TableCellProps) {
  return <td {...props} className={classes(!unstyled && numeric && styles.tableNumeric, className)} />
}
