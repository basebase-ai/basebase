/**
 * Renders a Basebase App inside a sandboxed srcdoc iframe.
 *
 * Replaces the Sandpack-based approach with a simpler, more reliable method:
 * 1. React + ReactDOM + Plotly loaded from CDN as UMD globals
 * 2. Babel standalone transpiles JSX in-browser
 * 3. SDK + Plot shim inlined (no module bundler needed)
 * 4. Basebase's code has imports stripped (everything is already in scope)
 *
 * The iframe uses a restrictive sandbox while allowing popups so app links
 * with target="_blank" / window.open() can open in a new tab.
 */

import { useEffect, useState, useCallback, useRef } from "react";
import html2canvas from "html2canvas";
import { APP_SDK_SOURCE, APP_STYLES, REACT_PLOTLY_SHIM } from "./appSdkSource";
import { apiRequest, API_BASE } from "../../lib/api";

// ---- types ----------------------------------------------------------------

interface AppTokenData {
  token: string;
  expires_at: string;
  app_id: string;
  api_base: string;
}

interface AppApiData {
  frontend_code: string;
  frontend_code_compiled?: string | null;
}
interface ExternalNavigationPrompt {
  href: string;
  target?: "_blank" | "_top";
}

interface SandpackAppRendererProps {
  appId: string;
  /** Initial code used until the API fetch completes. */
  frontendCode?: string;
  frontendCodeCompiled?: string | null;
  embedToken?: string;
  /** Use unauthenticated /api/public/apps/:id and query routes (no Bearer token). */
  publicMode?: boolean;
  onError?: (message: string) => void;
  /** If true, skip screenshot capture (screenshot already exists). */
  hasScreenshot?: boolean;
}

// ---- helpers --------------------------------------------------------------

