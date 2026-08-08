
export function Skeleton({ className = '' }: { className?: string }) {
  return (
    <div
      className={`animate-shimmer rounded-lg ${className}`}
      style={{
        background:
          'linear-gradient(90deg, var(--surface-2) 25%, var(--surface-3) 50%, var(--surface-2) 75%)',
        backgroundSize: '200% 100%',
      }}
      aria-hidden="true"
    />
  )
}

export function KpiSkeleton() {
  return (
    <div className="rounded-tile bg-surface p-5 shadow-card ring-hairline sm:p-6">
      <Skeleton className="h-3.5 w-24" />
      <Skeleton className="mt-4 h-8 w-32" />
      <Skeleton className="mt-4 h-3 w-40" />
    </div>
  )
}

export function CardSkeleton({ height = 300 }: { height?: number }) {
  return (
    <div className="rounded-card bg-surface p-6 shadow-card ring-hairline sm:p-7">
      <Skeleton className="h-4 w-52" />
      <Skeleton className="mt-3 h-3 w-72 max-w-full" />
      <div className="mt-7" style={{ height }}>
        <Skeleton className="h-full w-full" />
      </div>
      <Skeleton className="mt-7 h-7 w-64 rounded-pill" />
    </div>
  )
}
