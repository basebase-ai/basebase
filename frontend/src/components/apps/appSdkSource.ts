/**
 * Source code for the @revtops/app-sdk virtual module injected into Sandpack.
 *
 * This is shipped as a string constant so SandpackAppRenderer can place it
 * at /node_modules/@revtops/app-sdk/index.js inside the sandbox filesystem.
 *
 * Basebase's generated React code imports from "@revtops/app-sdk".
 */

export const APP_SDK_SOURCE: string = `
import { useState, useEffect, useCallback, useRef } from "react";

// ---------------------------------------------------------------------------
// Globals injected by the host (SandpackAppRenderer) via /src/setup.js
// ---------------------------------------------------------------------------
const APP_TOKEN = window.__REVTOPS_APP_TOKEN__ || "";
const API_BASE  = window.__REVTOPS_API_BASE__  || "";
const APP_ID    = window.__REVTOPS_APP_ID__    || "";
const PUBLIC_MODE = window.__REVTOPS_PUBLIC_MODE__ === true;

// ---------------------------------------------------------------------------
// useAppQuery – fetch data from a named server-side query
// ---------------------------------------------------------------------------
const MIN_REFETCH_MS = 5000;

export function useAppQuery(queryName, params, options) {
  const [data, setData]       = useState(null);
  const [columns, setColumns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);
  const abortRef = useRef(null);
  const lastFetchedAt = useRef(0);
  const lastParamKey = useRef("");

  // Stable serialisation of params for the dependency array
  const paramKey = JSON.stringify(params ?? {});

  const refetch = useCallback(async () => {
    // Throttle: skip if same params and last fetch was recent
    const paramsChanged = paramKey !== lastParamKey.current;
    if (!paramsChanged && Date.now() - lastFetchedAt.current < MIN_REFETCH_MS) return;

    // Abort any in-flight request
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError(null);

    try {
      const queryPath = PUBLIC_MODE
        ? "/public/apps/" + APP_ID + "/queries/" + encodeURIComponent(queryName)
        : "/apps/" + APP_ID + "/queries/" + encodeURIComponent(queryName);
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (!PUBLIC_MODE) {
        headers["Authorization"] = "Bearer " + APP_TOKEN;
      }
      const res = await fetch(API_BASE + queryPath, {
        method: "POST",
        headers,
        body: paramKey,
        signal: controller.signal,
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        if (res.status === 401) {
          try { window.parent.postMessage({ type: "app-token-expired" }, "*"); } catch (_) {}
        }
        throw new Error(body.detail || "Query failed (" + res.status + ")");
      }
      const json = await res.json();
      setData(json.data ?? []);
      setColumns(json.columns ?? []);
      lastFetchedAt.current = Date.now();
      lastParamKey.current = paramKey;
    } catch (err) {
      if (err.name !== "AbortError") {
        setError(err instanceof Error ? err : new Error(err.message || "Unknown error"));
      }
    } finally {
      setLoading(false);
    }
  }, [queryName, paramKey]);

  useEffect(() => { refetch(); }, [refetch]);

  // Built-in polling via refetchInterval option
  useEffect(() => {
    if (!options?.refetchInterval) return;
    const id = setInterval(refetch, options.refetchInterval);
    return () => clearInterval(id);
  }, [refetch, options?.refetchInterval]);

  // Cleanup on unmount
  useEffect(() => () => { if (abortRef.current) abortRef.current.abort(); }, []);

  return { data, columns, loading, error, refetch };
}



// ---------------------------------------------------------------------------
// triggerWorkflow – first-class app SDK API to enqueue a workflow run from this app
//
// Usage:
// await triggerWorkflow("<workflow-id>", { foo: "bar" });
//
// Note: Do not hand-roll window.parent.postMessage("app-trigger-workflow").
// This helper is the supported codepath and handles request IDs, status updates,
// validation compatibility, and timeout behavior.
//
// Optional status listener:
// await triggerWorkflow("<workflow-id>", { foo: "bar" }, {
//   onStatus: ({ stage, requestId, error, result }) => {
//     console.log("[My App] workflow trigger status", stage, { requestId, error, result });
//   },
// });
// ---------------------------------------------------------------------------
export function triggerWorkflow(workflowId, triggerData, options) {
  const requestId = (globalThis.crypto && globalThis.crypto.randomUUID)
    ? globalThis.crypto.randomUUID()
    : (Date.now().toString(36) + Math.random().toString(36).slice(2));

  return new Promise((resolve, reject) => {
    const notify = (stage, details) => {
      try {
        if (options && typeof options.onStatus === "function") options.onStatus({ stage, ...details });
      } catch (_) {}
    };
    let timeoutId = null;

    const cleanup = () => {
      window.removeEventListener("message", onMessage);
      if (timeoutId) clearTimeout(timeoutId);
    };

    const onMessage = (event) => {
      const payload = event && event.data ? event.data : null;
      if (!payload || payload.type !== "app-trigger-workflow-result" || payload.requestId !== requestId) return;
      cleanup();
      if (payload.ok) {
        notify("queued", { requestId, workflowId, result: payload.result });
        console.log("[App SDK] Workflow trigger queued", { requestId, workflowId, result: payload.result });
        resolve(payload.result || { status: "queued" });
      } else {
        notify("failed", { requestId, workflowId, error: payload.error });
        console.error("[App SDK] Workflow trigger failed", { requestId, workflowId, error: payload.error });
        reject(new Error(payload.error || "Failed to trigger workflow"));
      }
    };

    window.addEventListener("message", onMessage);
    notify("listening", { requestId, workflowId });
    console.log("[App SDK] Listening for workflow trigger result", { requestId, workflowId });
    timeoutId = setTimeout(() => {
      cleanup();
      console.error("[App SDK] Workflow trigger timed out", { requestId, workflowId });
      notify("timeout", { requestId, workflowId });
      reject(new Error("Timed out waiting for workflow trigger response"));
    }, 15000);

    try {
      const sanitizedTriggerData = triggerData && typeof triggerData === "object" ? triggerData : undefined;
      console.log("[App SDK] Requesting workflow trigger", {
        requestId,
        appId: APP_ID,
        workflowId,
        triggerDataKeys: sanitizedTriggerData ? Object.keys(sanitizedTriggerData).sort() : [],
      });
      notify("posting", {
        requestId,
        appId: APP_ID,
        workflowId,
        triggerDataKeys: sanitizedTriggerData ? Object.keys(sanitizedTriggerData).sort() : [],
      });
      window.parent.postMessage({
        type: "app-trigger-workflow",
        requestId,
        appId: APP_ID,
        workflowId,
        triggerData: sanitizedTriggerData,
        transport: "sdk.triggerWorkflow",
      }, "*");
    } catch (err) {
      cleanup();
      reject(err instanceof Error ? err : new Error("Failed to post message to parent"));
    }
  });
}

// ---------------------------------------------------------------------------
// waitForWorkflowRun – poll workflow_runs until completed / failed / timeout
// ---------------------------------------------------------------------------
const WORKFLOW_RUN_ID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function waitForWorkflowRun(runId, options) {
  if (PUBLIC_MODE) {
    return Promise.reject(new Error("waitForWorkflowRun is not available in public mode"));
  }
  const id = String(runId || "").trim();
  if (!WORKFLOW_RUN_ID_RE.test(id)) {
    return Promise.reject(new Error("Invalid workflow run id"));
  }
  const timeoutMs = (options && options.timeoutMs) || 600000;
  const pollIntervalMs = (options && options.pollIntervalMs) || 2500;
  const requestId = (globalThis.crypto && globalThis.crypto.randomUUID)
    ? globalThis.crypto.randomUUID()
    : (Date.now().toString(36) + Math.random().toString(36).slice(2));

  return new Promise((resolve, reject) => {
    let timeoutId = null;

    const cleanup = () => {
      window.removeEventListener("message", onMessage);
      if (timeoutId) clearTimeout(timeoutId);
    };

    const onMessage = (event) => {
      const payload = event && event.data ? event.data : null;
      if (!payload || payload.type !== "app-wait-workflow-run-result" || payload.requestId !== requestId) {
        return;
      }
      cleanup();
      if (payload.ok) {
        resolve(payload.result || { status: "completed" });
      } else {
        reject(new Error(payload.error || "Failed to wait for workflow run"));
      }
    };

    window.addEventListener("message", onMessage);
    timeoutId = setTimeout(() => {
      cleanup();
      reject(new Error(
        "Workflow did not finish in time. Ensure the Celery worker is running (execute_workflow task).",
      ));
    }, timeoutMs);

    try {
      window.parent.postMessage({
        type: "app-wait-workflow-run",
        requestId,
        appId: APP_ID,
        runId: id,
        pollIntervalMs,
        transport: "sdk.waitForWorkflowRun",
      }, "*");
    } catch (err) {
      cleanup();
      reject(err instanceof Error ? err : new Error("Failed to post message to parent"));
    }
  });
}

// ---------------------------------------------------------------------------
// useAppSQL – arbitrary SELECT / DML (same guards as agent run_sql_* tools)
// ---------------------------------------------------------------------------

export function useAppSQL(sql, options) {
  const trimmed = (sql || "").trim();
  const isSelect = /^\\s*(select|with)\\b/i.test(trimmed);
  const [data, setData] = useState(null);
  const [columns, setColumns] = useState([]);
  const [loading, setLoading] = useState(Boolean(isSelect && options?.autoFetch !== false && !PUBLIC_MODE));
  const [error, setError] = useState(null);
  const abortRef = useRef(null);

  const postSql = useCallback(async (queryText) => {
    if (PUBLIC_MODE) {
      throw new Error("useAppSQL is not available in public mode");
    }
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const res = await fetch(API_BASE + "/apps/" + APP_ID + "/sql", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + APP_TOKEN,
      },
      body: JSON.stringify({ query: queryText }),
      signal: controller.signal,
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok) {
      if (res.status === 401) {
        try { window.parent.postMessage({ type: "app-token-expired" }, "*"); } catch (_) {}
      }
      throw new Error(json.detail || json.error || "SQL failed (" + res.status + ")");
    }
    if (json.rows !== undefined) {
      return { kind: "select", rows: json.rows, columns: json.columns || [] };
    }
    return { kind: "write", result: json };
  }, []);

  const refetch = useCallback(async () => {
    if (!trimmed || PUBLIC_MODE) return;
    setLoading(true);
    setError(null);
    try {
      const out = await postSql(trimmed);
      if (out.kind === "select") {
        setData(out.rows);
        setColumns(out.columns);
      }
    } catch (err) {
      if (err.name !== "AbortError") {
        setError(err instanceof Error ? err : new Error(err.message || "Unknown error"));
      }
    } finally {
      setLoading(false);
    }
  }, [trimmed, postSql]);

  useEffect(() => {
    if (!isSelect || options?.autoFetch === false || PUBLIC_MODE) {
      if (!isSelect || PUBLIC_MODE) setLoading(false);
      return;
    }
    void refetch();
    return () => {
      if (abortRef.current) abortRef.current.abort();
    };
  }, [isSelect, options?.autoFetch, refetch]);

  const mutate = useCallback(
    async (overrideQuery) => {
      const q = (overrideQuery != null ? String(overrideQuery) : trimmed).trim();
      if (!q) throw new Error("No SQL to execute");
      setLoading(true);
      setError(null);
      try {
        const out = await postSql(q);
        if (out.kind === "select") {
          setData(out.rows);
          setColumns(out.columns);
        }
        return out;
      } catch (err) {
        const e = err instanceof Error ? err : new Error(String(err));
        setError(e);
        throw e;
      } finally {
        setLoading(false);
      }
    },
    [trimmed, postSql]
  );

  return { data, columns, loading, error, refetch, mutate };
}

// ---------------------------------------------------------------------------
// useAppConnector – query / write / action on a connected connector
// ---------------------------------------------------------------------------

export function useAppConnector() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const execute = useCallback(async (config) => {
    if (PUBLIC_MODE) {
      const e = new Error("useAppConnector is not available in public mode");
      setError(e);
      throw e;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(API_BASE + "/apps/" + APP_ID + "/connector", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: "Bearer " + APP_TOKEN,
        },
        body: JSON.stringify(config),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) {
        if (res.status === 401) {
          try { window.parent.postMessage({ type: "app-token-expired" }, "*"); } catch (_) {}
        }
        throw new Error(json.detail || json.error || "Connector failed (" + res.status + ")");
      }
      if (json.error) {
        throw new Error(String(json.error));
      }
      return json;
    } catch (err) {
      const e = err instanceof Error ? err : new Error(String(err));
      setError(e);
      throw e;
    } finally {
      setLoading(false);
    }
  }, []);

  return { execute, loading, error };
}

// ---------------------------------------------------------------------------
// useDateRange – convert named periods to { start, end } ISO date strings
// ---------------------------------------------------------------------------
export function useDateRange(period) {
  const now = new Date();
  let start;
  let end = new Date(now);

  switch (period) {
    case "last_7d": {
      start = new Date(now);
      start.setDate(start.getDate() - 7);
      break;
    }
    case "last_30d": {
      start = new Date(now);
      start.setDate(start.getDate() - 30);
      break;
    }
    case "last_90d": {
      start = new Date(now);
      start.setDate(start.getDate() - 90);
      break;
    }
    case "last_quarter": {
      const q = Math.floor(now.getMonth() / 3);
      const prevQ = q === 0 ? 3 : q - 1;
      const year  = q === 0 ? now.getFullYear() - 1 : now.getFullYear();
      start = new Date(year, prevQ * 3, 1);
      end   = new Date(year, prevQ * 3 + 3, 0);
      break;
    }
    case "this_quarter": {
      const cq = Math.floor(now.getMonth() / 3);
      start = new Date(now.getFullYear(), cq * 3, 1);
      break;
    }
    case "ytd": {
      start = new Date(now.getFullYear(), 0, 1);
      break;
    }
    case "last_year": {
      start = new Date(now.getFullYear() - 1, 0, 1);
      end   = new Date(now.getFullYear() - 1, 11, 31);
      break;
    }
    case "this_year": {
      start = new Date(now.getFullYear(), 0, 1);
      break;
    }
    default: {
      start = new Date(now);
      start.setDate(start.getDate() - 30);
    }
  }

  return {
    start: start.toISOString().slice(0, 10),
    end:   end.toISOString().slice(0, 10),
  };
}

// ---------------------------------------------------------------------------
// UI primitives
// ---------------------------------------------------------------------------

export function Spinner() {
  return (
    <div style={{display:"flex",justifyContent:"center",padding:"2rem"}}>
      <div style={{
        width:24,height:24,border:"3px solid var(--app-spinner-track)",
        borderTop:"3px solid var(--app-accent)",borderRadius:"50%",
        animation:"spin 0.8s linear infinite",
      }}/>
      <style>{\`@keyframes spin{to{transform:rotate(360deg)}}\`}</style>
    </div>
  );
}

export function ErrorBanner({ message }) {
  return (
    <div style={{
      padding:"0.75rem 1rem",borderRadius:"0.5rem",
      background:"rgba(239,68,68,0.15)",border:"1px solid rgba(239,68,68,0.3)",
      color:"#fca5a5",fontSize:"0.875rem",
    }}>
      {message || "Something went wrong"}
    </div>
  );
}
`;

