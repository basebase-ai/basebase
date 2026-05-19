"""
Default Daily Digest workflow prompt and Home App definitions.

Seeded per organization by migration; orgs may customize after creation.
"""
from __future__ import annotations

from typing import Any

DAILY_DIGEST_WORKFLOW_NAME: str = "Daily Digest"
DAILY_DIGEST_APP_TITLE: str = "Daily Digest"

DAILY_DIGEST_WORKFLOW_PROMPT: str = """Generate the team daily digest for one calendar day (America/Los_Angeles).

## Date
1. If trigger data includes digest_date (YYYY-MM-DD), use it for all steps below.
2. Otherwise compute digest_date as yesterday in America/Los_Angeles (YYYY-MM-DD).

## Active members
Run SQL to list members to summarize:
SELECT om.user_id, u.name
FROM org_members om
JOIN users u ON u.id = om.user_id
WHERE om.status = 'active' AND u.is_guest = false
ORDER BY u.name

## Per-member summaries
For EACH active member:
1. Call collect_digest_data(user_id=<uuid>, digest_date=<digest_date>).
2. If all activity arrays are empty, set summary JSON to a quiet-day narrative using member_name and org_name from the tool result (no LLM needed).
3. Otherwise summarize the raw JSON. Return ONLY valid JSON (no markdown fences) with keys:
   - narrative: 1-2 sentences, past tense, use the member's first name
   - highlights: array of short strings (max 8)
   - categories: object with optional keys code, issues, meetings, slack, calendar, crm, documents (arrays of short strings)
   Only report actions the person actively took. Ignore automated emails and passive noise.
   Refer ONLY to that single calendar day.
4. Upsert into temp_data with:
   - namespace = 'daily_digest'
   - key = digest_date (string)
   - entity_type = 'user'
   - entity_id = user_id
   - value = summary JSON including active_sources from collect_digest_data
   - metadata = {"generated_at": "<ISO8601 UTC now>"}
   Use INSERT ... ON CONFLICT ON CONSTRAINT uq_temp_data_digest_slot DO UPDATE SET value = EXCLUDED.value, metadata = EXCLUDED.metadata;

## Team summary
1. Read member narratives from temp_data for this digest_date (entity_type = 'user').
2. Optionally read prior team rows (entity_type = 'team', last 4 days before digest_date) for context.
3. Produce 1-4 markdown sections (# Title, 1-2 sentences each) on shared goals/initiatives. Past tense, no bullet lists. If everyone was quiet, use "# Quiet Day" with a short note.
4. Upsert team row: namespace='daily_digest', key=digest_date, entity_type='team', entity_id=<organization_id>, value={"summary_text": "...", "member_count": N}, metadata with generated_at.

## Finish
Confirm how many member rows and whether team summary were written.
"""

DAILY_DIGEST_APP_QUERIES: dict[str, Any] = {
    "member_digests": {
        "sql": """
SELECT
  td.entity_id AS user_id,
  u.name,
  u.avatar_url,
  td.value,
  td.metadata
FROM temp_data td
LEFT JOIN users u ON u.id = td.entity_id
WHERE td.namespace = 'daily_digest'
  AND td.key = :date
  AND td.entity_type = 'user'
ORDER BY u.name NULLS LAST
""".strip(),
        "params": {
            "date": {"type": "string", "required": True},
        },
    },
    "team_summary": {
        "sql": """
SELECT td.value
FROM temp_data td
WHERE td.namespace = 'daily_digest'
  AND td.key = :date
  AND td.entity_type = 'team'
LIMIT 1
""".strip(),
        "params": {
            "date": {"type": "string", "required": True},
        },
    },
    "available_dates": {
        "sql": """
SELECT DISTINCT td.key AS digest_date
FROM temp_data td
WHERE td.namespace = 'daily_digest'
  AND td.entity_type = 'team'
  AND td.key IS NOT NULL
ORDER BY td.key DESC
LIMIT 30
""".strip(),
        "params": {},
    },
    "digest_workflow": {
        "sql": """
SELECT id AS workflow_id
FROM workflows
WHERE name = 'Daily Digest'
  AND is_enabled = true
  AND archived_at IS NULL
LIMIT 1
""".strip(),
        "params": {},
    },
}

