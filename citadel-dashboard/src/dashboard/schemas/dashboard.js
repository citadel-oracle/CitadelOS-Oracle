"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.dashboardSourceSnapshotSchema = exports.dashboardFeedMetaSchema = void 0;
const zod_1 = require("zod");
exports.dashboardFeedMetaSchema = zod_1.z.object({
    health: zod_1.z.string(), readiness: zod_1.z.string(), latency_ms: zod_1.z.number().finite(),
    last_updated: zod_1.z.string().nullable(), source_last_updated: zod_1.z.string().nullable(),
});
exports.dashboardSourceSnapshotSchema = zod_1.z.object({
    schemaVersion: zod_1.z.literal(1),
    provider: zod_1.z.enum(['mock', 'rest', 'websocket', 'replay', 'historical']),
    traceId: zod_1.z.string().min(1), generatedAt: zod_1.z.iso.datetime(), selectedSymbol: zod_1.z.string().min(1),
    feeds: zod_1.z.record(zod_1.z.string(), zod_1.z.unknown()), feedMeta: zod_1.z.record(zod_1.z.string(), exports.dashboardFeedMetaSchema),
});
