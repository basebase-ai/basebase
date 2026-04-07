/**
 * Segmented control for artifact/app visibility (private / team / public).
 */

export type VisibilityLevel = "private" | "team" | "public";

const LEVELS: readonly { id: VisibilityLevel; short: string }[] = [
  { id: "private", short: "Only me" },
  { id: "team", short: "Team" },
  { id: "public", short: "Public" },
] as const;

interface VisibilitySelectorProps {
  value: VisibilityLevel;
  onChange: (next: VisibilityLevel) => void;
  disabled?: boolean;
  busy?: boolean;
}

const BADGE_CLASS: Record<VisibilityLevel, string> = {
  private: "bg-amber-900/50 text-amber-200 border border-amber-700/50",
  team: "bg-surface-700 text-surface-400 border border-surface-600",
  public: "bg-emerald-900/40 text-emerald-200 border border-emerald-700/40",
};

export function VisibilityBadge({
  visibility,
}: {
  visibility: string;
}): JSX.Element {
  const v: VisibilityLevel =
    visibility === "private" || visibility === "public" || visibility === "team"
      ? visibility
      : "team";
  const label: string =
    v === "private" ? "Private" : v === "public" ? "Public" : "Team";
  return (
    <span
      className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${BADGE_CLASS[v]}`}
    >
      {label}
    </span>
  );
}

/** Shared height with header selects / buttons (AppFullView, ArtifactFullView). */
const CONTROL_ROW_CLASS =
  "inline-flex h-8 shrink-0 rounded-md border border-surface-600 overflow-hidden bg-surface-800/80";

export function VisibilitySelector({
  value,
  onChange,
  disabled = false,
  busy = false,
}: VisibilitySelectorProps): JSX.Element {
  return (
    <div
      role="group"
      aria-label="Visibility"
      className="flex items-center gap-2 shrink-0"
    >
      <span className="text-xs text-surface-500 whitespace-nowrap max-sm:hidden">
        Visibility
      </span>
      <div className={CONTROL_ROW_CLASS}>
        {LEVELS.map((lvl) => (
          <button
            key={lvl.id}
            type="button"
            disabled={disabled || busy}
            onClick={() => onChange(lvl.id)}
            className={`px-2.5 text-xs font-medium transition-colors flex items-center justify-center min-w-0 ${
              value === lvl.id
                ? "bg-primary-600 text-white"
                : "text-surface-300 hover:bg-surface-700"
            }`}
          >
            {lvl.short}
          </button>
        ))}
      </div>
    </div>
  );
}
