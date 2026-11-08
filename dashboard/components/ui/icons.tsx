/**
 * Small inline SVG icons. DESIGN.md: "the mockups use simple inline SVG", and no
 * icon library is used. Every icon takes its colour from `currentColor`, so the
 * colour comes from a token class on the parent (e.g. `text-jp-amber`).
 */

type IconProps = { size?: number; className?: string };

/** Amber triangle used by the FlagMarker (an AI-guessed answer). */
export function TriangleIcon({ size = 14, className }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 14 14" aria-hidden="true" className={className}>
      <path d="M7 1.5L13 12.5H1Z" fill="currentColor" />
    </svg>
  );
}

/** Circle with a tick, used by EmptyState. */
export function CheckCircleIcon({ size = 28, className }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" aria-hidden="true" className={className}>
      <circle cx="14" cy="14" r="11" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path
        d="M9 14.5l3.2 3L19 11"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** Close X for the Drawer. */
export function CloseIcon({ size = 16, className }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true" className={className}>
      <path d="M3 3l10 10M13 3L3 13" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

/** Lock for "filled locally / encrypted" tags. */
export function LockIcon({ size = 12, className }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 12 12" aria-hidden="true" className={className}>
      <rect x="2" y="5.2" width="8" height="5.3" rx="1.2" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <path d="M4 5.2V3.8a2 2 0 0 1 4 0v1.4" fill="none" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  );
}
