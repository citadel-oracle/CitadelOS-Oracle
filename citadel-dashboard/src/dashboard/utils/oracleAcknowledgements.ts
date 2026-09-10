const STORAGE_KEY = 'citadel.personal-oracle.acknowledgements.v1'

export const oracleAcknowledgementKey = (observationId: string, version: number) =>
  `${observationId}:${version}`

export function loadOracleAcknowledgements(): Set<string> {
  if (typeof window === 'undefined') return new Set()
  try {
    const value = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '[]')
    return new Set(Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [])
  } catch {
    return new Set()
  }
}

export function saveOracleAcknowledgement(observationId: string, version: number): Set<string> {
  const next = loadOracleAcknowledgements()
  next.add(oracleAcknowledgementKey(observationId, version))
  if (typeof window !== 'undefined') window.localStorage.setItem(STORAGE_KEY, JSON.stringify([...next]))
  return next
}
