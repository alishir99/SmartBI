
type IconProps = {
  className?: string
  strokeWidth?: number
}

function Svg({
  className = 'h-4 w-4',
  strokeWidth = 1.5,
  children,
}: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  )
}

export const IconOverview = (p: IconProps) => (
  <Svg {...p}>
    <rect x="2.75" y="2.75" width="6" height="6" rx="1.75" />
    <rect x="11.25" y="2.75" width="6" height="6" rx="1.75" />
    <rect x="2.75" y="11.25" width="6" height="6" rx="1.75" />
    <rect x="11.25" y="11.25" width="6" height="6" rx="1.75" />
  </Svg>
)

export const IconProducts = (p: IconProps) => (
  <Svg {...p}>
    <path d="M10 2.5 17 6v8l-7 3.5L3 14V6l7-3.5Z" />
    <path d="M3 6l7 3.5L17 6" />
    <path d="M10 9.5v8" />
  </Svg>
)

export const IconGeo = (p: IconProps) => (
  <Svg {...p}>
    <path d="M10 17.5s5.25-4.6 5.25-9a5.25 5.25 0 1 0-10.5 0c0 4.4 5.25 9 5.25 9Z" />
    <circle cx="10" cy="8.25" r="1.9" />
  </Svg>
)

export const IconPin = (p: IconProps) => (
  <Svg {...p}>
    <path d="M7.5 2.75h5l-.6 4.1 2.35 2.35H5.75L8.1 6.85l-.6-4.1Z" />
    <path d="M10 9.2v8.05" />
  </Svg>
)

export const IconPinFilled = ({ className = 'h-4 w-4' }: IconProps) => (
  <svg viewBox="0 0 20 20" fill="currentColor" className={className} aria-hidden="true" focusable="false">
    <path d="M7.5 2.75h5l-.6 4.1 2.35 2.35H5.75L8.1 6.85l-.6-4.1Z" />
    <rect x="9.25" y="9.2" width="1.5" height="8.05" rx="0.75" />
  </svg>
)

export const IconDownload = (p: IconProps) => (
  <Svg {...p}>
    <path d="M10 3v9" />
    <path d="M6.25 8.5 10 12.25 13.75 8.5" />
    <path d="M3.5 15.5h13" />
  </Svg>
)

export const IconShare = (p: IconProps) => (
  <Svg {...p}>
    <path d="M10 12.75V3.25" />
    <path d="M6.5 6.5 10 3l3.5 3.5" />
    <path d="M4.25 11v4.25a1.5 1.5 0 0 0 1.5 1.5h8.5a1.5 1.5 0 0 0 1.5-1.5V11" />
  </Svg>
)

export const IconLink = (p: IconProps) => (
  <Svg {...p}>
    <path d="M8.25 11.75 11.75 8.25" />
    <path d="M7.25 12.75 5.4 14.6a2.5 2.5 0 1 1-3.5-3.5l2.5-2.5a2.5 2.5 0 0 1 3.5 0" />
    <path d="M12.75 7.25l1.85-1.85a2.5 2.5 0 1 1 3.5 3.5l-2.5 2.5a2.5 2.5 0 0 1-3.5 0" />
  </Svg>
)

export const IconChevron = (p: IconProps) => (
  <Svg {...p}>
    <path d="M7.5 4.5 13 10l-5.5 5.5" />
  </Svg>
)

export const IconChevronDown = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 7.75 10 12.75l5-5" />
  </Svg>
)

export const IconArrowUp = (p: IconProps) => (
  <Svg {...p}>
    <path d="M10 16V4.5" />
    <path d="M5.25 9.25 10 4.5l4.75 4.75" />
  </Svg>
)

export const IconArrowDown = (p: IconProps) => (
  <Svg {...p}>
    <path d="M10 4v11.5" />
    <path d="M14.75 10.75 10 15.5l-4.75-4.75" />
  </Svg>
)

export const IconMinus = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4.5 10h11" />
  </Svg>
)

export const IconDatabase = (p: IconProps) => (
  <Svg {...p}>
    <ellipse cx="10" cy="5" rx="6" ry="2.4" />
    <path d="M4 5v10c0 1.33 2.69 2.4 6 2.4s6-1.07 6-2.4V5" />
    <path d="M4 10c0 1.33 2.69 2.4 6 2.4s6-1.07 6-2.4" />
  </Svg>
)

