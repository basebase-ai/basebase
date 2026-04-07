import { useState, useCallback } from "react";

export type ViewMode = "grid" | "list";

const STORAGE_KEY = "gallery-view-mode";

function readStored(): ViewMode {
  try {
    const raw: string | null = localStorage.getItem(STORAGE_KEY);
    if (raw === "grid" || raw === "list") return raw;
  } catch {
    /* SSR / private-browsing – fall through */
  }
  return "grid";
}

/**
 * Persists grid/list preference to localStorage so the choice
 * is shared across Apps, Documents, and Workflows galleries.
 */
export function useViewMode(): [ViewMode, (next: ViewMode) => void] {
  const [mode, setModeState] = useState<ViewMode>(readStored);

  const setMode = useCallback((next: ViewMode): void => {
    setModeState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* quota / private-browsing */
    }
  }, []);

  return [mode, setMode];
}
