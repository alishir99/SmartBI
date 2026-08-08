import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Spinner } from './Icons'

type Variant = 'primary' | 'secondary' | 'ghost' | 'quiet' | 'outline'
type Size = 'sm' | 'md' | 'lg'

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant
  size?: Size
  loading?: boolean
  icon?: ReactNode
  /** Icon-only buttons must still carry a label for screen readers. */
  iconOnly?: boolean
}

/** Pill-shaped: solid accent for primary, quiet ghost for everything else. */
const VARIANTS: Record<Variant, string> = {
  primary: 'bg-accent text-accent-fg hover:bg-accent-hover active:opacity-90 shadow-none',
  secondary:
    'bg-surface-2 text-ink hover:bg-surface-3 active:opacity-90 ring-1 ring-inset ring-hairline',
  ghost: 'bg-transparent text-ink-secondary hover:bg-surface-2 hover:text-ink',
  quiet: 'bg-transparent text-accent hover:bg-accent-soft',
  outline: 'bg-surface text-accent ring-1 ring-inset ring-hairline hover:bg-accent-soft',
}

const SIZES: Record<Size, string> = {
  sm: 'h-8 px-3.5 text-sm gap-1.5',
  md: 'h-10 px-5 text-base gap-2',
  lg: 'h-12 px-7 text-lg gap-2',
}

const ICON_SIZES: Record<Size, string> = {
  sm: 'h-8 w-8',
  md: 'h-10 w-10',
  lg: 'h-12 w-12',
}

export function Button({
  variant = 'secondary',
  size = 'md',
  loading = false,
  icon,
  iconOnly = false,
  className = '',
  children,
  disabled,
  type = 'button',
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      className={[
        'inline-flex shrink-0 items-center justify-center rounded-pill font-medium',
        'transition-[background-color,color,opacity,transform] duration-200 ease-out',
        'cursor-pointer select-none whitespace-nowrap',
        'disabled:pointer-events-none disabled:opacity-40',
        VARIANTS[variant],
        iconOnly ? ICON_SIZES[size] : SIZES[size],
        className,
      ].join(' ')}
      {...rest}
    >
      {loading ? <Spinner className={size === 'sm' ? 'h-3.5 w-3.5' : 'h-4 w-4'} /> : icon}
      {!iconOnly && children}
    </button>
  )
}