export const IconCheck = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4.5 10.75 8 14.25l7.5-8.5" />
  </Svg>
)

export const IconInfo = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="10" cy="10" r="7.25" />
    <path d="M10 9v4.5" />
    <path d="M10 6.6h.01" strokeWidth={2} />
  </Svg>
)

export const IconShield = (p: IconProps) => (
  <Svg {...p}>
    <path d="M10 2.75l5.75 2.1v5.15c0 3.4-2.4 6.15-5.75 7.25-3.35-1.1-5.75-3.85-5.75-7.25V4.85L10 2.75Z" />
    <path d="M7.6 10.1 9.4 11.9l3.2-3.4" />
  </Svg>
)

export const IconQuestion = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="10" cy="10" r="7.25" />
    <path d="M8.05 7.9a1.95 1.95 0 1 1 2.9 1.7c-.6.35-.95.75-.95 1.5" />
    <path d="M10 14.1h.01" strokeWidth={2} />
  </Svg>
)

export const IconSend = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3.75 10h11" />
    <path d="M10.25 5.5 14.75 10l-4.5 4.5" />
  </Svg>
)

export const IconStop = (p: IconProps) => (
  <Svg {...p}>
    <rect x="5.5" y="5.5" width="9" height="9" rx="2" />
  </Svg>
)

export const IconTrash = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3.75 6h12.5" />
    <path d="M8.25 3.5h3.5" />
    <path d="M5.5 6l.6 9.1a1.5 1.5 0 0 0 1.5 1.4h4.8a1.5 1.5 0 0 0 1.5-1.4L14.5 6" />
    <path d="M8.5 9v4.5M11.5 9v4.5" />
  </Svg>
)

export const IconSun = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="10" cy="10" r="3.4" />
    <path d="M10 2.5v1.6M10 15.9v1.6M2.5 10h1.6M15.9 10h1.6M4.7 4.7l1.15 1.15M14.15 14.15l1.15 1.15M15.3 4.7l-1.15 1.15M5.85 14.15 4.7 15.3" />
  </Svg>
)

export const IconMoon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M15.5 12.4A6.2 6.2 0 0 1 7.6 4.5a6.5 6.5 0 1 0 7.9 7.9Z" />
  </Svg>
)

export const IconLogout = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12.5 6V4.5A1.5 1.5 0 0 0 11 3H5.5A1.5 1.5 0 0 0 4 4.5v11A1.5 1.5 0 0 0 5.5 17H11a1.5 1.5 0 0 0 1.5-1.5V14" />
    <path d="M8.75 10h8" />
    <path d="M14 7.25 16.75 10 14 12.75" />
  </Svg>
)

export const IconEmptyChart = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 16.5h14" />
    <path d="M3 16.5V3.5" />
    <path d="M6.25 13.5v-2.75M9.75 13.5V8M13.25 13.5v-4.25M16.75 13.5V6" />
  </Svg>
)

export const IconSparkle = (p: IconProps) => (
  <Svg {...p}>
    <path d="M8 2.75 9.4 6.6 13.25 8 9.4 9.4 8 13.25 6.6 9.4 2.75 8 6.6 6.6 8 2.75Z" />
    <path d="M14.5 12.25l.7 1.55 1.55.7-1.55.7-.7 1.55-.7-1.55-1.55-.7 1.55-.7.7-1.55Z" />
  </Svg>
)

/** The MCP boundary: the contract the model has to go through to reach any data. */
export const IconPlug = (p: IconProps) => (
  <Svg {...p}>
    <path d="M7.5 2.75v3.5M12.5 2.75v3.5" />
    <path d="M5 6.25h10v2.5a5 5 0 0 1-10 0v-2.5Z" />
    <path d="M10 13.75v3.5" />
  </Svg>
)

export function Spinner({ className = 'h-3.5 w-3.5' }: IconProps) {
  return (
    <svg viewBox="0 0 20 20" className={`${className} animate-spin`} aria-hidden="true">
      <circle cx="10" cy="10" r="7" fill="none" stroke="currentColor" strokeWidth="2" opacity="0.2" />
      <path
        d="M17 10a7 7 0 0 0-7-7"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  )
}
