/** Turns a streamed tool_call into the short Swedish line shown on a progress chip. */

const TOOL_LABELS: Record<string, string> = {
  get_capabilities: 'get_capabilities',
  resolve_entities: 'resolve_entities',
  query_sales: 'query_sales',
  query_market_share: 'query_market_share',
  dashboard: 'dashboard',
}

export function toolLabel(tool: string): string {
  return TOOL_LABELS[tool] ?? tool
}

function firstString(value: unknown): string | null {
  if (typeof value === 'string' && value) return value
  if (Array.isArray(value)) {
    const found = value.find((entry) => typeof entry === 'string' && entry)
    return typeof found === 'string' ? found : null
  }
  return null
}

/** `hämtar Stockholms län…` */
export function describeToolCall(tool: string, args: Record<string, unknown>): string {
  switch (tool) {
    case 'get_capabilities':
      return 'läser vad datan innehåller'

    case 'resolve_entities': {
      const text = firstString(args.text)
      return text ? `slår upp "${text}"` : 'slår upp entiteter'
    }

    case 'query_market_share':
      return 'hämtar andel av kategori'

    case 'query_sales':
    default: {
      const filters = (args.filters ?? {}) as Record<string, unknown>
      const region = firstString(filters.region)
      const channel = firstString(filters.channel)
      const dimensions = Array.isArray(args.dimensions) ? (args.dimensions as string[]) : []
      const scope = region ?? (channel ? channelLabel(channel) : null)
      const grain = dimensions.length ? DIMENSION_LABELS[dimensions[0]] ?? dimensions[0] : null

      if (scope && grain) return `hämtar ${grain} i ${scope}`
      if (scope) return `hämtar ${scope}`
      if (grain) return `hämtar ${grain}`
      return 'hämtar försäljning'
    }
  }
}

function channelLabel(channel: string): string {
  return channel === 'online' ? 'onlinekanalen' : 'fysiska butiker'
}

const DIMENSION_LABELS: Record<string, string> = {
  month: 'per månad',
  iso_week: 'per vecka',
  day: 'per dag',
  product: 'per produkt',
  category: 'per kategori',
  region: 'per län',
  store: 'per butik',
  channel: 'per kanal',
}
