import { DataTable } from './DataTable'
import type { DataTableColumn, DataTableProps, DataTableRow } from './DataTable'

export type JournalColumn = DataTableColumn
export type JournalEntry = DataTableRow
export type JournalTableProps = DataTableProps

export function JournalTable(props: JournalTableProps) {
  return <DataTable {...props} />
}
