import type { Column, ResultRow } from '../types'
import { formatCell } from '../lib/format'

/** The table view every chart can fall back to. */
export function DataTable({
  columns,
  rows,
  caption,
}: {
  columns: Column[]
  rows: ResultRow[]
  caption?: string
}) {
  return (
    <div className="quiet-scroll -mx-1 overflow-x-auto px-1">
      <table className="w-full min-w-[28rem] border-collapse text-sm">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr className="hairline-b">
            {columns.map((column, index) => (
              <th
                key={column.key}
                scope="col"
                className={`whitespace-nowrap px-3 pb-2.5 pt-0 text-xs font-medium text-ink-muted ${
                  index === 0 ? 'text-left' : 'text-right'
                }`}
              >
                {column.label}
                {column.unit === 'SEK' && (
                  <span className="ml-1 font-normal normal-case">(kr, exkl. moms)</span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex} className="hairline-b last:border-b-0">
              {columns.map((column, index) => (
                <td
                  key={column.key}
                  className={`px-3 py-2.5 ${
                    index === 0
                      ? 'text-left text-ink'
                      : 'tabular text-right text-ink-secondary'
                  }`}
                >
                  {formatCell(row[column.key] ?? null, column)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
