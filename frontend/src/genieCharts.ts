export type GenieColumn = { name: string; type?: string }
export type GenieData = { columns?: GenieColumn[]; rows?: unknown[][] }

export type GenieChartSpec = {
  kind: 'bar' | 'line'
  dimensionIndex: number
  metricIndexes: number[]
  rows: unknown[][]
}

const NUMERIC_TYPE = /(tinyint|smallint|int|bigint|long|short|float|double|decimal|number|numeric)/i
const DATE_TYPE = /(date|timestamp|time)/i

export function numericValue(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value !== 'string') return null
  const raw = value.trim()
  if (!raw) return null
  const normalized = raw
    .replace(/[%$€£\s]/g, '')
    .replace(/\.(?=\d{3}(?:\D|$))/g, '')
    .replace(',', '.')
  const parsed = Number(normalized)
  return Number.isFinite(parsed) ? parsed : null
}

function isNumericColumn(column: GenieColumn, rows: unknown[][], index: number) {
  if (NUMERIC_TYPE.test(column.type || '')) return true
  const samples = rows.slice(0, 12).map(row => row[index]).filter(value => value !== null && value !== undefined && value !== '')
  return samples.length > 0 && samples.every(value => numericValue(value) !== null)
}

function isTemporalColumn(column: GenieColumn, rows: unknown[][], index: number) {
  if (DATE_TYPE.test(column.type || '') || /(date|data|dia|m[eê]s|ano|hora|week|month|year)/i.test(column.name)) return true
  const samples = rows.slice(0, 8).map(row => String(row[index] ?? '')).filter(Boolean)
  return samples.length > 1 && samples.every(value => /^\d{4}-\d{2}(?:-\d{2})?/.test(value))
}

export function inferGenieChart(data: GenieData): GenieChartSpec | null {
  const columns = data.columns || []
  const rows = (data.rows || []).filter(row => Array.isArray(row))
  if (columns.length < 2 || rows.length < 2) return null

  const numericIndexes = columns
    .map((column, index) => isNumericColumn(column, rows, index) ? index : -1)
    .filter(index => index >= 0)
  const dimensionIndex = columns.findIndex((column, index) => !numericIndexes.includes(index) || isTemporalColumn(column, rows, index))
  const metricIndexes = numericIndexes.filter(index => index !== dimensionIndex).slice(0, 3)
  if (dimensionIndex < 0 || metricIndexes.length === 0) return null

  return {
    kind: isTemporalColumn(columns[dimensionIndex], rows, dimensionIndex) ? 'line' : 'bar',
    dimensionIndex,
    metricIndexes,
    rows: rows.slice(0, 20),
  }
}

