import { Button } from "./Button";
import { CheckCircleIcon } from "./icons";

/** Icon + one sentence + (optionally) one button, in a dashed 1 px border. */
export function EmptyState({
  message,
  actionLabel,
  actionHref,
  onAction,
}: {
  message: string;
  actionLabel?: string;
  actionHref?: string;
  onAction?: () => void;
}) {
  return (
    <div className="flex flex-col items-start gap-2.5 rounded-card border border-dashed border-jp-line-strong p-6">
      <CheckCircleIcon className="text-jp-brand" />
      <div className="text-sm text-jp-ink">{message}</div>
      {actionLabel &&
        (actionHref ? (
          <Button href={actionHref} size="sm">
            {actionLabel}
          </Button>
        ) : (
          <Button size="sm" onClick={onAction}>
            {actionLabel}
          </Button>
        ))}
    </div>
  );
}
