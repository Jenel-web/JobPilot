import Link from "next/link";
import { cn } from "@/lib/cn";

export type ButtonVariant = "primary" | "secondary" | "danger" | "link";
export type ButtonSize = "md" | "sm" | "xs";

const VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-jp-brand text-white font-semibold",
  secondary: "border border-jp-line-strong bg-jp-surface text-jp-ink font-medium",
  danger: "bg-jp-danger text-white font-semibold",
  link: "bg-transparent text-jp-brand font-medium",
};

// md = 36 px (page actions), sm = 32 px (detail panel), xs = 30 px (banners)
const SIZES: Record<ButtonSize, string> = {
  md: "h-9 px-4 text-sm",
  sm: "h-8 px-3 text-label",
  xs: "h-[30px] px-3 text-label",
};

type ButtonProps = {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** When set, renders a navigation link that looks like a button. */
  href?: string;
  /** With `href`: open in a new tab (for Prosple / employer links). */
  external?: boolean;
  className?: string;
  children: React.ReactNode;
} & Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "className" | "children">;

/**
 * One primary button per view (DESIGN.md). Label it with the result,
 * e.g. "Submit approved (5)", not "Submit".
 */
export function Button({
  variant = "secondary",
  size = "md",
  href,
  external,
  className,
  children,
  ...rest
}: ButtonProps) {
  const classes = cn(
    "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-control transition-opacity",
    "disabled:cursor-not-allowed disabled:opacity-45",
    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-jp-brand",
    VARIANTS[variant],
    variant === "link" ? "h-9 px-3 text-sm" : SIZES[size],
    className,
  );

  if (href !== undefined) {
    return external ? (
      <a href={href} target="_blank" rel="noreferrer" className={classes}>
        {children}
      </a>
    ) : (
      <Link href={href} className={classes}>
        {children}
      </Link>
    );
  }

  return (
    <button type="button" {...rest} className={classes}>
      {children}
    </button>
  );
}