DAILY_DIGEST_APP_FRONTEND_CODE: str = """
function addDays(iso, delta) {
  const parts = iso.split("-");
  const y = Number(parts[0]);
  const m = Number(parts[1]);
  const d = Number(parts[2]);
  const dt = new Date(Date.UTC(y, m - 1, d + delta));
  return dt.toISOString().slice(0, 10);
}

function formatDisplay(iso) {
  const parts = iso.split("-");
  return parts[1] + "/" + parts[2] + "/" + parts[0];
}

function narrativeOf(summary) {
  if (!summary || typeof summary !== "object") return "";
  return String(summary.narrative || "").trim();
}

function MemberCard({ row }) {
  const name = (row.name || row.user_id || "").trim() || "Member";
  const summary = row.value || {};
  const narrative = narrativeOf(summary);
  const highlights = Array.isArray(summary.highlights) ? summary.highlights : [];
  const sources = Array.isArray(summary.active_sources) ? summary.active_sources : [];
  const initial = name.slice(0, 1).toUpperCase();
  return (
    <article style={{
      border: "1px solid var(--app-border)",
      borderRadius: "0.75rem",
      padding: "1rem",
      background: "var(--app-card-bg)",
      display: "flex",
      flexDirection: "column",
      gap: "0.75rem",
      maxHeight: "28rem",
      overflowY: "auto",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
        {row.avatar_url ? (
          <img src={row.avatar_url} alt="" style={{ width: 40, height: 40, borderRadius: "50%", objectFit: "cover" }} />
        ) : (
          <div style={{
            width: 40, height: 40, borderRadius: "50%", background: "var(--app-control-bg)",
            display: "flex", alignItems: "center", justifyContent: "center",
            color: "var(--app-control-fg)", fontWeight: 500,
          }}>{initial}</div>
        )}
        <h3 style={{ margin: 0, color: "var(--app-fg)", fontSize: "1rem", fontWeight: 500 }}>{name}</h3>
      </div>
      {sources.length > 0 ? (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.35rem" }}>
          {sources.map((s) => (
            <span key={s} style={{
              fontSize: "0.7rem", padding: "0.15rem 0.45rem",
              borderRadius: "0.35rem", background: "var(--app-tag-bg)", color: "var(--app-tag-fg)",
            }}>{s}</span>
          ))}
        </div>
      ) : null}
      {narrative ? (
        <p style={{ color: "var(--app-fg)", fontSize: "0.875rem", lineHeight: 1.6, margin: 0 }}>{narrative}</p>
      ) : (
        <p style={{ color: "var(--app-body-muted)", fontSize: "0.875rem", margin: 0 }}>No digest for this day yet.</p>
      )}
      {highlights.length > 0 ? (
        <ul style={{ margin: 0, paddingLeft: "1.25rem", color: "var(--app-muted)", fontSize: "0.875rem" }}>
          {highlights.map((h, i) => (
            <li key={i}>{String(h)}</li>
          ))}
        </ul>
      ) : null}
    </article>
  );
}

export default function App() {
  const [digestDate, setDigestDate] = useState(function() {
    const d = new Date();
    d.setUTCDate(d.getUTCDate() - 1);
    return d.toISOString().slice(0, 10);
  });
  const [search, setSearch] = useState("");
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState(null);

  const dateParams = useMemo(function() { return { date: digestDate }; }, [digestDate]);
  const membersQuery = useAppQuery("member_digests", dateParams);
  const teamQuery = useAppQuery("team_summary", dateParams);
  const wfQuery = useAppQuery("digest_workflow", {});

  const members = membersQuery.data;
  const membersLoading = membersQuery.loading;
  const membersError = membersQuery.error;
  const refetchMembers = membersQuery.refetch;
  const refetchTeam = teamQuery.refetch;

  const teamSummary = teamQuery.data && teamQuery.data[0] && teamQuery.data[0].value
    ? (teamQuery.data[0].value.summary_text || "")
    : "";

  const workflowId = wfQuery.data && wfQuery.data[0] ? wfQuery.data[0].workflow_id : null;

  const filtered = useMemo(function() {
    const rows = members || [];
    const q = search.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(function(m) {
      return String(m.name || m.user_id || "").toLowerCase().indexOf(q) >= 0;
    });
  }, [members, search]);

  const handleGenerate = useCallback(async function() {
    if (!workflowId) {
      setGenError("Daily Digest workflow not found for this organization.");
      return;
    }
    setGenerating(true);
    setGenError(null);
    try {
      const queued = await triggerWorkflow(workflowId, { digest_date: digestDate });
      const runId = queued && queued.run_id ? String(queued.run_id) : "";
      if (runId) {
        await waitForWorkflowRun(runId, { timeoutMs: 600000, pollIntervalMs: 3000 });
      }
      await refetchMembers();
      await refetchTeam();
    } catch (e) {
      setGenError(e instanceof Error ? e.message : String(e));
    } finally {
      setGenerating(false);
    }
  }, [workflowId, digestDate, refetchMembers, refetchTeam]);

  const loading = membersLoading;
  const error = membersError || genError;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1rem", maxWidth: 1200, margin: "0 auto" }}>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "0.5rem", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <button type="button" onClick={function() { setDigestDate(function(d) { return addDays(d, -1); }); }} style={{ background: "var(--app-control-bg)", borderColor: "var(--app-border)", color: "var(--app-control-fg)" }}>←</button>
          <span style={{ fontWeight: 500, minWidth: "7rem", textAlign: "center", color: "var(--app-fg)" }}>{formatDisplay(digestDate)}</span>
          <button type="button" onClick={function() { setDigestDate(function(d) { return addDays(d, 1); }); }} style={{ background: "var(--app-control-bg)", borderColor: "var(--app-border)", color: "var(--app-control-fg)" }}>→</button>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", alignItems: "center" }}>
          <input
            type="text"
            placeholder="Search members…"
            value={search}
            onChange={function(e) { setSearch(e.target.value); }}
            style={{ minWidth: "8rem" }}
          />
          <button type="button" disabled={generating} onClick={function() { void handleGenerate(); }}>
            {generating ? "Generating…" : "Generate"}
          </button>
          <button type="button" onClick={function() { void refetchMembers(); void refetchTeam(); }} style={{ background: "var(--app-control-bg)", borderColor: "var(--app-accent)", color: "var(--app-accent-muted)" }}>
            Refresh
          </button>
        </div>
      </div>

      {error ? <ErrorBanner message={String(error)} /> : null}
      {loading ? <Spinner /> : null}

      {!loading && teamSummary ? (
        <article style={{
          border: "1px solid rgba(99,102,241,0.35)",
          borderRadius: "0.75rem",
          padding: "1rem",
          background: "var(--app-card-bg)",
        }}>
          <div style={{ fontSize: "0.7rem", fontWeight: 600, color: "var(--app-accent-muted)", textTransform: "uppercase", marginBottom: "0.5rem" }}>Team Summary</div>
          <div style={{ color: "var(--app-muted)", fontSize: "0.875rem", lineHeight: 1.6, whiteSpace: "pre-wrap" }}>{teamSummary}</div>
        </article>
      ) : null}

      {!loading && filtered.length === 0 ? (
        <p style={{ color: "var(--app-body-muted)", fontSize: "0.875rem" }}>No team members or no digest data for this day.</p>
      ) : null}

      {!loading && filtered.length > 0 ? (
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
          gap: "1rem",
        }}>
          {filtered.map(function(m) {
            return <MemberCard key={m.user_id} row={m} />;
          })}
        </div>
      ) : null}
    </div>
  );
}
"""