/**
 * Lightweight react-plotly.js shim that uses window.Plotly (loaded via CDN).
 *
 * This avoids bundling the 3.5 MB plotly.js package inside Sandpack, which
 * would cause the CodeSandbox bundler to time out.
 */
export const REACT_PLOTLY_SHIM: string = `
import React, { useRef, useEffect, useCallback } from "react";

function Plot({ data, layout, config, style, className, onInitialized, onUpdate, ...rest }) {
  const containerRef = useRef(null);
  const revisionRef = useRef(0);

  const doPlot = useCallback(() => {
    const el = containerRef.current;
    if (!el || !window.Plotly) return;
    const finalLayout = {
      ...(layout || {}),
      autosize: true,
    };
    const finalConfig = { responsive: true, ...(config || {}) };
    window.Plotly.react(el, data || [], finalLayout, finalConfig);
  }, [data, layout, config]);

  useEffect(() => {
    doPlot();
  }, [doPlot]);

  // Cleanup
  useEffect(() => {
    return () => {
      if (containerRef.current && window.Plotly) {
        try { window.Plotly.purge(containerRef.current); } catch (_) {}
      }
    };
  }, []);

  return React.createElement("div", {
    ref: containerRef,
    style: style || { width: "100%", height: "400px" },
    className: className || "",
  });
}

export default Plot;
`;

