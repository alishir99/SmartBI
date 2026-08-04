/** Turns a streamed tool_call into the short line shown on a progress chip. */

import { columnLabel, t } from './i18n'

/** The tool's own name is an internal identifier; "query_sales" on a retailer's screen is noise. */
export function toolLabel(tool: string): string {
  const label = t(`tool.${tool}`)
  return label === `tool.${tool}` ? tool : label
}

function firstString(value: unknown): string | null {
  if (typeof value === 'string' && value) return value
  if (Array.isArray(value)) {
    const found = value.find((entry) => typeof entry === 'string' && entry)
    return typeof found === 'string' ? found : null
  }
  return null
}

/** `hämtar Stockholms län…` / `fetching Stockholms län…` */
export function describeToolCall(tool: string, args: Record<string, unknown>): string {
  switch (tool) {
    case 'get_capabilities':
      return t('tool.doing.capabilities')

    case 'resolve_entities': {
      const text = firstString(args.text)
      return text ? t('tool.doing.resolve', { text }) : t('tool.doing.resolve_generic')
    }

    case 'query_market_share':
      return t('tool.doing.market_share')

    case 'query_sales':
    default: {
      const filters = (args.filters ?? {}) as Record<string, unknown>
      const region = firstString(filters.region)
      const channel = firstString(filters.channel)
      const dimensions = Array.isArray(args.dimensions) ? (args.dimensions as string[]) : []
      const scope = region ?? (channel ? channelLabel(channel) : null)
      // The dimension names come off the same key table the chart axes use, so a chip and the
      // axis under it cannot disagree about what "region" is called.
      const grain = dimensions.length
        ? t('tool.per', { dimension: columnLabel(dimensions[0], dimensions[0]).toLowerCase() })
        : null

      if (scope && grain) return t('tool.doing.scoped', { grain, scope })
      if (scope) return t('tool.doing.scope_only', { scope })
      if (grain) return t('tool.doing.grain_only', { grain })
      return t('tool.doing.sales')
    }
  }
}

function channelLabel(channel: string): string {
  return channel === 'online' ? t('channel.online') : t('channel.physical')
}
