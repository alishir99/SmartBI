
export function Field({
  id,
  label,
  type,
  value,
  autoComplete,
  onChange,
  hint,
  autoFocus = false,
}: {
  id: string
  label: string
  type: string
  value: string
  autoComplete: string
  onChange: (value: string) => void
  hint?: string
  autoFocus?: boolean
}) {
  const hintId = hint ? `${id}-hint` : undefined
  return (
    <div>
      <label htmlFor={id} className="block text-xs font-medium text-ink-secondary">
        {label}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        autoComplete={autoComplete}
        // Autofocus is right here and only here: these forms are single-purpose pages where
        // the first field is the only thing to do.
        autoFocus={autoFocus}
        aria-describedby={hintId}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1.5 h-10 w-full rounded-tile bg-surface-2 px-3.5 text-sm text-ink outline-none ring-hairline transition-shadow duration-200 focus:ring-1 focus:ring-accent"
      />
      {hint && (
        <p id={hintId} className="mt-1.5 text-2xs text-ink-muted">
          {hint}
        </p>
      )}
    </div>
  )
}