/** Matches Basebase shell :root / .dark surface tokens (see index.css). */
export type AppTheme = 'light' | 'dark';

const APP_THEME_CSS: Record<AppTheme, string> = {
  light: `
  --app-bg: #f9fafb;
  --app-fg: #333538;
  --app-muted: #7e8288;
  --app-border: #e2e4e7;
  --app-card-bg: #ffffff;
  --app-control-bg: #f0f1f3;
  --app-control-fg: #333538;
  --app-tag-bg: #f0f1f3;
  --app-tag-fg: #64686d;
  --app-accent: #6366f1;
  --app-accent-muted: #818cf8;
  --app-body-muted: #7e8288;
  --app-spinner-track: rgba(0, 0, 0, 0.08);
  `,
  dark: `
  --app-bg: #18181b;
  --app-fg: #e4e4e7;
  --app-muted: #a1a1aa;
  --app-border: #3f3f46;
  --app-card-bg: rgba(24, 24, 27, 0.6);
  --app-control-bg: #27272a;
  --app-control-fg: #e4e4e7;
  --app-tag-bg: #27272a;
  --app-tag-fg: #a1a1aa;
  --app-accent: #6366f1;
  --app-accent-muted: #818cf8;
  --app-body-muted: #71717a;
  --app-spinner-track: rgba(255, 255, 255, 0.15);
  `,
};

