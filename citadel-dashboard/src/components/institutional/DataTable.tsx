import type { ReactNode } from 'react'

import { DataTable as DesignTable, TableCell, TableHeaderCell, TableRow } from '@/design-system'
import { classNames, renderState } from './shared'
import styles from './institutional.module.css'
import type { IdentifiedItem, InstitutionalDensity, StatefulProps } from './types'

export interface DataTableColumn extends IdentifiedItem {
  header: ReactNode
  align?: 'left' | 'center' | 'right'
  numeric?: boolean
}

export interface DataTableRow extends IdentifiedItem {
  cells: Record<string, ReactNode>
  className?: string
}

export interface DataTableProps extends StatefulProps {
  columns: DataTableColumn[]
  rows?: DataTableRow[]
  caption?: ReactNode
  density?: InstitutionalDensity
  striped?: boolean
  interactiveRows?: boolean
  className?: string
  frameClassName?: string
  onRowActivate?: (row: DataTableRow) => void
}

export function DataTable({ columns, rows = [], caption, density = 'default', striped = false, interactiveRows = false, loading, empty, loadingLabel, emptyTitle, emptyDescription, className, frameClassName, onRowActivate }: DataTableProps) {
  const state = renderState({ loading, empty: empty ?? rows.length === 0, loadingLabel, emptyTitle, emptyDescription })
  if (state) return <div className={classNames(styles.surface, frameClassName)}>{state}</div>
  return <DesignTable density={density} striped={striped} className={className} frameClassName={frameClassName}>{caption ? <caption>{caption}</caption> : null}<thead><TableRow>{columns.map((column) => <TableHeaderCell key={column.id} numeric={column.numeric} className={column.align ? styles[`align${column.align[0].toUpperCase()}${column.align.slice(1)}`] : undefined}>{column.header}</TableHeaderCell>)}</TableRow></thead><tbody>{rows.map((row) => <TableRow key={row.id} interactive={interactiveRows} tabIndex={interactiveRows ? 0 : undefined} className={row.className} onClick={onRowActivate ? () => onRowActivate(row) : undefined} onKeyDown={onRowActivate ? (event) => { if (event.key === 'Enter' || event.key === ' ') onRowActivate(row) } : undefined}>{columns.map((column) => <TableCell key={column.id} numeric={column.numeric} className={column.align ? styles[`align${column.align[0].toUpperCase()}${column.align.slice(1)}`] : undefined}>{row.cells[column.id]}</TableCell>)}</TableRow>)}</tbody></DesignTable>
}
