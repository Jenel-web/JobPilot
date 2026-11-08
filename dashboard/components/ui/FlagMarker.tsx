import { TriangleIcon } from "./icons";

/** Amber triangle plus a count: "N answers were guessed by AI". */
export function FlagMarker({ count }: { count: number }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-label text-jp-ink" aria-label={`${count} flagged`}>
      <TriangleIcon className="text-jp-amber" />
      <span className="tabular">{count}</span>
    </span>
  );
}
