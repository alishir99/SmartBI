import type { Column, ResultRow } from '../types'
import { formatCell, isCurrency } from '../lib/format'
import { pointQuestion } from '../lib/questions'
import { columnLabel } from '../lib/i18n'

export function DataTable({
  columns,
  rows,
  caption,
  onAsk,
}: {
  columns: Column[]
  rows: ResultRow[]
  caption?: string
  /** Makes the first column ask about its row - the keyboard path to the chart's click. */
  onAsk?: (question: string) => void
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
                {columnLabel(column.key, column.label)}
                {isCurrency(column.unit) && (
                  <span className="ml-1 font-normal normal-case">({column.unit})</span>
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
                  {index === 0 && onAsk ? (
                    <AskCell column={column} value={row[column.key] ?? null} onAsk={onAsk} />
                  ) : (
                    formatCell(row[column.key] ?? null, column)
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function AskCell({
  column,
  value,
  onAsk,
}: {
  column: Column
  value: string | number | null
  onAsk: (question: string) => void
}) {
  const text = formatCell(value, column)
  if (value === null || value === '') return <>{text}</>
  const question = pointQuestion(column, String(value))
  return (
    <button
      type="button"
      onClick={() => onAsk(question)}
      aria-label={question}
      className="text-left underline-offset-4 transition-colors duration-200 hover:text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
    >
      {text}
    </button>
  )
}