/** CSS injected into every embedded app iframe; follows the host light/dark theme. */
export function getAppStyles(theme: AppTheme): string {
  return `
* { box-sizing: border-box; margin: 0; padding: 0; }
:root { ${APP_THEME_CSS[theme]} }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: var(--app-bg);
  color: var(--app-fg);
  padding: 1rem;
}
select, input, button {
  font-family: inherit;
  font-size: 0.875rem;
  background: var(--app-control-bg);
  color: var(--app-control-fg);
  border: 1px solid var(--app-border);
  border-radius: 0.375rem;
  padding: 0.5rem 0.75rem;
  outline: none;
}
select:focus, input:focus { border-color: var(--app-accent); }
button {
  cursor: pointer;
  background: var(--app-accent);
  border-color: var(--app-accent);
  color: #fff;
  font-weight: 500;
}
button:hover { filter: brightness(0.92); }
button:disabled { opacity: 0.6; cursor: not-allowed; }
table { width: 100%; border-collapse: collapse; }
th, td {
  text-align: left; padding: 0.5rem 0.75rem;
  border-bottom: 1px solid var(--app-border);
  font-size: 0.875rem;
}
th { color: var(--app-muted); font-weight: 500; }
`;
}

/** @deprecated Use getAppStyles(theme) — kept for imports that expect a string constant. */
export const APP_STYLES: string = getAppStyles('dark');
