import { StatusChip } from "@/components/ui/StatusChip";
import type { FillStatus } from "@/lib/api-types";

/**
 * A filled page's status as a chip. No new colours: "filled" (waiting for you to decide) uses the queued blue,
 * "submitted" the submitted green, "abandoned" the rejected grey. The text always names the status.
 */
const MAP = {
  filled: { status: "queued", label: "Filled" },
  submitted: { status: "submitted", label: "Submitted" },
  abandoned: { status: "rejected", label: "Abandoned" },
} as const;

export function FillStatusChip({ status }: { status: FillStatus }) {
  const m = MAP[status];
  return <StatusChip status={m.status} label={m.label} />;
}
