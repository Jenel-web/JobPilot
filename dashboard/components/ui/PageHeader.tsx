/**
 * Page title row: Newsreader 28 px title on the left (with an optional
 * one-line summary under it), primary actions on the right.
 */
export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex items-end justify-between gap-4">
      <div className="flex flex-col gap-1.5">
        <h1 className="font-serif text-[28px] font-medium leading-[1.15]">{title}</h1>
        {subtitle && <p className="text-sm text-jp-ink-2">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2.5">{actions}</div>}
    </div>
  );
}
