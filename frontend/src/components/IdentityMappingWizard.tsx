/**
 * Identity Mapping Wizard – shown during connector setup to link external
 * platform users (GitHub logins, Slack members) to internal team members.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { HiCheck, HiChevronDown, HiX } from "react-icons/hi";
import { apiRequest } from "../lib/api";

// ── Types ────────────────────────────────────────────────────────────

interface ExternalUserRow {
  external_id: string;
  display_name: string;
  email: string | null;
  avatar_url: string | null;
  source: string;
  suggested_user_id: string | null;
  match_confidence: string | null;
}

interface TeamMemberRow {
  user_id: string;
  name: string | null;
  email: string | null;
  avatar_url: string | null;
}

interface ListExternalUsersResponse {
  external_users: ExternalUserRow[];
  team_members: TeamMemberRow[];
}

interface SaveIdentityMappingsResponse {
  saved: number;
}

export interface IdentityMappingWizardProps {
  organizationId: string;
  provider: string;
  onComplete: () => void;
  onSkip: () => void;
}

// ── Helpers ──────────────────────────────────────────────────────────

const PROVIDER_LABELS: Record<string, string> = {
  github: "GitHub",
  slack: "Slack",
};

function providerLabel(provider: string): string {
  return PROVIDER_LABELS[provider] ?? provider;
}

function Avatar({ url, name, size = 32 }: { url: string | null; name: string; size?: number }): JSX.Element {
  const initials: string = name
    .split(" ")
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  if (url) {
    return (
      <img
        src={url}
        alt={name}
        className="rounded-full object-cover flex-shrink-0"
        style={{ width: size, height: size }}
      />
    );
  }
  return (
    <div
      className="rounded-full bg-surface-700 flex items-center justify-center text-surface-300 text-xs font-medium flex-shrink-0"
      style={{ width: size, height: size }}
    >
      {initials}
    </div>
  );
}

// ── Dropdown for team member selection ───────────────────────────────

interface MemberDropdownProps {
  teamMembers: TeamMemberRow[];
  selectedUserId: string | null;
  onChange: (userId: string | null) => void;
}

function MemberDropdown({ teamMembers, selectedUserId, onChange }: MemberDropdownProps): JSX.Element {
  const [open, setOpen] = useState<boolean>(false);
  const selected: TeamMemberRow | undefined = teamMembers.find((m) => m.user_id === selectedUserId);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg border border-surface-600 bg-surface-800 hover:bg-surface-700 text-sm min-w-[180px] text-left"
      >
        {selected ? (
          <>
            <Avatar url={selected.avatar_url ?? null} name={selected.name ?? "?"} size={20} />
            <span className="text-surface-100 truncate flex-1">{selected.name ?? selected.email}</span>
          </>
        ) : (
          <span className="text-surface-500 flex-1">Select team member…</span>
        )}
        <HiChevronDown className="w-4 h-4 text-surface-400 flex-shrink-0" />
      </button>
      {open && (
        <div className="absolute z-50 mt-1 w-64 max-h-56 overflow-y-auto rounded-lg border border-surface-600 bg-surface-800 shadow-xl">
          <button
            type="button"
            onClick={() => { onChange(null); setOpen(false); }}
            className="w-full text-left px-3 py-2 text-sm text-surface-400 hover:bg-surface-700"
          >
            — None —
          </button>
          {teamMembers.map((m) => (
            <button
              key={m.user_id}
              type="button"
              onClick={() => { onChange(m.user_id); setOpen(false); }}
              className="w-full text-left px-3 py-2 flex items-center gap-2 text-sm text-surface-100 hover:bg-surface-700"
            >
              <Avatar url={m.avatar_url ?? null} name={m.name ?? "?"} size={20} />
              <div className="truncate flex-1">
                <span className="font-medium">{m.name}</span>
                {m.email ? <span className="text-surface-400 ml-1 text-xs">{m.email}</span> : null}
              </div>
              {m.user_id === selectedUserId ? <HiCheck className="w-4 h-4 text-primary-400" /> : null}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main wizard ──────────────────────────────────────────────────────

export function IdentityMappingWizard({
  organizationId,
  provider,
  onComplete,
  onSkip,
}: IdentityMappingWizardProps): JSX.Element {
  const [loading, setLoading] = useState<boolean>(true);
  const [saving, setSaving] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [externalUsers, setExternalUsers] = useState<ExternalUserRow[]>([]);
  const [teamMembers, setTeamMembers] = useState<TeamMemberRow[]>([]);

  // Map: external_id → user_id (or null)
  const [mappings, setMappings] = useState<Record<string, string | null>>({});

  const fetchExternalUsers = useCallback(async () => {
    setLoading(true);
    setError(null);
    const { data, error: err } = await apiRequest<ListExternalUsersResponse>(
      `/sync/${organizationId}/${provider}/list-external-users`,
      { method: "POST" },
    );
    if (err) {
      setError(err);
      setLoading(false);
      return;
    }
    if (data) {
      setExternalUsers(data.external_users);
      setTeamMembers(data.team_members);
      const initial: Record<string, string | null> = {};
      for (const eu of data.external_users) {
        initial[eu.external_id] = eu.suggested_user_id ?? null;
      }
      setMappings(initial);
    }
    setLoading(false);
  }, [organizationId, provider]);

  useEffect(() => {
    void fetchExternalUsers();
  }, [fetchExternalUsers]);

  const handleMappingChange = useCallback((externalId: string, userId: string | null) => {
    setMappings((prev) => ({ ...prev, [externalId]: userId }));
  }, []);

  const mappedCount: number = useMemo(
    () => Object.values(mappings).filter((v) => v !== null).length,
    [mappings],
  );

  const handleSave = useCallback(async () => {
    setSaving(true);
    setError(null);

    const entries: Array<{ external_id: string; user_id: string; source: string }> = [];
    for (const [extId, userId] of Object.entries(mappings)) {
      if (userId) {
        const ext: ExternalUserRow | undefined = externalUsers.find((e) => e.external_id === extId);
        entries.push({
          external_id: extId,
          user_id: userId,
          source: ext?.source ?? provider,
        });
      }
    }

    if (entries.length > 0) {
      const { error: saveErr } = await apiRequest<SaveIdentityMappingsResponse>(
        `/sync/${organizationId}/${provider}/save-identity-mappings`,
        {
          method: "POST",
          body: JSON.stringify({ mappings: entries }),
        },
      );
      if (saveErr) {
        setError(saveErr);
        setSaving(false);
        return;
      }
    }

    setSaving(false);
    onComplete();
  }, [mappings, externalUsers, organizationId, provider, onComplete]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div
        className="bg-surface-900 border border-surface-700 rounded-xl shadow-xl w-full max-w-2xl mx-4 max-h-[85vh] flex flex-col"
        onClick={(e: React.MouseEvent) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-surface-700">
          <div>
            <h2 className="text-lg font-semibold text-surface-100">
              Map {providerLabel(provider)} Users
            </h2>
            <p className="text-sm text-surface-400 mt-0.5">
              Link external accounts to your team members so activity is correctly attributed.
            </p>
          </div>
          <button
            onClick={onSkip}
            className="p-1 text-surface-400 hover:text-surface-200 rounded"
            aria-label="Close"
          >
            <HiX className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          {loading ? (
            <div className="flex items-center justify-center py-16 text-surface-400 gap-2">
              <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                />
              </svg>
              Fetching {providerLabel(provider)} users…
            </div>
          ) : error ? (
            <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-red-300 text-sm">
              {error}
            </div>
          ) : externalUsers.length === 0 ? (
            <p className="text-surface-400 text-sm py-8 text-center">
              No external users found. You can skip this step and map users later from the Team settings.
            </p>
          ) : (
            <div className="space-y-2">
              {externalUsers.map((eu) => {
                const currentMapping: string | null = mappings[eu.external_id] ?? null;
                const isAutoMatched: boolean = eu.suggested_user_id !== null && currentMapping === eu.suggested_user_id;
                return (
                  <div
                    key={eu.external_id}
                    className={`flex items-center gap-3 px-3 py-2.5 rounded-lg border ${
                      currentMapping
                        ? isAutoMatched
                          ? "border-green-500/30 bg-green-500/5"
                          : "border-primary-500/30 bg-primary-500/5"
                        : "border-surface-700 bg-surface-800/50"
                    }`}
                  >
                    <Avatar url={eu.avatar_url} name={eu.display_name} size={36} />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-surface-100 truncate">
                        {eu.display_name}
                      </div>
                      <div className="text-xs text-surface-400 truncate">
                        {eu.external_id}
                        {eu.email ? ` · ${eu.email}` : ""}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {isAutoMatched ? (
                        <span className="text-xs text-green-400 whitespace-nowrap">
                          Auto-matched ({eu.match_confidence})
                        </span>
                      ) : null}
                      <MemberDropdown
                        teamMembers={teamMembers}
                        selectedUserId={currentMapping}
                        onChange={(uid) => handleMappingChange(eu.external_id, uid)}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-surface-700">
          <div className="text-sm text-surface-400">
            {mappedCount} of {externalUsers.length} mapped
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={onSkip}
              className="px-4 py-2 text-sm text-surface-300 hover:text-surface-100 rounded-lg"
            >
              Skip for now
            </button>
            <button
              type="button"
              disabled={saving}
              onClick={() => void handleSave()}
              className="px-4 py-2 text-sm font-medium text-white bg-primary-600 hover:bg-primary-500 disabled:opacity-50 rounded-lg"
            >
              {saving ? "Saving…" : "Confirm & Continue"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
