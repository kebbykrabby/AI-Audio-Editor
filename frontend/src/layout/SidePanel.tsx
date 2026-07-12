import { useEffect } from "react";
import { History, MessageSquare, PanelRightClose, PanelRightOpen, ShieldAlert, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import AiTab from "../editor/AiTab";
import CensorTab from "../editor/CensorTab";
import FillersTab from "../editor/FillersTab";
import HistoryTab from "../editor/HistoryTab";
import { useEditorStore } from "../store/editorStore";

type Tab = "history" | "fillers" | "censor" | "ai";

const TABS: { id: Tab; icon: typeof History; label: string }[] = [
  { id: "history", icon: History, label: "History" },
  { id: "fillers", icon: Sparkles, label: "Fillers" },
  { id: "censor", icon: ShieldAlert, label: "Censor" },
  { id: "ai", icon: MessageSquare, label: "AI" },
];

/**
 * Right-side tabbed panel container mounted in Shell. Owns the active-tab
 * state and the collapse toggle. Tab content is rendered by dedicated
 * `<*Tab/>` components — this component doesn't know anything about the
 * review flows themselves.
 *
 * When an AI review is active (filler / profanity / NLE), the tab
 * switcher auto-jumps to the matching tab so the review UI is visible.
 */
export default function SidePanel({
  tab,
  setTab,
  collapsed,
  setCollapsed,
  width,
}: {
  tab: Tab;
  setTab: (t: Tab) => void;
  collapsed: boolean;
  setCollapsed: (v: boolean) => void;
  /** Width in pixels; controlled from Shell via ResizeHandle. */
  width: number;
}) {
  const activeFillerReview = useEditorStore((s) => s.activeFillerReview);
  const activeProfanityReview = useEditorStore((s) => s.activeProfanityReview);
  const activeNlePlanReview = useEditorStore((s) => s.activeNlePlanReview);

  // Auto-switch tab when a review becomes active so the UI matches the state.
  useEffect(() => {
    if (activeFillerReview) setTab("fillers");
  }, [activeFillerReview, setTab]);
  useEffect(() => {
    if (activeProfanityReview) setTab("censor");
  }, [activeProfanityReview, setTab]);
  useEffect(() => {
    if (activeNlePlanReview) setTab("ai");
  }, [activeNlePlanReview, setTab]);

  if (collapsed) {
    return (
      <button
        onClick={() => setCollapsed(false)}
        className="w-6 border-l border-border bg-card hover:bg-accent flex items-center justify-center shrink-0 transition-colors"
        title="Open panel"
        aria-label="Open side panel"
      >
        <PanelRightOpen className="w-3 h-3" />
      </button>
    );
  }

  return (
    <>
      <div
        className="border-l border-border bg-card flex flex-col shrink-0"
        style={{ width }}
      >
        {/* Tab bar */}
        <div className="flex items-center gap-1 px-2 py-2 border-b border-border">
          {TABS.map((t) => {
            const Icon = t.icon;
            const active = tab === t.id;
            return (
              <Button
                key={t.id}
                variant={active ? "secondary" : "ghost"}
                size="sm"
                className="h-7 gap-1 text-xs flex-1 px-1"
                onClick={() => setTab(t.id)}
              >
                <Icon className="w-3 h-3" />
                <span className="hidden lg:inline">{t.label}</span>
              </Button>
            );
          })}
        </div>

        {/* Tab content */}
        <div className="flex-1 overflow-hidden">
          {tab === "history" && <HistoryTab />}
          {tab === "fillers" && <FillersTab />}
          {tab === "censor" && <CensorTab />}
          {tab === "ai" && <AiTab />}
        </div>
      </div>

      <button
        onClick={() => setCollapsed(true)}
        className="w-6 border-l border-border bg-card hover:bg-accent flex items-center justify-center shrink-0 transition-colors"
        title="Collapse panel"
        aria-label="Collapse side panel"
      >
        <PanelRightClose className="w-3 h-3" />
      </button>
    </>
  );
}
