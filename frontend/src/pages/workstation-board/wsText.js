// A machine's capacity line: "396 Kgs/day", or per operation when its speed depends on what it
// makes: "collar 960 · cuff 1,920 Pcs/day".
const n = (v) => Number(v || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })

export const hasRates = (m) => !!(m && m.per_day_by_operation && Object.keys(m.per_day_by_operation).length)

export function capText(m) {
  const unit = m.uom || 'kg'
  if (!hasRates(m)) return `${n(m.per_day)} ${unit}/day`
  const parts = Object.entries(m.per_day_by_operation)
    .map(([op, v]) => `${op.replace(/\s+knitting$/i, '')} ${n(v)}`)
  return `${parts.join(' · ')} ${unit}/day`
}
