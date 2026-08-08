/** The model sends the spec, not the data - rows come from /api/result/{query_id}, so a
 * hallucinated number can never reach this component. */

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  LineChart,
  Pie,
  PieChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { TooltipProps } from 'recharts'
import type { ChartSpec, Column, ResultRow } from '../types'
import { CHART_INK, MARK, SERIES_MUTED } from './palette'
import { axisCategoryLabel, prepareChart, type PreparedChart } from './prepare'
import { ChartTooltip } from './ChartTooltip'
import { DataTable } from './DataTable'
import { pointQuestion } from '../lib/questions'
import { columnLabel, plural, t } from '../lib/i18n'
import { formatCell, formatKpiValue, formatMoneyOnScale, formatNumber } from '../lib/format'

type Props = {
  spec: ChartSpec
  columns: Column[]
  rows: ResultRow[]
  height?: number
  /** Clicking a mark asks about that value; mouse-only, so the table view's first column
   * (real buttons) gives the same questions a keyboard path. */
  onAsk?: (question: string) => void
}

const AXIS_TICK = { fill: CHART_INK.axisText, fontSize: 11 }
const MARGIN = { top: 4, right: 8, bottom: 0, left: 0 }

export function Chart({ spec, columns, rows, height = 280, onAsk }: Props) {
  if (rows.length === 0) return <EmptyPlot height={height} />

  const prepared = prepareChart(spec, columns, rows)

  if (spec.type === 'table') {
    return (
      <DataTable
        columns={prepared.columns}
        rows={prepared.rows}
        caption={spec.title}
        onAsk={onAsk}
      />
    )
  }
  if (spec.type === 'kpi') {
    return <KpiPlot prepared={prepared} />
  }

  // A sideways chart grows with its rows instead of squeezing them: the caller's height is a
  // floor, not a ceiling.
  const sideways = isSideways(spec, prepared)
  const plotHeight = sideways
    ? Math.max(height, sidewaysHeight(prepared.rows.length))
    : height

  // Recharts emits a bare <svg> with no accessible name - without this a screen reader found
  // nothing here at all.
  const description = describeChart(spec, prepared)

  /* Unit sits beside the axis, not on it, to avoid overlapping the top tick. It follows the
     value axis - bottom on a sideways chart, since top-left would read as labelling categories. */
  const unit = prepared.scale?.unit ?? prepared.unit
  const unitLabel = unit ? (
    <p className={`text-2xs text-ink-muted ${sideways ? 'mt-1 text-right' : 'mb-1'}`}>{unit}</p>
  ) : null

  return (
    <figure className="m-0">
      {!sideways && unitLabel}
      <div style={{ height: plotHeight }} role="img" aria-label={description}>
        <ResponsiveContainer width="100%" height="100%">
          {plot(spec, prepared, sideways, onAsk && markClick(prepared, onAsk))}
        </ResponsiveContainer>
      </div>
      {sideways && unitLabel}
      <Legend prepared={prepared} />
      {/* Drawn only when marker_label exists too - an annotation nobody can read is just
          decoration. */}
      {spec.markers.length > 0 && spec.marker_label && !sideways && (
        <p className="mt-2 text-2xs text-ink-muted">{spec.marker_label}</p>
      )}
      {prepared.folded && (
        <p className="mt-2 text-2xs text-ink-muted">
          {t('chart.folded_note', { other: t('card.other') })}
        </p>
      )}
      {prepared.hidden > 0 && (
        <p className="mt-2 text-2xs text-ink-muted">
          Visar de {formatNumber(prepared.rows.length)} största av{' '}
          {formatNumber(prepared.rows.length + prepared.hidden)}. Välj Tabell eller CSV för
          resten.
        </p>
      )}
      {/* sr-only, not hidden: must stay in the accessibility tree. Title already shows in the
          card header, so showing it here too would be noise. */}
      <figcaption className="sr-only">{description}</figcaption>
    </figure>
  )
}

const CHART_KIND: Record<string, string> = {
  line: 'Linjediagram',
  bar: 'Stapeldiagram',
  stacked_bar: 'Staplat stapeldiagram',
  area: 'Ytdiagram',
  pie: 'Cirkeldiagram',
}

