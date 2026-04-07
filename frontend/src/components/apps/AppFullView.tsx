/**
 * Full-screen app view at /apps/:id.
 *
 * Shows the Sandpack-rendered app with a header bar containing:
 * - App title
 * - "Copy link" button
 * - "Embed" button (generates tokenized embed URL)
 * - Back to gallery button
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { SandpackAppRenderer } from "./SandpackAppRenderer";
import { apiRequest } from "../../lib/api";
import { useAppStore } from "../../store";
import type { VisibilityLevel } from "../VisibilitySelector";

interface AppDetail {
  id: string;
  title: string | null;
  description: string | null;
  frontend_code: string;
  frontend_code_compiled?: string | null;
  query_names: string[];
  conversation_id: string | null;
  created_at: string | null;
  user_id: string;
  widget_config?: Record<string, unknown> | null;
  visibility: string;
}

interface EmbedTokenData {
  embed_url: string;
  token: string;
  expires_at: string;
}

interface AppFullViewProps {
  appId: string;
}

export function AppFullView({ appId }: AppFullViewProps): JSX.Element {
  const [app, setApp] = useState<AppDetail | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [linkCopied, setLinkCopied] = useState<boolean>(false);
  const [embedUrl, setEmbedUrl] = useState<string | null>(null);
  const [embedCopied, setEmbedCopied] = useState<boolean>(false);
  const [previewMode, setPreviewMode] = useState<string>("auto");
  const [detailLevel, setDetailLevel] = useState<string>("standard");
  const [visBusy, setVisBusy] = useState<boolean>(false);
  const [menuOpen, setMenuOpen] = useState<boolean>(false);
  const menuRef = useRef<HTMLDivElement>(null);

  const setCurrentView = useAppStore((s) => s.setCurrentView);
  const user = useAppStore((s) => s.user);

  const fetchApp = useCallback(async (): Promise<void> => {
    setLoading(true);
    const resp = await apiRequest<AppDetail>(`/apps/${appId}`);
    if (resp.error || !resp.data) {
      setError(resp.error ?? "Failed to load app");
    } else {
      setApp({
        ...resp.data,
        visibility: resp.data.visibility ?? "team",
      });
    }
    setLoading(false);
  }, [appId]);

  useEffect(() => {
    void fetchApp();
  }, [fetchApp]);

  // Sync preview mode / detail level from widget_config when app loads
  useEffect(() => {
    if (app?.widget_config) {
      if (app.widget_config.preferred_mode) setPreviewMode(app.widget_config.preferred_mode as string);
      if (app.widget_config.detail_level) setDetailLevel(app.widget_config.detail_level as string);
    }
  }, [app?.widget_config]);

  const handlePreviewSettingsChange = async (
    newMode?: string,
    newDetail?: string,
  ): Promise<void> => {
    const payload: Record<string, string> = {};
    if (newMode !== undefined) payload.preferred_mode = newMode === "auto" ? "" : newMode;
    if (newDetail !== undefined) payload.detail_level = newDetail;

    // Optimistic update
    if (newMode !== undefined) setPreviewMode(newMode);
    if (newDetail !== undefined) setDetailLevel(newDetail);

    await apiRequest(`/apps/${appId}/preview-settings`, {
      method: "PATCH",
      body: JSON.stringify(
        Object.fromEntries(
          Object.entries(payload).filter(([, v]) => v !== ""),
        ),
      ),
    });
  };

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

  const organization = useAppStore((s) => s.organization);
  const organizations = useAppStore((s) => s.organizations);
  const orgHandle: string | null =
    organization?.handle ??
    (organization?.id ? organizations.find((o) => o.id === organization.id)?.handle ?? null : null) ??
    null;
  const prefix: string = orgHandle ? `/${orgHandle}` : "";

  const isOwner: boolean =
    Boolean(user?.id) && Boolean(app?.user_id) && user?.id === app?.user_id;

  const handleCopyLink = async (): Promise<void> => {
    const isPublic: boolean = app?.visibility === "public";
    const url: string = isPublic
      ? `${window.location.origin}/public/apps/${appId}`
      : `${window.location.origin}${prefix}/apps/${appId}`;
    await navigator.clipboard.writeText(url);
    setLinkCopied(true);
    setTimeout(() => setLinkCopied(false), 2000);
  };

  const handleVisibilityChange = async (next: VisibilityLevel): Promise<void> => {
    if (next === "public") {
      const ok: boolean = window.confirm(
        "Anyone on the internet can view this app without signing in. Continue?",
      );
      if (!ok) return;
    }
    if (app) setApp({ ...app, visibility: next });
    setVisBusy(true);
    const resp = await apiRequest<{ visibility: string }>(`/apps/${appId}/visibility`, {
      method: "PATCH",
      body: JSON.stringify({ visibility: next }),
    });
    setVisBusy(false);
    if (resp.error && app) {
      setApp({ ...app, visibility: app.visibility });
    }
  };

  const handleEmbed = async (): Promise<void> => {
    if (embedUrl) {
      await navigator.clipboard.writeText(
        `<iframe src="${embedUrl}" width="100%" height="600" frameborder="0"></iframe>`
      );
      setEmbedCopied(true);
      setTimeout(() => setEmbedCopied(false), 2000);
      return;
    }

    const resp = await apiRequest<EmbedTokenData>(`/apps/${appId}/embed-token`, {
      method: "POST",
    });
    if (resp.data) {
      setEmbedUrl(resp.data.embed_url);
      const snippet: string = `<iframe src="${resp.data.embed_url}" width="100%" height="600" frameborder="0"></iframe>`;
      await navigator.clipboard.writeText(snippet);
      setEmbedCopied(true);
      setTimeout(() => setEmbedCopied(false), 2000);
    }
  };

  const goBack = (): void => {
    setCurrentView("apps" as never);
    window.history.pushState(null, "", `${prefix}/apps`);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin w-8 h-8 border-2 border-surface-500 border-t-primary-500 rounded-full" />
      </div>
    );
  }

  if (error || !app) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="p-4 rounded-lg bg-red-900/20 border border-red-700 text-red-300 text-sm max-w-md text-center">
          {error ?? "App not found"}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header bar – single row */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-surface-700 bg-surface-900 flex-shrink-0">
        <button
          onClick={goBack}
          className="text-surface-400 hover:text-surface-200 transition-colors shrink-0"
          title="Back to Apps"
        >
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
        </button>
        <div className="min-w-0 flex-1">
          <h1 className="text-base font-semibold text-surface-100 truncate">
            {app.title ?? "Untitled App"}
          </h1>
          {app.description && (
            <p className="text-xs text-surface-400 mt-0.5 truncate max-w-md">
              {app.description}
            </p>
          )}
        </div>

        {/* Three-dot menu */}
        <div ref={menuRef} className="relative shrink-0">
          <button
            onClick={() => setMenuOpen((p) => !p)}
            className="flex items-center justify-center w-8 h-8 rounded-md hover:bg-surface-700 text-surface-400 hover:text-surface-200 transition-colors"
            title="Options"
          >
            <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
              <circle cx="10" cy="4" r="1.5" />
              <circle cx="10" cy="10" r="1.5" />
              <circle cx="10" cy="16" r="1.5" />
            </svg>
          </button>

          {menuOpen && (
            <div className="absolute right-0 top-full mt-1 w-56 rounded-lg bg-surface-800 border border-surface-600 shadow-xl z-50 py-1 text-xs">
              {/* Visibility */}
              {isOwner && (
                <>
                  <div className="px-3 py-1.5 text-[10px] font-semibold text-surface-500 uppercase tracking-wider">
                    Visibility
                  </div>
                  {(["private", "team", "public"] as const).map((lvl) => {
                    const label: string =
                      lvl === "private" ? "Only me" : lvl === "team" ? "Team" : "Public";
                    const active: boolean = (app.visibility as VisibilityLevel) === lvl;
                    return (
                      <button
                        key={lvl}
                        type="button"
                        disabled={visBusy}
                        onClick={() => void handleVisibilityChange(lvl)}
                        className={`w-full text-left px-3 py-1.5 flex items-center gap-2 transition-colors ${
                          active
                            ? "text-primary-400"
                            : "text-surface-300 hover:bg-surface-700"
                        } disabled:opacity-50`}
                      >
                        <span className="w-4 text-center">
                          {active ? "✓" : ""}
                        </span>
                        {label}
                      </button>
                    );
                  })}
                  <div className="my-1 border-t border-surface-700" />
                </>
              )}

              {/* Preview mode */}
              <div className="px-3 py-1.5 text-[10px] font-semibold text-surface-500 uppercase tracking-wider">
                Preview
              </div>
              {([
                ["auto", "Auto"],
                ["screenshot", "Screenshot"],
                ["widget", "Widget"],
                ["mini_app", "Mini App"],
                ["icon", "Icon"],
              ] as const).map(([val, label]) => (
                <button
                  key={val}
                  type="button"
                  onClick={() => void handlePreviewSettingsChange(val, undefined)}
                  className={`w-full text-left px-3 py-1.5 flex items-center gap-2 transition-colors ${
                    previewMode === val
                      ? "text-primary-400"
                      : "text-surface-300 hover:bg-surface-700"
                  }`}
                >
                  <span className="w-4 text-center">
                    {previewMode === val ? "✓" : ""}
                  </span>
                  {label}
                </button>
              ))}

              {previewMode === "widget" && (
                <>
                  <div className="my-1 border-t border-surface-700" />
                  <div className="px-3 py-1.5 text-[10px] font-semibold text-surface-500 uppercase tracking-wider">
                    Detail level
                  </div>
                  {([
                    ["minimal", "Minimal"],
                    ["standard", "Standard"],
                    ["detailed", "Detailed"],
                  ] as const).map(([val, label]) => (
                    <button
                      key={val}
                      type="button"
                      onClick={() => void handlePreviewSettingsChange(undefined, val)}
                      className={`w-full text-left px-3 py-1.5 flex items-center gap-2 transition-colors ${
                        detailLevel === val
                          ? "text-primary-400"
                          : "text-surface-300 hover:bg-surface-700"
                      }`}
                    >
                      <span className="w-4 text-center">
                        {detailLevel === val ? "✓" : ""}
                      </span>
                      {label}
                    </button>
                  ))}
                </>
              )}

              <div className="my-1 border-t border-surface-700" />

              {/* Actions */}
              <button
                type="button"
                onClick={() => { void handleCopyLink(); setMenuOpen(false); }}
                className="w-full text-left px-3 py-1.5 text-surface-300 hover:bg-surface-700 transition-colors flex items-center gap-2"
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                </svg>
                {linkCopied
                  ? (app.visibility === "public" ? "Public link copied!" : "Link copied!")
                  : "Copy link"}
              </button>
              <button
                type="button"
                onClick={() => { void handleEmbed(); setMenuOpen(false); }}
                className="w-full text-left px-3 py-1.5 text-surface-300 hover:bg-surface-700 transition-colors flex items-center gap-2"
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
                </svg>
                {embedCopied ? "Embed code copied!" : "Copy embed code"}
              </button>
            </div>
          )}
        </div>
      </div>

      {/* App renderer */}
      <div className="flex-1 overflow-hidden">
        <SandpackAppRenderer
          appId={appId}
        />
      </div>
    </div>
  );
}
