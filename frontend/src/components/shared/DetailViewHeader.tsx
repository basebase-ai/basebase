/**
 * Shared header for full-screen app and document (artifact) detail views.
 * Back button, title, optional subtitle, optional center slot, three-dot menu.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";

export type DetailViewMenuContent =
  | ReactNode
  | ((closeMenu: () => void) => ReactNode);

export interface DetailViewHeaderProps {
  onBack: () => void;
  /** Shown on back button hover / screen readers */
  backButtonLabel: string;
  title: string;
  subtitle?: string | null;
  /** e.g. search match navigator */
  centerSlot?: ReactNode;
  /** Dropdown body; use the `closeMenu` callback from the function form to dismiss after actions */
  menuContent: DetailViewMenuContent;
}

export function DetailViewHeader({
  onBack,
  backButtonLabel,
  title,
  subtitle,
  centerSlot,
  menuContent,
}: DetailViewHeaderProps): JSX.Element {
  const [menuOpen, setMenuOpen] = useState<boolean>(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const onClickOutside = (e: MouseEvent): void => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [menuOpen]);

  return (
    <div className="flex items-center gap-3 px-4 py-3 border-b border-surface-700 bg-surface-900 flex-shrink-0">
      <button
        type="button"
        onClick={onBack}
        className="text-surface-400 hover:text-surface-200 transition-colors shrink-0"
        title={backButtonLabel}
        aria-label={backButtonLabel}
      >
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
        </svg>
      </button>
      <div className="min-w-0 flex-1">
        <h1 className="text-base font-semibold text-surface-100 truncate">{title}</h1>
        {subtitle ? (
          <p className="text-xs text-surface-400 mt-0.5 truncate max-w-md">{subtitle}</p>
        ) : null}
      </div>
      {centerSlot ? <div className="shrink-0 flex items-center">{centerSlot}</div> : null}
      <div ref={menuRef} className="relative shrink-0">
        <button
          type="button"
          onClick={() => setMenuOpen((p) => !p)}
          className="flex items-center justify-center w-8 h-8 rounded-md hover:bg-surface-700 text-surface-400 hover:text-surface-200 transition-colors"
          title="Options"
          aria-expanded={menuOpen}
          aria-haspopup="true"
        >
          <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
            <circle cx="10" cy="4" r="1.5" />
            <circle cx="10" cy="10" r="1.5" />
            <circle cx="10" cy="16" r="1.5" />
          </svg>
        </button>
        {menuOpen ? (
          <div className="absolute right-0 top-full mt-1 w-56 rounded-lg bg-surface-800 border border-surface-600 shadow-xl z-50 py-1 text-xs">
            {typeof menuContent === "function"
              ? menuContent(() => setMenuOpen(false))
              : menuContent}
          </div>
        ) : null}
      </div>
    </div>
  );
}