/** The sentence a screen reader announces in place of the plot. */
export function describeChart(spec: ChartSpec, prepared: PreparedChart): string {
  const kind = CHART_KIND[spec.type] ?? 'Diagram'
  const parts = [`${kind}: ${spec.title || 'utan titel'}`]

  const measures = (prepared.slices.length > 0 ? prepared.slices : prepared.series)
    .map((series) => series.label)
    .filter(Boolean)
  if (measures.length > 0) {
    parts.push(`visar ${measures.join(', ')}`)
  }
  if (prepared.xColumn) {
    const dimension = columnLabel(prepared.xColumn.key, prepared.xColumn.label).toLowerCase()
    parts.push(t('tool.per', { dimension }))
  }
  parts.push(plural(prepared.rows.length, 'value'))
  if (prepared.scale?.unit) {
    parts.push(`i ${prepared.scale.unit}`)
  }
  if (prepared.folded) {
    parts.push(t('card.other_note'))
  }
  if (prepared.hidden > 0) {
    parts.push(`${prepared.hidden} rader visas inte i diagrammet`)
  }
  // Points at the actual toggle, not a vague "table below": the table replaces the chart via
  // the Diagram/Tabell control in the card's actions.
  return `${parts.join(', ')}. Välj Tabell för att läsa samma siffror som text.`
}

type MarkClick = { onClick: (state: { activeLabel?: string | number }) => void; className: string }

/** One handler on the whole chart, not per mark: Recharts reports which category was clicked,
 * same answer whether it's a bar, point, or stacked segment. */
function markClick(prepared: PreparedChart, onAsk: (question: string) => void): MarkClick {
  return {
    onClick: (state) => {
      const label = state?.activeLabel
      if (label !== undefined && label !== null && label !== '') {
        onAsk(pointQuestion(prepared.xColumn, String(label)))
      }
    },
    className: 'cursor-pointer',
  }
}

/** Recharts wants a single element child, so each type returns one complete chart. */
function plot(spec: ChartSpec, prepared: PreparedChart, sideways: boolean,
              click?: MarkClick) {
  const { rows, series } = prepared
  const stacked = spec.type === 'stacked_bar'

  if (spec.type === 'pie') {
    const nameKey = prepared.xColumn?.key ?? 'name'
    const valueKey = series[0]?.key ?? 'value'
    return (
      <PieChart margin={MARGIN}>
        <Pie
          data={rows}
          dataKey={valueKey}
          nameKey={nameKey}
          innerRadius="56%"
          outerRadius="82%"
          paddingAngle={1}
          stroke={CHART_INK.surface}
          strokeWidth={MARK.surfaceGap}
          isAnimationActive={false}
        >
          {rows.map((row, index) => (
            <Cell key={String(row[nameKey] ?? index)} fill={sliceColor(prepared, index)} />
          ))}
        </Pie>
        <Tooltip content={pieTooltip(prepared)} cursor={false} />
      </PieChart>
    )
  }

  const axes = buildAxes(prepared, sideways, sideways ? [] : spec.markers)

  if (spec.type === 'line') {
    return (
      <LineChart data={rows} margin={MARGIN} {...click}>
        {axes}
        {/* Recharts paints in child order, so the muted comparison is drawn first and the
            current period stays on top wherever the two cross. */}
        {[...series].sort((a, b) => Number(b.muted) - Number(a.muted)).map((descriptor) => (
          <Line
            key={descriptor.key}
            type="monotone"
            dataKey={descriptor.key}
            name={descriptor.label}
            stroke={descriptor.color}
            strokeWidth={MARK.lineWidth}
            strokeDasharray={descriptor.muted ? MARK.compareDash : undefined}
            dot={rows.length <= 12 && !descriptor.muted
              ? { r: MARK.dotRadius, strokeWidth: 0, fill: descriptor.color }
              : false}
            activeDot={{ r: MARK.dotRadius + 1, strokeWidth: 2,
                         stroke: CHART_INK.surface, fill: descriptor.color }}
            isAnimationActive={false}
          />
        ))}
      </LineChart>
    )
  }

  if (spec.type === 'area') {
    return (
      <AreaChart data={rows} margin={MARGIN} {...click}>
        {axes}
        {series.map((descriptor) => (
          <Area
            key={descriptor.key}
            type="monotone"
            dataKey={descriptor.key}
            name={descriptor.label}
            stroke={descriptor.color}
            strokeWidth={MARK.lineWidth}
            fill={descriptor.color}
            fillOpacity={MARK.areaOpacity}
            isAnimationActive={false}
          />
        ))}
      </AreaChart>
    )
  }

  const bar = (descriptor: (typeof series)[number]) => (
    <Bar
      key={descriptor.key}
      dataKey={descriptor.key}
      name={descriptor.label}
      fill={descriptor.color}
      stackId={stacked ? 'stack' : undefined}
      maxBarSize={MARK.barMaxSize}
      radius={
        stacked
          ? 0
          : sideways
            ? [0, MARK.barRadius, MARK.barRadius, 0]
            : [MARK.barRadius, MARK.barRadius, 0, 0]
      }
      isAnimationActive={false}
    />
  )

  // A moving average shares the axis with the bars it averages but isn't drawn as one: it's a
  // shape across periods, which only a line can show.
  const averages = sideways ? [] : series.filter((descriptor) => descriptor.line)
  if (averages.length > 0) {
    return (
      <ComposedChart data={rows} margin={MARGIN} {...click}>
        {axes}
        {series.filter((descriptor) => !descriptor.line).map(bar)}
        {averages.map((descriptor) => (
          <Line
            key={descriptor.key}
            type="monotone"
            dataKey={descriptor.key}
            name={descriptor.label}
            stroke={descriptor.color}
            strokeWidth={MARK.lineWidth}
            dot={false}
            // Average has gaps where its window was short/incomplete; connecting across them
            // would draw an average over periods it never covered.
            connectNulls={false}
            activeDot={{ r: MARK.dotRadius, strokeWidth: 2,
                         stroke: CHART_INK.surface, fill: descriptor.color }}
            isAnimationActive={false}
          />
        ))}
      </ComposedChart>
    )
  }

  return (
    <BarChart data={rows} margin={MARGIN} layout={sideways ? 'vertical' : 'horizontal'}
              {...click}>
      {axes}
      {series.map(bar)}
    </BarChart>
  )
}

