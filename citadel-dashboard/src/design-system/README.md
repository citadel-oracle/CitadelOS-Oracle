# CITADEL Design System

This package is the reusable visual contract for CITADEL OS. It does not alter or depend on page architecture, runtime state, APIs, or trading behavior.

## Foundation

- Five typography levels: `hero`, `sectionTitle`, `tableHeader`, `body`, `caption`.
- One eight-pixel spacing scale, exposed in CSS and TypeScript.
- Semantic color roles only: brand, positive, negative, information, warning, and neutral.
- Three institutional row densities: 24px, 32px, and 40px.
- Standardized borders, radii, elevation, hover, focus, and reduced-motion behavior.

## Components

- `Typography`
- `Card`
- `Badge`
- `StatusChip`
- `SectionHeader`
- `Row`
- `MetricCard`
- `DataTable`, `TableRow`, `TableHeaderCell`, `TableCell`

Import components from `@/design-system`. Tokens load with the component stylesheet and are also available through `colors`, `spacing`, and `rowHeights`.

```tsx
import { DataTable, MetricCard, StatusChip, TableCell, TableRow } from '@/design-system'

<MetricCard label="Live MTM" value="+₹1,140" detail="+9.18%" tone="positive" layout="inline" />

<StatusChip tone="positive">Running</StatusChip>

<DataTable density="compact">
  <tbody>
    <TableRow>
      <TableCell>PB NIFTY CE 1M</TableCell>
      <TableCell numeric>+₹320</TableCell>
    </TableRow>
  </tbody>
</DataTable>
```

Existing pages must not be migrated until the design system is approved.
