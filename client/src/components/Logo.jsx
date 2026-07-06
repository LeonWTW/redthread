// RedThread logo — "thread-stitch R" (docs/plans/003): one continuous
// thread-red stroke draws the R, entering at a stitch dot and exiting as an
// underline tail. The mark carries the red; the wordmark stays ink.
// `draw` enables the one-time stroke-draw animation (Login only).

export default function Logo({ size = 24, withWordmark = false, draw = false, className = '' }) {
  const markClass = ['logo-mark', draw && 'logo-draw', !withWordmark && className]
    .filter(Boolean)
    .join(' ')
  const mark = (
    <svg
      className={markClass}
      width={size}
      height={size}
      viewBox="0 0 32 32"
      role="img"
      aria-label={withWordmark ? undefined : 'RedThread'}
      aria-hidden={withWordmark ? true : undefined}
    >
      <circle className="logo-dot logo-dot-start" cx="7" cy="28" r="1.9" />
      <path
        className="logo-path"
        pathLength="100"
        d="M7 28 V6 H15.5 C21 6 24 8.6 24 12.2 C24 15.8 21 18.4 15.5 18.4 H10.5 L20.5 28 Q22.5 30 25.5 30 H27"
        fill="none"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle className="logo-dot logo-dot-end" cx="29" cy="30" r="1.9" />
    </svg>
  )
  if (!withWordmark) return mark
  return (
    <span className={['logo-lockup', className].filter(Boolean).join(' ')}>
      {mark}
      <span className="logo-wordmark">RedThread</span>
    </span>
  )
}
