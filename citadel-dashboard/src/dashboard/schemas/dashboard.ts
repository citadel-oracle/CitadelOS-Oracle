import { z } from 'zod'

export const dashboardFeedMetaSchema = z.object({
  health: z.string(), readiness: z.string(), latency_ms: z.number().finite(),
  last_updated: z.string().nullable(), source_last_updated: z.string().nullable(),
})

export const dashboardSourceSnapshotSchema = z.object({
  schemaVersion: z.literal(1),
  provider: z.enum(['mock', 'rest', 'websocket', 'replay', 'historical']),
  traceId: z.string().min(1), generatedAt: z.iso.datetime(), selectedSymbol: z.string().min(1),
  feeds: z.record(z.string(), z.unknown()), feedMeta: z.record(z.string(), dashboardFeedMetaSchema),
})