/** Strip import/export statements so code can live in a shared Babel block. */
function stripModuleSyntax(code: string): string {
  return code
    // Remove import lines
    .replace(/^\s*import\s+.*?from\s+['"].*?['"];?\s*$/gm, "")
    // export function Foo → function Foo
    .replace(/export\s+function\s+/g, "function ")
    // export default function Foo → function Foo
    .replace(/export\s+default\s+function\s+/g, "function ")
    // export default <identifier>;
    .replace(/export\s+default\s+/g, "")
    // export { ... }
    .replace(/export\s+\{[^}]*\};?/g, "");
}

/**
 * Transform Basebase's code for the srcdoc environment:
 * - Strip imports (everything is in global scope)
 * - Capture the default-exported component name
 */
function transformAppCode(code: string): { transformed: string; appName: string } {
  let appName = "App";

  // Capture name from `export default function Foo`
  const namedMatch = code.match(/export\s+default\s+function\s+(\w+)/);
  if (namedMatch?.[1]) {
    appName = namedMatch[1];
  } else {
    // Capture name from standalone `export default Foo`
    const defaultMatch = code.match(/export\s+default\s+(\w+)\s*;?/);
    if (defaultMatch?.[1]) {
      appName = defaultMatch[1];
    }
  }

  const transformed: string = code
    // Remove all import lines
    .replace(/^\s*import\s+.*?from\s+['"].*?['"];?\s*$/gm, "")
    // export default function Foo → function Foo
    .replace(/export\s+default\s+function\s+(\w+)/, "function $1")
    // export default Foo; → (remove)
    .replace(/export\s+default\s+\w+\s*;?/, "");

  return { transformed, appName };
}

/** Closing tag as a constant so the bundler/linter never sees a raw close-script. */
const CS = "<" + "/script>";

/** Escape a string for safe embedding inside an HTML <script> block. */
function escapeForScript(s: string): string {
  return s.replace(new RegExp(CS, "gi"), "<\\/script>");
}

const BASEBASE_HOST = "basebase.com";

function normalizeHttpNavigationHref(href: string): string | null {
  try {
    const parsed = new URL(href, window.location.href);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : null;
  } catch {
    return null;
  }
}

// ---- build the srcdoc HTML ------------------------------------------------

function buildSrcdocHtml(opts: {
  frontendCode: string;
  frontendCodeCompiled?: string | null;
  token: string;
  apiBase: string;
  appId: string;
  publicMode: boolean;
}): string {
  const sdkInline: string = stripModuleSyntax(APP_SDK_SOURCE);
  const plotInline: string = stripModuleSyntax(REACT_PLOTLY_SHIM);
  const { transformed, appName } = transformAppCode(opts.frontendCode);
  const useCompiled: boolean = typeof opts.frontendCodeCompiled === "string" && opts.frontendCodeCompiled.length > 0;

  // When compiled code is available, skip Babel Standalone entirely
  const babelScript: string = useCompiled
    ? ""
    : `<script src="https://unpkg.com/@babel/standalone@7/babel.min.js">${CS}`;
  const scriptType: string = useCompiled ? "text/javascript" : "text/babel";
  const appCode: string = useCompiled ? opts.frontendCodeCompiled as string : transformed;

  return `<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8" />
<script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js">${CS}
<script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js">${CS}
<script src="https://cdn.plot.ly/plotly-2.35.3.min.js">${CS}
${babelScript}
<style>${escapeForScript(APP_STYLES)}</style>
</head>
<body>
<div id="root"></div>

<script>
// Globals for the SDK
window.__REVTOPS_APP_TOKEN__ = ${JSON.stringify(opts.token)};
window.__REVTOPS_API_BASE__  = ${JSON.stringify(opts.apiBase)};
window.__REVTOPS_APP_ID__    = ${JSON.stringify(opts.appId)};
window.__REVTOPS_PUBLIC_MODE__ = ${opts.publicMode ? "true" : "false"};

// Harden popup behavior for untrusted app code:
// - block javascript:/data: URLs
// - always open with noopener,noreferrer
// - sever opener references when possible
(function(){
  const SAFE_SPECIAL_SCHEMES = /^(mailto:|tel:)/i;
  const BASEBASE_HOST = ${JSON.stringify(BASEBASE_HOST)};
  function isSingleSlashPath(url) {
    return url.startsWith("/") && !url.startsWith("//");
  }
  function isBasebaseHost(hostname) {
    return hostname === BASEBASE_HOST || hostname.endsWith("." + BASEBASE_HOST);
  }
  function parseHttpUrl(raw) {
    try {
      const parsed = new URL(raw, window.location.href);
      return /^https?:$/i.test(parsed.protocol) ? parsed : null;
    } catch(_) {
      return null;
    }
  }
  function shouldConfirmTopNavigation(raw) {
    const parsed = parseHttpUrl(raw);
    return !!parsed && parsed.origin !== window.location.origin && !isBasebaseHost(parsed.hostname);
  }
  function isSafeUrl(raw) {
    if (typeof raw !== "string") return false;
    const url = raw.trim();
    if (!url) return false;
    if (url.startsWith("#") || isSingleSlashPath(url) || SAFE_SPECIAL_SCHEMES.test(url)) return true;
    return parseHttpUrl(url) !== null;
  }
  function isLikelyExternalUrl(raw) {
    if (typeof raw !== "string") return false;
    const url = raw.trim();
    if (!url || url.startsWith("#") || isSingleSlashPath(url)) return false;
    const parsed = parseHttpUrl(url);
    return parsed ? parsed.origin !== window.location.origin : /^https?:/i.test(url);
  }
  function sanitizeFeatures(features) {
    const base = (typeof features === "string" && features.trim()) ? features + "," : "";
    return base + "noopener,noreferrer";
  }
  const originalOpen = window.open ? window.open.bind(window) : null;
  let pendingExternalHref = null;
  let pendingExternalTarget = "_blank";
  function postExternalNavigationRequest(href, target) {
    pendingExternalHref = href;
    pendingExternalTarget = target;
    try { window.parent.postMessage({ type:"external-link-navigation", href: href, target: target }, "*"); } catch(_) {}
  }
  function navigateTop(url) {
    const href = typeof url === "string" ? url.trim() : String(url ?? "").trim();
    if (!isSafeUrl(href)) return false;
    if (shouldConfirmTopNavigation(href)) {
      const parsed = parseHttpUrl(href);
      postExternalNavigationRequest(parsed ? parsed.href : href, "_top");
      return true;
    }
    window.top.location.href = href;
    return true;
  }
  const topLocationProxy = new Proxy({}, {
    get: function(_target, prop) {
      if (prop === "assign" || prop === "replace") {
        return function(url) { navigateTop(url); };
      }
      return window.top.location[prop];
    },
    set: function(_target, prop, value) {
      if (prop === "href") return navigateTop(value);
      window.top.location[prop] = value;
      return true;
    },
  });
  const guardedTopWindow = new Proxy({}, {
    get: function(_target, prop) {
      if (prop === "location") return topLocationProxy;
      if (prop === "top" || prop === "parent" || prop === "self" || prop === "window") return guardedTopWindow;
      const value = window.top[prop];
      return typeof value === "function" ? value.bind(window.top) : value;
    },
    set: function(_target, prop, value) {
      if (prop === "location") return navigateTop(value);
      window.top[prop] = value;
      return true;
    },
  });
  const guardedWindow = new Proxy({}, {
    get: function(_target, prop) {
      if (prop === "top" || prop === "parent") return guardedTopWindow;
      const value = window[prop];
      return typeof value === "function" ? value.bind(window) : value;
    },
    set: function(_target, prop, value) {
      if (prop === "top" || prop === "parent") return true;
      window[prop] = value;
      return true;
    },
  });
  window.__BASEBASE_APP_GUARDED_WINDOW__ = guardedWindow;
  if (originalOpen) {
    window.open = function(url, target, features) {
      if (!isSafeUrl(typeof url === "string" ? url : String(url ?? ""))) {
        return null;
      }
      const opened = originalOpen(url, target || "_blank", sanitizeFeatures(features));
      try { if (opened) { opened.opener = null; } } catch(_) {}
      return opened;
    };
  }
  window.addEventListener("message", function(ev) {
    const data = ev && ev.data ? ev.data : null;
    if (!data || data.type !== "external-link-navigation-decision") return;
    if (!pendingExternalHref || typeof data.href !== "string" || data.href !== pendingExternalHref) return;
    if (data.allow === true) {
      originalOpen(pendingExternalHref, pendingExternalTarget, sanitizeFeatures(""));
    }
    pendingExternalHref = null;
    pendingExternalTarget = "_blank";
  });
  document.addEventListener("click", function(ev){
    const t = ev.target;
    if (!(t instanceof Element)) return;
    const a = t.closest("a[href]");
    if (!(a instanceof HTMLAnchorElement)) return;
    const href = a.getAttribute("href") || "";
    if (!isSafeUrl(href)) {
      ev.preventDefault();
      return;
    }
    a.setAttribute("rel", "noopener noreferrer");
    if (!a.getAttribute("target")) a.setAttribute("target", "_blank");
    if (isLikelyExternalUrl(href)) {
      ev.preventDefault();
      postExternalNavigationRequest(href, a.getAttribute("target") || "_blank");
    }
  }, true);
})();

// Global error handler → show in UI + notify parent
window.onerror = function(msg, url, line, col, err) {
  var el = document.getElementById('root');
  if (el) {
    el.innerHTML = '<div style="color:#fca5a5;padding:1rem;font-family:monospace;font-size:12px;white-space:pre-wrap;">'
      + (err ? err.stack || err.message : msg) + '<' + '/div>';
  }
  try { window.parent.postMessage({ type:"app-error", error: String(msg) }, "*"); } catch(_){}
};
${CS}

<script type="${scriptType}">
/* ---- Guard common top-window navigation APIs used by app code ---- */
const __basebaseWindow = globalThis.__BASEBASE_APP_GUARDED_WINDOW__ || globalThis;
(function(window, self, top, parent) {
/* ---- React destructured ---- */
const { useState, useEffect, useCallback, useRef, useMemo, useReducer, useContext, createContext, Fragment } = React;

/* ---- SDK (inlined) ---- */
${escapeForScript(sdkInline)}

/* ---- Plot shim (inlined) ---- */
${escapeForScript(plotInline)}

/* ---- App code ---- */
${escapeForScript(appCode)}

/* ---- Boot ---- */
try {
  const _root = ReactDOM.createRoot(document.getElementById("root"));
  _root.render(React.createElement(typeof ${appName} !== "undefined" ? ${appName} : function() {
    return React.createElement("div", { style: { color: "#fca5a5", padding: "1rem" } }, "No component found");
  }));
} catch(e) {
  document.getElementById("root").innerHTML =
    '<div style="color:#fca5a5;padding:1rem;font-family:monospace;font-size:12px;white-space:pre-wrap;">' + e.message + '<' + '/div>';
  try { window.parent.postMessage({ type:"app-error", error: e.message }, "*"); } catch(_){}
}
})(__basebaseWindow, __basebaseWindow, __basebaseWindow.top, __basebaseWindow.parent);
${CS}
</body>
</html>`;
}

// ---- component ------------------------------------------------------------

export function SandpackAppRenderer({
  appId,
  frontendCode: initialCode,
  frontendCodeCompiled: initialCompiled,
  embedToken,
  publicMode = false,
  onError,
  hasScreenshot,
}: SandpackAppRendererProps): JSX.Element {
  const [tokenData, setTokenData] = useState<AppTokenData | null>(null);
  const [appCode, setAppCode] = useState<string | null>(initialCode ?? null);
  const [appCodeCompiled, setAppCodeCompiled] = useState<string | null | undefined>(initialCompiled);
  const [error, setError] = useState<string | null>(null);
  const [externalNavPrompt, setExternalNavPrompt] = useState<ExternalNavigationPrompt | null>(null);
  const [tokenRetry, setTokenRetry] = useState<number>(0);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const retryingRef = useRef<boolean>(false);
  const screenshotCapturedRef = useRef<boolean>(false);

  // Fetch latest app code from DB — always prefer this over the prop snapshot
  useEffect(() => {
    if (embedToken || publicMode) return; // embed / public pages fetch their own data
    let cancelled = false;
    (async () => {
      const resp = await apiRequest<AppApiData>(`/apps/${appId}`);
      if (cancelled) return;
      if (resp.data) {
        setAppCode(resp.data.frontend_code);
        setAppCodeCompiled(resp.data.frontend_code_compiled);
      }
    })();
    return () => { cancelled = true; };
  }, [appId, embedToken, publicMode]);

  // Public app: load code from unauthenticated API
  useEffect(() => {
    if (!publicMode) return;
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetch(`${API_BASE}/public/apps/${appId}`);
        if (!res.ok) {
          setError("This app is not public or could not be loaded.");
          return;
        }
        const data = (await res.json()) as {
          frontend_code: string;
          frontend_code_compiled?: string | null;
        };
        if (cancelled) return;
        setAppCode(data.frontend_code);
        setAppCodeCompiled(data.frontend_code_compiled);
      } catch {
        if (!cancelled) setError("Failed to load public app");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [appId, publicMode]);

  // Listen for error / token-expired messages from the iframe
  useEffect(() => {
    const handler = (event: MessageEvent): void => {
      const expectedSource = iframeRef.current?.contentWindow ?? null;
      const expectedOrigin = window.location.origin;
      const maybeData = event.data as { type?: string; requestId?: string; appId?: string; workflowId?: string } | null;
      if (event.source !== expectedSource || event.origin !== expectedOrigin) {
        if (maybeData?.type?.startsWith("app-")) {
          console.warn("[Apps iframe bridge] Ignored app message from unexpected source or origin", {
            type: maybeData.type,
            requestId: maybeData.requestId,
            appId: maybeData.appId,
            workflowId: maybeData.workflowId,
            actualOrigin: event.origin,
            expectedOrigin,
            sourceMatches: event.source === expectedSource,
          });
        }
        return;
      }

      const data = event.data as {
        type?: string;
        error?: string;
        href?: string;
        requestExternalId?: string;
        requestId?: string;
        target?: string;
        appId?: string;
        workflowId?: string;
        triggerData?: Record<string, unknown>;
      } | null;
      if (data?.type === "external-link-navigation") {
        const href: string = typeof data.href === "string" && data.href.length > 0 ? data.href : "";
        const normalizedHref = href ? normalizeHttpNavigationHref(href) : null;
        if (normalizedHref) {
          setExternalNavPrompt({ href: normalizedHref, target: data.target === "_top" ? "_top" : "_blank" });
        }
        return;
      }
      if (data?.type === "app-error" && data.error && onError) {
        onError(data.error);
      }
      if (data?.type === "app-token-expired" && !retryingRef.current) {
        retryingRef.current = true;
        try { sessionStorage.removeItem(`app_token_${appId}`); } catch { /* ignore */ }
        setTokenData(null);
        setTokenRetry((n: number) => n + 1);
      }
      if (data?.type === "app-trigger-workflow") {
        const requestId = data.requestId;
        const workflowId = data.workflowId;
        const payloadAppId = data.appId;
        const payloadAppIdMatchesCurrentApp = (() => {
          if (!payloadAppId) return false;
          try {
            return payloadAppId.toLowerCase() === appId.toLowerCase();
          } catch {
            return false;
          }
        })();
        if (data.transport !== "sdk.triggerWorkflow") {
          console.warn("[Apps iframe bridge] Workflow trigger should use first-class SDK helper triggerWorkflow() instead of a hand-rolled postMessage", {
            appId: payloadAppId,
            workflowId,
            requestId,
            transport: data.transport,
          });
        }

        if (!requestId || !workflowId || !payloadAppIdMatchesCurrentApp) {
          console.warn("[Apps iframe bridge] Invalid workflow trigger payload", {
            requestId,
            workflowId,
            payloadAppId,
            expectedAppId: appId,
          });
          (event.source as Window | null)?.postMessage({
            type: "app-trigger-workflow-result",
            requestId,
            ok: false,
            error: "Invalid workflow trigger payload",
          }, "*");
          return;
        }

        void (async () => {
          try {
            const triggerDataKeys = data.triggerData && typeof data.triggerData === "object"
              ? Object.keys(data.triggerData).sort()
              : [];
            console.warn("[Apps iframe bridge] Trigger workflow request", {
              appId: payloadAppId,
              workflowId,
              requestId,
              triggerDataKeys,
            });
            const response = await apiRequest<{
              status: string;
              task_id: string;
              workflow_id: string;
              run_id: string;
              triggered_by_user_id: string;
              request_id?: string | null;
            }>(`/apps/${payloadAppId}/workflows/${workflowId}/trigger`, {
              method: "POST",
              body: JSON.stringify({
                trigger_data: data.triggerData && typeof data.triggerData === "object" ? data.triggerData : undefined,
                request_id: requestId,
              }),
            });
            if (response.error || !response.data) {
              console.warn("[Apps iframe bridge] Workflow trigger API rejected request", {
                appId: payloadAppId,
                workflowId,
                requestId,
                error: response.error,
              });
              (event.source as Window | null)?.postMessage({
                type: "app-trigger-workflow-result",
                requestId,
                ok: false,
                error: response.error ?? "Failed to queue workflow",
              }, "*");
              return;
            }
            console.warn("[Apps iframe bridge] Workflow trigger queued", {
              appId: payloadAppId,
              workflowId,
              requestId,
              taskId: response.data.task_id,
              runId: response.data.run_id,
            });
            (event.source as Window | null)?.postMessage({
              type: "app-trigger-workflow-result",
              requestId,
              ok: true,
              result: response.data,
            }, "*");
          } catch (err) {
            console.warn("[Apps iframe bridge] Trigger workflow failed", err);
            (event.source as Window | null)?.postMessage({
              type: "app-trigger-workflow-result",
              requestId,
              ok: false,
              error: err instanceof Error ? err.message : "Failed to trigger workflow",
            }, "*");
          }
        })();
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [onError, appId]);

  const fetchToken = useCallback(async (): Promise<void> => {
    if (publicMode) {
      setTokenData({
        token: "",
        expires_at: "",
        app_id: appId,
        api_base: API_BASE,
      });
      return;
    }
    if (embedToken) {
      setTokenData({
        token: embedToken,
        expires_at: "",
        app_id: appId,
        api_base: API_BASE,
      });
      return;
    }

    // Check sessionStorage cache first
    const cacheKey = `app_token_${appId}`;
    try {
      const cached = sessionStorage.getItem(cacheKey);
      if (cached) {
        const parsed = JSON.parse(cached) as AppTokenData & { _cachedAt: number };
        // Reuse if less than 50 minutes old (tokens last 60 min)
        if (Date.now() - parsed._cachedAt < 50 * 60 * 1000) {
          setTokenData(parsed);
          return;
        }
        sessionStorage.removeItem(cacheKey);
      }
    } catch { /* ignore parse errors */ }

    const resp = await apiRequest<AppTokenData>(`/apps/${appId}/token`, {
      method: "POST",
    });

    if (resp.error || !resp.data) {
      setError(resp.error ?? "Failed to get app token");
      return;
    }
    // Cache for reuse
    try {
      sessionStorage.setItem(cacheKey, JSON.stringify({ ...resp.data, _cachedAt: Date.now() }));
    } catch { /* storage full — ignore */ }
    retryingRef.current = false;
    setTokenData(resp.data);
  }, [appId, embedToken, publicMode]);

  useEffect(() => {
    void fetchToken();
  }, [fetchToken, tokenRetry]);

  // Screenshot capture: after iframe loads and data settles, capture via html2canvas
  useEffect(() => {
    if (hasScreenshot || screenshotCapturedRef.current || embedToken || publicMode) return;
    if (!iframeRef.current || !tokenData || !appCode) return;

    // Try capture at 3s, retry at 6s if first attempt skipped (still loading)
    let attempt = 0;
    const tryCapture = (): void => {
      const iframe = iframeRef.current;
      if (!iframe || screenshotCapturedRef.current) return;

      try {
        const iframeDoc = iframe.contentDocument;
        if (!iframeDoc?.body) {
          console.warn("[screenshot] No contentDocument access for", appId);
          return;
        }

        const bodyText = iframeDoc.body.innerText?.trim() ?? '';
        console.log(`[screenshot] attempt=${attempt} bodyLen=${bodyText.length} appId=${appId}`);
        if (bodyText.length < 10 && attempt < 2) {
          attempt++;
          setTimeout(tryCapture, 3000);
          return;
        }

        screenshotCapturedRef.current = true;
        console.log("[screenshot] Capturing with html2canvas...", appId);
        const previewWidth = 1200;
        const previewHeight = 630;
        html2canvas(iframeDoc.body, {
          backgroundColor: "#18181b",
          // Capture at full DOM resolution so gallery previews stay crisp.
          scale: 1,
          logging: false,
          useCORS: true,
          width: previewWidth,
          height: previewHeight,
          windowWidth: previewWidth,
          windowHeight: previewHeight,
        }).then((canvas) => {
          let quality = 0.9;
          let dataUrl = canvas.toDataURL("image/jpeg", quality);
          while (dataUrl.length >= 2_000_000 && quality > 0.55) {
            quality -= 0.1;
            dataUrl = canvas.toDataURL("image/jpeg", quality);
          }

          console.log(
            `[screenshot] Captured! size=${dataUrl.length} quality=${quality.toFixed(2)} ` +
            `dimensions=${canvas.width}x${canvas.height} appId=${appId}`
          );
          if (dataUrl.length < 2_000_000) {
            void apiRequest("/apps/" + appId + "/screenshot", {
              method: "POST",
              body: JSON.stringify({ screenshot: dataUrl }),
            });
          } else {
            console.warn("[screenshot] Too large after quality fallback:", dataUrl.length, "appId=", appId);
          }
        }).catch((err) => {
          console.error("[screenshot] html2canvas failed:", err);
        });
      } catch (err) {
        console.error("[screenshot] Access error:", err);
      }
    };

    const timer = setTimeout(tryCapture, 3000);
    return () => clearTimeout(timer);
  }, [appId, tokenData, appCode, hasScreenshot, embedToken, publicMode]);

  if (error) {
    return (
      <div className="flex items-center justify-center h-full min-h-[200px]">
        <div className="p-4 rounded-lg bg-red-900/20 border border-red-700 text-red-300 text-sm max-w-md text-center">
          {error}
        </div>
      </div>
    );
  }

  if (!tokenData || !appCode) {
    return (
      <div className="flex items-center justify-center h-full min-h-[200px]">
        <div className="animate-spin w-6 h-6 border-2 border-surface-500 border-t-primary-500 rounded-full" />
      </div>
    );
  }

  const resolvedApiBase: string =
    tokenData.api_base.startsWith("/")
      ? `${window.location.origin}${tokenData.api_base}`
      : tokenData.api_base;

  const srcdoc: string = buildSrcdocHtml({
    frontendCode: appCode,
    frontendCodeCompiled: appCodeCompiled,
    token: tokenData.token,
    apiBase: resolvedApiBase,
    appId,
    publicMode,
  });

  return (
    <div className="w-full h-full min-h-[400px] relative">
      {externalNavPrompt ? (
        <div className="absolute top-2 left-2 right-2 z-20 rounded-md border border-amber-500/40 bg-zinc-900/95 px-3 py-3 text-xs text-amber-100 shadow-lg">
          <p className="mb-2">You are leaving Basebase and opening an external link:</p>
          <p className="mb-3 break-all text-amber-200">{externalNavPrompt.href}</p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="rounded bg-amber-500 px-2 py-1 text-[11px] font-medium text-black hover:bg-amber-400"
              onClick={() => {
                if (externalNavPrompt.target === "_top") {
                  setExternalNavPrompt(null);
                  window.location.assign(externalNavPrompt.href);
                  return;
                }
                const expectedSource = iframeRef.current?.contentWindow ?? null;
                expectedSource?.postMessage(
                  {
                    type: "external-link-navigation-decision",
                    href: externalNavPrompt.href,
                    allow: true,
                  },
                  "*",
                );
                setExternalNavPrompt(null);
              }}
            >
              Open link
            </button>
            <button
              type="button"
              className="rounded border border-zinc-600 px-2 py-1 text-[11px] text-zinc-200 hover:bg-zinc-800"
              onClick={() => {
                const expectedSource = iframeRef.current?.contentWindow ?? null;
                expectedSource?.postMessage(
                  {
                    type: "external-link-navigation-decision",
                    href: externalNavPrompt.href,
                    allow: false,
                  },
                  "*",
                );
                setExternalNavPrompt(null);
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}
      <iframe
        ref={iframeRef}
        srcDoc={srcdoc}
        sandbox="allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox"
        style={{
          width: "100%",
          height: "100%",
          minHeight: 400,
          border: "none",
          borderRadius: 8,
          background: "#18181b",
        }}
        title="Basebase App"
      />
    </div>
  );
}