function isSideways(spec: ChartSpec, prepared: PreparedChart): boolean {
  if (spec.type !== 'bar' || !prepared.xColumn || prepared.xColumn.type === 'date') return false
  const longest = Math.max(
    0,
    ...prepared.rows.map((row) => String(row[prepared.xColumn?.key ?? ''] ?? '').length),
  )
  return prepared.rows.length > 6 || longest > 14
}

/** Height a sideways chart needs so every category row keeps a legible band. */
function sidewaysHeight(rowCount: number): number {
  return rowCount * 34 + 28
}

/** Returns an array, not a fragment: Recharts scans its direct children for axes/grid/tooltip,
 * and a fragment hides them from that scan - the chart would silently render with no axes. */
function buildAxes(prepared: PreparedChart, sideways: boolean, markers: string[] = []) {
  const categoryKey = prepared.xColumn?.key
  const tooltip = (
    <Tooltip
      key="tooltip"
      content={<ChartTooltip columns={prepared.columns} labelFormatter={(v) => xLabel(prepared, v)} />}
      cursor={{ fill: 'var(--surface-2)', stroke: CHART_INK.grid }}
    />
  )

  if (sideways) {
    return [
      <CartesianGrid key="grid" stroke={CHART_INK.grid} strokeDasharray="0" horizontal={false} />,
      <XAxis
        key="x"
        type="number"
        tick={AXIS_TICK}
        tickMargin={8}
        tickFormatter={(value: number) => yLabel(prepared, value)}
      />,
      <YAxis
        key="y"
        type="category"
        dataKey={categoryKey}
        tick={AXIS_TICK}
        tickMargin={8}
        width={categoryAxisWidth(prepared)}
        interval={0}
        tickFormatter={(value: string) => tickLabel(prepared, value, true)}
      />,
      tooltip,
    ]
  }

  return [
    <CartesianGrid key="grid" stroke={CHART_INK.grid} strokeDasharray="0" vertical={false} />,
    <XAxis
      key="x"
      dataKey={categoryKey}
      tick={AXIS_TICK}
      tickMargin={10}
      minTickGap={12}
      interval="preserveStartEnd"
      tickFormatter={(value: string) => tickLabel(prepared, value, false)}
    />,
    <YAxis
      key="y"
      tick={AXIS_TICK}
      tickMargin={8}
      width={52}
      tickFormatter={(value: number) => yLabel(prepared, value)}
    />,
    tooltip,
    // Annotation, not a series - drawn only on a vertical axis, since a marker on a sideways
    // ranked bar would name a category, not a moment.
    ...markers.map((value) => (
      <ReferenceLine
        key={`marker-${value}`}
        x={value}
        stroke={SERIES_MUTED}
        strokeDasharray={MARK.compareDash}
        strokeWidth={1}
        ifOverflow="hidden"
      />
    )),
  ]
}

