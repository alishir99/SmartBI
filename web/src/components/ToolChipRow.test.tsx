/** The tool chips under a question, which are the only view of what the agent actually did. */

import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { ToolChip } from '../lib/chat'
import { ToolChipRow } from './ChatPanel'

afterEach(cleanup)

const chip = (overrides: Partial<ToolChip>): ToolChip => ({
  id: 'chip-1',
  tool: 'query_sales',
  args: {},
  done: true,
  rowCount: 12,
  ...overrides,
})

describe('a tool chip', () => {
  it('reports the row count for a tool that returns rows', () => {
    render(<ToolChipRow chip={chip({ rowCount: 12 })} />)
    expect(screen.getByText(/12 rader/)).toBeDefined()
  })

  it('says nothing about rows for a tool that has none', () => {
    // get_capabilities and resolve_entities have no row concept, so the count arrived as 0 and
    // a lookup that succeeded read as one that found nothing: "✓ Uppslag · 0 rader".
    render(<ToolChipRow chip={chip({ tool: 'resolve_entities', rowCount: null })} />)
    expect(screen.queryByText(/rader/)).toBeNull()
  })
})
