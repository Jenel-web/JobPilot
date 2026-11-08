/**
 * Text colour class for a bare score number in lists and tables.
 * Same thresholds as ScoreBadge: green 80+, amber 60-79, grey under 60.
 */
export function scoreTextClass(score: number): string {
  if (score >= 80) return "text-jp-status-submitted";
  if (score >= 60) return "text-jp-amber";
  return "text-jp-status-new";
}