/** Wide enough for the labels, capped so the bars never lose more than a third of the width. */
function categoryAxisWidth(prepared: PreparedChart): number {
  const key = prepared.xColumn?.key
  const longest = Math.max(
    0,
    ...prepared.rows.map((row) => xLabel(prepared, String(row[key ?? ''] ?? '')).length),
  )
  return Math.min(190, Math.max(96, longest * 6.4 + 12))
}

/** Pie colour follows the slice, not the measure, so it reads `slices` - built by prepare.ts
 * from the dimension values, in the same row order Recharts draws. */
function sliceColor(prepared: PreparedChart, index: number): string {
  return prepared.slices[index]?.color ?? 'var(--series-1)'
}

function pieTooltip(prepared: PreparedChart) {
  const valueColumn = prepared.columns.find((column) => column.type === 'number')
  return ({ active, payload }: TooltipProps<number, string>) => {
    if (!active || !payload?.length) return null
    const entry = payload[0]
    const value = typeof entry.value === 'number' ? entry.value : null
    return (
      <div className="pointer-events-none rounded-xl bg-surface px-3.5 py-2.5 shadow-pop ring-hairline">
        <p className="text-xs text-ink-secondary">{String(entry.name ?? '')}</p>
        <p className="tabular text-sm font-medium text-ink">
          {value !== null && valueColumn ? formatCell(value, valueColumn) : '–'}
        </p>
      </div>
    )
  }
}

/** Full label - for the tooltip, which has room for the whole name. */
function xLabel(prepared: PreparedChart, value: string): string {
  return prepared.xColumn ? formatCell(value, prepared.xColumn) : value
}

function tickLabel(prepared: PreparedChart, value: string, sideways: boolean): string {
  const formatted = xLabel(prepared, value)
  if (prepared.xColumn?.type === 'date') return formatted
  return axisCategoryLabel(formatted, sideways || prepared.rows.length <= 6)
}

function yLabel(prepared: PreparedChart, value: number): string {
  if (prepared.scale) return formatMoneyOnScale(value, prepared.scale)
  if (prepared.unit === '%' || prepared.unit === 'p.e.')
    return formatNumber(value, value % 1 === 0 ? 0 : 1)
  return formatNumber(value)
}

/** Custom, not Recharts' legend: relief text for light-mode hues that fall below 3:1 contrast
 * on white, so it ships on every multi-series chart and is never dropped for space. */
function Legend({ prepared }: { prepared: PreparedChart }) {
  // Pie always gets a legend, even at count 1: wedges carry no axis, so without it the colour
  // names nothing.
  const isPie = prepared.slices.length > 0
  const entries = isPie ? prepared.slices : prepared.series
  if (entries.length === 0 || (!isPie && entries.length < 2)) return null
  return (
    <ul className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1.5">
      {entries.map((descriptor) => (
        <li key={descriptor.key} className="flex items-center gap-2 text-xs text-ink-secondary">
          <span
            className="h-2 w-2 shrink-0 rounded-full"
            style={{ backgroundColor: descriptor.color }}
            aria-hidden="true"
          />
          {descriptor.label}
        </li>
      ))}
    </ul>
  )
}

function KpiPlot({ prepared }: { prepared: PreparedChart }) {
  const descriptor = prepared.series[0]
  const column = prepared.columns.find((candidate) => candidate.key === descriptor?.key)
  const raw = descriptor ? prepared.rows[0]?.[descriptor.key] : null
  const value = typeof raw === 'number' ? raw : null

  return (
    <p className="tabular py-4 text-3xl font-semibold tracking-tight text-ink">
      {value !== null && column ? formatKpiValue(value, column.unit ?? 'st') : '–'}
    </p>
  )
}

function EmptyPlot({ height }: { height: number }) {
  return (
    <div
      className="flex items-center justify-center rounded-tile bg-surface-2 text-sm text-ink-muted"
      style={{ height }}
    >
      Inga rader matchade urvalet.
    </div>
  )
}
