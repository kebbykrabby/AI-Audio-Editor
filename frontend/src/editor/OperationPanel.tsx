import AiActionsBar from "./AiActionsBar";

/**
 * Idle state of the editor's right column: the AI-actions surface (Find
 * fillers / Censor profanity / Ask AI).
 *
 * The deterministic-op UI (Trim/Delete/Fade/Volume/…) lives in
 * `<EditToolbar/>` — a horizontal strip mounted directly under the header.
 * Once a review flow is entered, Shell.tsx swaps this component out for the
 * matching review panel (FillerReviewPanel / ProfanityReviewPanel /
 * NlePlanReviewPanel), so at any moment the right column shows either the
 * "propose" surface or a live review.
 *
 * Kept as a named component (rather than inlining AiActionsBar in Shell) so
 * Step 7 can move it into a tabbed sidebar without touching Shell again.
 */
export default function OperationPanel() {
  return <AiActionsBar />;
}
