/**
 * Connectors management screen.
 * 
 * Features:
 * - View all connected connectors
 * - View available connectors to connect
 * - Sync status and manual sync trigger
 * - Disconnect integrations
 * 
 * Uses React Query for server state (integrations list).
 */

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import Nango from '@nangohq/frontend';
import {
  HiGlobeAlt,
  HiUserGroup,
  HiX,
  HiCog,
  HiShare,
  HiLockClosed,
  HiChevronDown,
  HiLightningBolt,
  HiLink,
  HiDotsVertical,
} from 'react-icons/hi';
import { API_BASE, apiRequest, getAuthenticatedRequestHeaders } from '../lib/api';
import { useAppStore, useIntegrations, useIntegrationsLoading, type Integration, type SyncStats } from '../store';
import { useWebSocket } from '../hooks/useWebSocket';
import { IdentityMappingWizard } from './IdentityMappingWizard';
import {
  CONNECTOR_DISPLAY as CONNECTOR_DISPLAY_OVERRIDE,
  CONNECTOR_ICON_MAP as ICON_MAP,
  DEFAULT_CONNECTOR_ICON as DEFAULT_ICON,
  DEFAULT_CONNECTOR_COLOR as DEFAULT_COLOR,
  isImageIcon,
  getConnectorColorClass as getColorClass,
} from './shared/ConnectorIcons';

/** Connector metadata from GET /api/connectors */
interface ConnectorMetaFromApi {
  slug: string;
  name: string;
  description: string;
  auth_type: string;
  scope: 'user' | 'organization';
  default_sharing: { share_synced_data: boolean; share_query_access: boolean; share_write_access: boolean };
  connection_flow: 'oauth' | 'builtin' | 'custom_credentials';
  capabilities: string[];
  icon: string;
}

/** Fallback when API fails or provider not in registry. */
interface IntegrationConfigEntry {
  name: string;
  description: string;
  icon: string;
  color: string;
  scope: 'organization' | 'user';
}

const INTEGRATION_CONFIG_FALLBACK: Record<string, IntegrationConfigEntry> = {
  hubspot: { name: 'HubSpot', description: 'CRM data including deals, contacts, and companies', icon: 'hubspot', color: 'from-orange-500 to-orange-600', scope: 'user' },
  salesforce: { name: 'Salesforce', description: 'CRM - Opportunities, Accounts', icon: 'salesforce', color: 'from-blue-500 to-blue-600', scope: 'user' },
  slack: { name: 'Slack', description: 'Team messages and communication history', icon: 'slack', color: 'from-purple-500 to-purple-600', scope: 'organization' },
  zoom: { name: 'Zoom', description: 'Meeting transcripts and cloud recording insights', icon: 'zoom', color: 'from-blue-400 to-blue-500', scope: 'user' },
  google_calendar: { name: 'Google Calendar', description: 'Meetings, events, and scheduling data', icon: 'google_calendar', color: 'from-green-500 to-green-600', scope: 'user' },
  gmail: { name: 'Gmail', description: 'Google email communications', icon: 'gmail', color: 'from-red-500 to-red-600', scope: 'user' },
  microsoft_calendar: { name: 'Microsoft Calendar', description: 'Outlook calendar events and meetings', icon: 'microsoft_calendar', color: 'from-sky-500 to-sky-600', scope: 'user' },
  microsoft_mail: { name: 'Microsoft Mail', description: 'Outlook emails and communications', icon: 'microsoft_mail', color: 'from-sky-500 to-sky-600', scope: 'user' },
  fireflies: { name: 'Fireflies', description: 'Meeting transcriptions and notes', icon: 'fireflies', color: 'from-violet-500 to-violet-600', scope: 'user' },
  granola: { name: 'Granola', description: 'AI meeting notes, transcripts, and action items', icon: '/connector-icons/granola.png', color: 'from-lime-500 to-green-600', scope: 'user' },
  google_drive: { name: 'Google Drive', description: 'Docs, Sheets, Slides, and Gemini meeting notes from Drive', icon: 'google_drive', color: 'from-yellow-500 to-amber-500', scope: 'user' },
  apollo: { name: 'Apollo.io', description: 'Data enrichment - Contact titles, companies, emails', icon: 'apollo', color: 'from-yellow-400 to-yellow-500', scope: 'user' },
  github: { name: 'GitHub', description: 'Track repos, commits, and pull requests by team', icon: 'github', color: 'from-gray-600 to-gray-700', scope: 'user' },
  linear: { name: 'Linear', description: 'Issue tracking - sync and manage teams, projects, and issues', icon: 'linear', color: 'from-indigo-500 to-violet-600', scope: 'user' },
  jira: { name: 'Jira', description: 'Issue tracking - sync projects and issues from Atlassian Jira', icon: 'jira', color: 'from-blue-500 to-blue-600', scope: 'user' },
  asana: { name: 'Asana', description: 'Tasks and projects - sync and manage workspaces, projects, and tasks', icon: 'asana', color: 'from-fuchsia-500 to-pink-600', scope: 'user' },
  trello: { name: 'Trello', description: 'Boards and cards – sync workspaces, boards, lists, and cards', icon: 'trello', color: 'from-blue-600 to-sky-500', scope: 'user' },
  web_search: { name: 'Web Search', description: 'Web search and URL fetching — enable for the agent to search the web or fetch pages', icon: 'globe', color: 'from-emerald-500 to-teal-600', scope: 'organization' },
  code_sandbox: { name: 'Code Sandbox', description: 'Run shell commands and scripts in a secure sandbox (Python, Node, bash)', icon: 'terminal', color: 'from-amber-500 to-orange-600', scope: 'organization' },
  twilio: { name: 'Twilio', description: 'Send SMS messages to phone numbers', icon: 'sms', color: 'from-red-500 to-pink-600', scope: 'organization' },
  artifacts: { name: 'Artifact Builder', description: 'Create and update downloadable files (reports, markdown, PDFs, charts)', icon: 'artifacts', color: 'from-slate-500 to-slate-600', scope: 'organization' },
  apps: { name: 'App Builder', description: 'Create and update interactive mini-apps with React + SQL', icon: 'apps', color: 'from-violet-500 to-purple-600', scope: 'organization' },
  mcp: { name: 'MCP Server', description: 'Connect any MCP-compatible server by URL', icon: 'plug', color: 'from-cyan-500 to-blue-600', scope: 'user' },
  ispot_tv: { name: 'iSpot.tv', description: 'TV ad analytics — airings, spend, impressions, and conversions', icon: 'globe', color: 'from-emerald-500 to-teal-600', scope: 'organization' },
};

const CALENDAR_SHARING_WARNING_PROVIDERS = new Set(['google_calendar', 'microsoft_calendar']);

const isSharedWithTeam = (sharing: {
  shareSyncedData: boolean;
  shareQueryAccess: boolean;
  shareWriteAccess: boolean;
}): boolean => sharing.shareSyncedData || sharing.shareQueryAccess || sharing.shareWriteAccess;

// Extended integration type with display info
interface DisplayIntegration extends Integration {
  name: string;
  description: string;
  icon: string;
  color: string;
  connected: boolean;
}

/** ISO8601 UTC timestamp for ``since`` query (manual resync from). */
function isoUtcSubtractMs(offsetMs: number): string {
  return new Date(Date.now() - offsetMs).toISOString();
}

const RESYNC_OFFSET_MS = {
  hours24: 24 * 60 * 60 * 1000,
  days7: 7 * 24 * 60 * 60 * 1000,
  days30: 30 * 24 * 60 * 60 * 1000,
} as const;

interface SlackUserMapping {
  id: string;
  external_userid: string | null;
  external_email: string | null;
  source: string;
  match_source: string;
  created_at: string;
}

/**
 * Format sync stats into a human-readable summary string.
 * Shows counts for different object types synced.
 * Always shows stats for CRM providers (even zeros) for trust/debugging.
 */
function formatSyncStats(stats: SyncStats | null, provider: string): string | null {
  if (!stats) return null;

  const parts: string[] = [];

  // GitHub: show repos, commits, PRs
  if (provider === 'github') {
    const repos = stats.repositories ?? 0;
    const commits = stats.commits ?? 0;
    const prs = stats.pull_requests ?? 0;
    if (repos > 0) parts.push(`${repos} repos`);
    if (commits > 0) parts.push(`${commits.toLocaleString()} commits`);
    if (prs > 0) parts.push(`${prs} PRs`);
  } else if (provider === 'linear' || provider === 'jira' || provider === 'asana') {
    // Issue tracker providers: teams, projects, issues
    const teams = stats.teams ?? 0;
    const projects = stats.projects ?? 0;
    const issues = stats.issues ?? 0;
    if (teams > 0) parts.push(`${teams} ${teams === 1 ? 'team' : 'teams'}`);
    if (projects > 0) parts.push(`${projects} ${projects === 1 ? 'project' : 'projects'}`);
    if (issues > 0) parts.push(`${issues.toLocaleString()} issues`);
  } else if (provider === 'google_drive') {
    const total = stats.total_files ?? 0;
    const docs = stats.docs ?? 0;
    const sheets = stats.sheets ?? 0;
    const slides = stats.slides ?? 0;
    if (total > 0) parts.push(`${total.toLocaleString()} files`);
    if (docs > 0) parts.push(`${docs} docs`);
    if (sheets > 0) parts.push(`${sheets} sheets`);
    if (slides > 0) parts.push(`${slides} slides`);
  } else if (provider === 'slack') {
    const messages = stats.activities ?? 0;
    const channels = stats.channels ?? 0;
    if (channels > 0) {
      parts.push(`${messages.toLocaleString()} messages from ${channels} channel${channels !== 1 ? 's' : ''}`);
    } else {
      parts.push(`${messages.toLocaleString()} messages from 0 channels`);
    }
  } else {
  // CRM providers always show contact/account/deal counts (even if 0)
  const isCrmProvider = provider === 'hubspot' || provider === 'salesforce';
  if (isCrmProvider) {
    // Always show CRM stats for trust and debugging
    const contacts = stats.contacts ?? 0;
    const accounts = stats.accounts ?? 0;
    const deals = stats.deals ?? 0;
    parts.push(`${contacts.toLocaleString()} contacts`);
    parts.push(`${accounts.toLocaleString()} accounts`);
    parts.push(`${deals.toLocaleString()} deals`);
    if (stats.goals && stats.goals > 0) {
      parts.push(`${stats.goals.toLocaleString()} goals`);
    }
  } else {
    // Non-CRM: only show if > 0
    if (stats.contacts && stats.contacts > 0) {
      parts.push(`${stats.contacts.toLocaleString()} contacts`);
    }
    if (stats.accounts && stats.accounts > 0) {
      parts.push(`${stats.accounts.toLocaleString()} accounts`);
    }
    if (stats.deals && stats.deals > 0) {
      parts.push(`${stats.deals.toLocaleString()} deals`);
    }
  }
  }

  // Activity-based connectors (email, calendar, meetings) — Slack handled above
  if (provider !== 'slack' && stats.activities !== undefined) {
    const activityLabel = getActivityLabel(provider, stats.activities);
    parts.push(activityLabel);
  }

  if (parts.length === 0) return null;

  return parts.join(', ');
}

/**
 * Map CRM sync step to the noun used in the count label (e.g. "accounts", "deals").
 */
function getCrmStepNoun(step: string): string {
  if (step === 'accounts' || step === 'fetching accounts') return 'accounts';
  if (step === 'deals' || step === 'fetching deals') return 'deals';
  if (step === 'contacts' || step === 'fetching contacts') return 'contacts';
  if (step === 'activities') return 'activities';
  if (step === 'goals' || step === 'fetching goals') return 'goals';
  return 'items';
}

/**
 * Get a provider-specific label for activities count.
 * For CRM providers (HubSpot/Salesforce), pass optional step so the label matches the current sync phase (e.g. "0 accounts" during account sync).
 */
function getActivityLabel(provider: string, count: number, step?: string): string {
  const formatted = count.toLocaleString();
  if ((provider === 'hubspot' || provider === 'salesforce') && step !== undefined) {
    return `${formatted} ${getCrmStepNoun(step)}`;
  }
  switch (provider) {
    case 'gmail':
    case 'microsoft_mail':
      return `${formatted} emails`;
    case 'google_calendar':
    case 'microsoft_calendar':
      return `${formatted} meetings`;
    case 'slack':
      return `${formatted} messages`;
    case 'fireflies':
    case 'zoom':
      return `${formatted} recordings`;
    case 'hubspot':
    case 'salesforce':
      return `${formatted} activities`;
    default:
      return `${formatted} activities`;
  }
}


const SYNC_STARTED_STALE_MS = 2 * 60 * 60 * 1000;
const SYNC_PROGRESS_COMPLETE_HOLD_MS = 1200;

function isFreshSyncStartedAt(startedAt?: string): boolean {
  if (!startedAt) return false;
  const normalized = startedAt.endsWith('Z') || /[+-]\d{2}:?\d{2}$/.test(startedAt) ? startedAt : `${startedAt}Z`;
  const startedMs = new Date(normalized).getTime();
  return Number.isFinite(startedMs) && Date.now() - startedMs < SYNC_STARTED_STALE_MS;
}

function nextSyncProgressPercent(current: number | undefined, elapsedMs: number): number {
  const baseline = current ?? 8;
  const elapsedSeconds = Math.max(0, elapsedMs / 1000);
  const target = Math.min(92, 8 + Math.log1p(elapsedSeconds) * 18);
  return Math.max(baseline, Math.round(target));
}

async function getResponseErrorMessage(response: Response, fallback: string): Promise<string> {
  const responseText = await response.text();
  if (!responseText) return fallback;

  try {
    const payload = JSON.parse(responseText) as { detail?: string; message?: string } | string;
    if (typeof payload === 'string' && payload.trim()) return payload;
    if (payload && typeof payload === 'object') {
      if (typeof payload.detail === 'string' && payload.detail.trim()) return payload.detail;
      if (typeof payload.message === 'string' && payload.message.trim()) return payload.message;
    }
  } catch {
    // Fall through to raw response text.
  }

  return responseText.trim() || fallback;
}

export function DataSources(): JSX.Element {
  // Get user/org from Zustand (auth state)
  const { user, organization, organizations } = useAppStore();
  const setCurrentView = useAppStore((state) => state.setCurrentView);

  const openTeamMembersPanel = useCallback((): void => {
    const orgHandle =
      organization?.handle ??
      (organization?.id
        ? organizations.find((orgMembership) => orgMembership.id === organization.id)?.handle ?? null
        : null);
    const settingsPath = orgHandle ? `/${orgHandle}/settings?tab=members` : '/settings?tab=members';
    window.history.pushState({}, '', settingsPath);
    setCurrentView('org-settings');
  }, [organization?.handle, organization?.id, organizations, setCurrentView]);
  const fetchUserOrganizations = useAppStore((state) => state.fetchUserOrganizations);
  

  // Zustand: Get integrations state
  const rawIntegrations = useIntegrations();
  const integrationsLoading = useIntegrationsLoading();
  const fetchIntegrations = useAppStore((state) => state.fetchIntegrations);

  // Fetch integrations when component mounts or user/org changes
  useEffect(() => {
    if (organization?.id && user?.id) {
      void fetchIntegrations();
    }
  }, [organization?.id, user?.id, fetchIntegrations]);

  useEffect(() => {
    if (user?.id) {
      void fetchUserOrganizations();
    }
  }, [user?.id, fetchUserOrganizations]);

  const [syncingProviders, setSyncingProviders] = useState<Set<string>>(new Set());
  const [syncStartedAt, setSyncStartedAt] = useState<Record<string, number>>({});
  const [syncProgress, setSyncProgress] = useState<Record<string, number>>({});
  const [syncProgressPercent, setSyncProgressPercent] = useState<Record<string, number>>({});
  const [syncStep, setSyncStep] = useState<Record<string, string>>({});
  /** True while org-wide "Sync all" is running (until all provider polls finish). */
  const [syncingAll, setSyncingAll] = useState<boolean>(false);

  // On mount/org change, check if any syncs are already in-flight (survives page reload)
  useEffect(() => {
    if (!organization?.id) return;
    const orgId: string = organization.id;
    const syncableProviders: string[] = rawIntegrations
      .filter((i) => i.isActive)
      .map((i) => i.provider);
    if (syncableProviders.length === 0) return;

    let cancelled = false;
    const checkInFlight = async (): Promise<void> => {
      const inFlight = new Set<string>();
      const authHeaders = await getAuthenticatedRequestHeaders();
      await Promise.all(
        syncableProviders.map(async (provider: string) => {
          try {
            const res: Response = await fetch(`${API_BASE}/sync/${orgId}/${provider}/status`, {
              headers: authHeaders,
            });
            if (!res.ok) return;
            const data = (await res.json()) as { status: string };
            if (data.status === 'syncing') {
              inFlight.add(provider);
            }
          } catch {
            // ignore — status check is best-effort
          }
        }),
      );
      if (!cancelled && inFlight.size > 0) {
        const now = Date.now();
        setSyncingProviders((prev) => {
          const next = new Set(prev);
          for (const p of inFlight) next.add(p);
          return next;
        });
        setSyncStartedAt((prev) => {
          const next = { ...prev };
          for (const p of inFlight) next[p] = next[p] ?? now;
          return next;
        });
        setSyncProgressPercent((prev) => {
          const next = { ...prev };
          for (const p of inFlight) next[p] = Math.max(next[p] ?? 0, 8);
          return next;
        });
      }
    };
    void checkInFlight();
    return () => { cancelled = true; };
  }, [organization?.id, rawIntegrations]);
  const [disconnectingProviders, setDisconnectingProviders] = useState<Set<string>>(new Set());
  const [connectingProvider, setConnectingProvider] = useState<string | null>(null);
  const [slackMappings, setSlackMappings] = useState<SlackUserMapping[]>([]);
  const [slackMappingsLoading, setSlackMappingsLoading] = useState(false);
  const [slackMappingsError, setSlackMappingsError] = useState<string | null>(null);
  const [slackEmailInput, setSlackEmailInput] = useState('');
  const [slackCodeInput, setSlackCodeInput] = useState('');
  const [slackMappingStatus, setSlackMappingStatus] = useState<string | null>(null);
  const [slackSendCodeLoading, setSlackSendCodeLoading] = useState<boolean>(false);
  const [slackVerifyCodeLoading, setSlackVerifyCodeLoading] = useState<boolean>(false);
  const [showSlackVerificationModal, setShowSlackVerificationModal] = useState(false);
  const [showConnectModal, setShowConnectModal] = useState(false);
  const [identityMappingProvider, setIdentityMappingProvider] = useState<'slack' | null>(null);
  const [connectSearch, setConnectSearch] = useState('');
  const [showCodeSandboxWarning, setShowCodeSandboxWarning] = useState(false);

  // MCP connect form state
  const [showMcpForm, setShowMcpForm] = useState(false);
  const [mcpName, setMcpName] = useState('');
  const [mcpEndpointUrl, setMcpEndpointUrl] = useState('');
  const [mcpBearerToken, setMcpBearerToken] = useState('');
  const [mcpConnecting, setMcpConnecting] = useState(false);
  const [mcpError, setMcpError] = useState<string | null>(null);

  // iSpot.tv connect form state (client credentials)
  const [showIspotForm, setShowIspotForm] = useState(false);
  const [ispotClientId, setIspotClientId] = useState('');
  const [ispotClientSecret, setIspotClientSecret] = useState('');
  const [ispotConnecting, setIspotConnecting] = useState(false);
  const [ispotError, setIspotError] = useState<string | null>(null);

  // Connectors from API (source of truth for Connect modal and display)
  const [connectorsFromApi, setConnectorsFromApi] = useState<ConnectorMetaFromApi[]>([]);
  const [connectorsLoading, setConnectorsLoading] = useState(true);
  const [connectorsError, setConnectorsError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    setConnectorsLoading(true);
    setConnectorsError(null);
    fetch(`${API_BASE}/connectors`)
      .then((res) => {
        if (!res.ok) throw new Error(res.statusText);
        return res.json() as Promise<ConnectorMetaFromApi[]>;
      })
      .then((data) => {
        if (!cancelled) setConnectorsFromApi(data);
      })
      .catch((err) => {
        if (!cancelled) setConnectorsError(err instanceof Error ? err.message : 'Failed to load connectors');
      })
      .finally(() => {
        if (!cancelled) setConnectorsLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  /** Resolve display config for a provider (use API + overlay, or fallback). */
  const getConnectorDisplay = useCallback((provider: string): IntegrationConfigEntry & { connection_flow?: 'oauth' | 'builtin' | 'custom_credentials'; default_sharing?: { shareSyncedData: boolean; shareQueryAccess: boolean; shareWriteAccess: boolean }; hasSync?: boolean } => {
    const baseSlug = provider.startsWith('mcp_') ? 'mcp' : provider;
    const fallback = INTEGRATION_CONFIG_FALLBACK[baseSlug] ?? INTEGRATION_CONFIG_FALLBACK[provider];
    const apiConnector = connectorsFromApi.find((c) => c.slug === baseSlug);
    const override = CONNECTOR_DISPLAY_OVERRIDE[baseSlug] ?? CONNECTOR_DISPLAY_OVERRIDE[provider];
    if (apiConnector) {
      const icon = override?.icon ?? (apiConnector.icon || DEFAULT_ICON);
      const color = override?.color ?? DEFAULT_COLOR;
      return {
        name: apiConnector.name,
        description: apiConnector.description,
        icon,
        color,
        scope: apiConnector.scope,
        connection_flow: apiConnector.connection_flow,
        default_sharing: {
          shareSyncedData: apiConnector.default_sharing.share_synced_data,
          shareQueryAccess: apiConnector.default_sharing.share_query_access,
          shareWriteAccess: apiConnector.default_sharing.share_write_access,
        },
        hasSync: apiConnector.capabilities.includes('sync'),
      };
    }
    if (fallback) {
      return {
        ...fallback,
        default_sharing: { shareSyncedData: false, shareQueryAccess: false, shareWriteAccess: false },
        hasSync: true,
      };
    }
    return {
      name: provider,
      description: '',
      icon: DEFAULT_ICON,
      color: DEFAULT_COLOR,
      scope: 'user',
      default_sharing: { shareSyncedData: false, shareQueryAccess: false, shareWriteAccess: false },
      hasSync: false,
    };
  }, [connectorsFromApi]);

  /** Whether a provider is supported for display (in API list or mcp_* or fallback). */
  const isSupportedProvider = useCallback((provider: string): boolean => {
    if (provider.startsWith('mcp_')) return true;
    if (connectorsFromApi.length > 0) return connectorsFromApi.some((c) => c.slug === provider);
    return Object.prototype.hasOwnProperty.call(INTEGRATION_CONFIG_FALLBACK, provider) || (provider.startsWith('mcp_') && Object.prototype.hasOwnProperty.call(INTEGRATION_CONFIG_FALLBACK, 'mcp'));
  }, [connectorsFromApi]);

  // GitHub: available repos (from token), tracked repo ids, selection, loading
  interface GitHubRepo {
    github_repo_id: number;
    owner: string;
    name: string;
    full_name: string;
    description?: string;
    default_branch: string;
    is_private: boolean;
    language?: string;
    url: string;
  }
  const [githubAvailableRepos, setGithubAvailableRepos] = useState<GitHubRepo[]>([]);
  const [githubTrackedIds, setGithubTrackedIds] = useState<Set<number>>(new Set());
  const [githubTrackedNames, setGithubTrackedNames] = useState<string[]>([]);
  const [githubReposLoading, setGithubReposLoading] = useState(false);
  const [githubReposError, setGithubReposError] = useState<string | null>(null);
  const [githubSelectedIds, setGithubSelectedIds] = useState<Set<number>>(new Set());
  const [githubSaving, setGithubSaving] = useState(false);
  const [githubReposExpanded, setGithubReposExpanded] = useState(false);
  const [githubRequiresRepoReview, setGithubRequiresRepoReview] = useState(false);
  const [githubAutoScrollPending, setGithubAutoScrollPending] = useState(false);
  const connectorCardRefs = useRef<Record<string, HTMLLIElement | null>>({});
  
  // Live sync progress is tracked near syncingProviders so reload recovery can seed the same state.

  // Sharing modal state
  interface SharingModalState {
    isOpen: boolean;
    integrationId: string;
    provider: string;
    providerName: string;
    shareSyncedData: boolean;
    shareQueryAccess: boolean;
    shareWriteAccess: boolean;
    isInitialSetup: boolean;  // true = post-OAuth, false = editing existing
    initiallySharedWithTeam: boolean;
  }
  const [sharingModal, setSharingModal] = useState<SharingModalState | null>(null);
  const [sharingSaving, setSharingSaving] = useState(false);
  const [calendarSharingWarningOpen, setCalendarSharingWarningOpen] = useState(false);

  // Disconnect confirmation modal state
  interface DisconnectModalState {
    provider: string;
    step: 'confirm' | 'ask-delete';
  }
  const [disconnectModal, setDisconnectModal] = useState<DisconnectModalState | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);
  /** Which integration row id has the overflow menu open (null = closed). */
  const [rowMenuOpenForId, setRowMenuOpenForId] = useState<string | null>(null);
  /** Provider slug for slide-out detail drawer (null = closed). */
  const [detailProvider, setDetailProvider] = useState<string | null>(null);
  /** Desktop header page overflow (Sync all, mobile-only helpers). */
  const [pageOverflowOpen, setPageOverflowOpen] = useState<boolean>(false);
  const [disconnectError, setDisconnectError] = useState<string | null>(null);
  const [disconnectSuccess, setDisconnectSuccess] = useState<string | null>(null);
  const [sharingError, setSharingError] = useState<string | null>(null);

  const organizationId = organization?.id ?? '';
  const userId = user?.id ?? '';
  const activeMembership = organizations.find((org) => org.id === organizationId);
  const canConnectCodeSandbox = (user?.roles.includes('global_admin') ?? false) || activeMembership?.role === 'admin';
  const canSyncAllConnectors: boolean = useMemo((): boolean => {
    const isGlobalAdmin: boolean = user?.roles.includes('global_admin') ?? false;
    if (isGlobalAdmin) return true;
    return activeMembership?.role === 'admin';
  }, [user?.roles, activeMembership?.role]);

  useEffect(() => {
    if (rowMenuOpenForId === null) return;
    const onPointerDown = (e: PointerEvent): void => {
      const t = e.target as HTMLElement | null;
      if (t?.closest('[data-row-menu-root]')) return;
      setRowMenuOpenForId(null);
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [rowMenuOpenForId]);

  useEffect(() => {
    if (detailProvider === null) return;
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') setDetailProvider(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [detailProvider]);

  useEffect(() => {
    if (!pageOverflowOpen) return;
    const onPointerDown = (e: PointerEvent): void => {
      const t = e.target as HTMLElement | null;
      if (t?.closest('[data-page-overflow-root]')) return;
      setPageOverflowOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [pageOverflowOpen]);

  const connectBuiltinConnector = useCallback(
    async (
      provider: string,
      extraData?: Record<string, unknown> | null,
    ): Promise<void> => {
      const { data, error } = await apiRequest<{ status: string; provider: string }>(
        '/auth/integrations/connect-builtin',
        {
          method: 'POST',
          body: JSON.stringify({
            organization_id: organizationId,
            provider,
            user_id: userId,
            ...(extraData ? { extra_data: extraData } : {}),
          }),
        },
      );
      if (error || !data) {
        throw new Error(error ?? 'Failed to connect');
      }
    },
    [organizationId, userId],
  );

  const slackIntegration = rawIntegrations.find((integration) => integration.provider === 'slack');
  const slackConnected = Boolean(slackIntegration?.isActive);

  const githubIntegration = rawIntegrations.find((integration) => integration.provider === 'github');
  const githubConnected = Boolean(githubIntegration?.isActive);
  const githubCurrentUserConnected = rawIntegrations.some(
    (integration) => integration.provider === 'github' && integration.isActive && integration.currentUserConnected,
  );

  const markProviderSyncing = useCallback((provider: string): void => {
    const now = Date.now();
    setSyncingProviders((prev) => new Set(prev).add(provider));
    setSyncStartedAt((prev) => ({ ...prev, [provider]: prev[provider] ?? now }));
    setSyncProgressPercent((prev) => ({ ...prev, [provider]: Math.max(prev[provider] ?? 0, 8) }));
  }, []);

  const finishProviderSync = useCallback((provider: string): void => {
    setSyncProgressPercent((prev) => ({ ...prev, [provider]: 100 }));
    setTimeout(() => {
      setSyncProgress((prev) => {
        const next = { ...prev };
        delete next[provider];
        return next;
      });
      setSyncProgressPercent((prev) => {
        const next = { ...prev };
        delete next[provider];
        return next;
      });
      setSyncStep((prev) => {
        const next = { ...prev };
        delete next[provider];
        return next;
      });
      setSyncStartedAt((prev) => {
        const next = { ...prev };
        delete next[provider];
        return next;
      });
      setSyncingProviders((prev) => {
        const next = new Set(prev);
        next.delete(provider);
        return next;
      });
    }, SYNC_PROGRESS_COMPLETE_HOLD_MS);
  }, []);

  useEffect(() => {
    if (syncingProviders.size === 0) return;

    const interval = window.setInterval(() => {
      const now = Date.now();
      setSyncProgressPercent((prev) => {
        let changed = false;
        const next = { ...prev };
        for (const provider of syncingProviders) {
          const startedAt = syncStartedAt[provider] ?? now;
          const progress = nextSyncProgressPercent(next[provider], now - startedAt);
          if (next[provider] !== progress) {
            next[provider] = progress;
            changed = true;
          }
        }
        return changed ? next : prev;
      });
    }, 1000);

    return () => window.clearInterval(interval);
  }, [syncingProviders, syncStartedAt]);
  
  // Handle WebSocket messages for sync progress
  const handleWsMessage = useCallback((message: string) => {
    try {
      const data = JSON.parse(message) as {
        type: string;
        provider?: string;
        count?: number;
        status?: string;
        step?: string;
      };
      if (data.type !== 'sync_progress' || data.provider === undefined) return;

      const provider = data.provider;
      if (typeof data.count === 'number' && Number.isFinite(data.count)) {
        setSyncProgress((prev) => ({
          ...prev,
          [provider]: Math.max(prev[provider] ?? 0, data.count ?? 0),
        }));
      }
      if (data.step) {
        setSyncStep((prev) => ({
          ...prev,
          [provider]: data.step as string,
        }));
      }

      if (data.status === 'syncing') {
        markProviderSyncing(provider);
      }

      if (data.status === 'completed' || data.status === 'failed') {
        void fetchIntegrations();
        finishProviderSync(provider);
      }
    } catch {
      // Ignore non-JSON messages or parsing errors
    }
  }, [fetchIntegrations, finishProviderSync, markProviderSyncing]);
  
  // Connect to WebSocket for sync progress updates - authenticated via JWT token
  useWebSocket(
    userId ? '/ws/chat' : '',
    {
      onMessage: handleWsMessage,
    },
    organizationId || undefined,
  );

  const fetchSlackMappings = useCallback(async (): Promise<void> => {
    if (!organizationId || !userId) return;
    setSlackMappingsLoading(true);
    setSlackMappingsError(null);
    try {
      const params = new URLSearchParams({ organization_id: organizationId, user_id: userId });
      const headers = await getAuthenticatedRequestHeaders();
      const response = await fetch(`${API_BASE}/slack/user-mappings?${params.toString()}`, {
        headers,
      });
      if (!response.ok) {
        throw new Error(`Failed to load Slack mappings: ${response.status}`);
      }
      const data = (await response.json()) as { mappings: SlackUserMapping[] };
      const mappingsFromIdentityTable = data.mappings
        .map((mapping) => ({
          id: mapping.id,
          external_userid: mapping.external_userid,
          external_email: mapping.external_email,
          source: mapping.source,
          match_source: mapping.match_source,
          created_at: mapping.created_at,
        }))
        .filter((mapping) => mapping.source.toLowerCase().includes('slack'));
      setSlackMappings(mappingsFromIdentityTable);
    } catch (error) {
      console.error('[DataSources] Failed to load Slack mappings:', error);
      setSlackMappingsError(error instanceof Error ? error.message : 'Unknown error');
    } finally {
      setSlackMappingsLoading(false);
    }
  }, [organizationId, userId]);

  useEffect(() => {
    if (slackConnected) {
      void fetchSlackMappings();
    }
  }, [fetchSlackMappings, slackConnected]);

  const fetchGitHubAvailableRepos = useCallback(async (): Promise<void> => {
    if (!organizationId) return;
    setGithubReposLoading(true);
    setGithubReposError(null);
    try {
      const headers = await getAuthenticatedRequestHeaders();
      const res = await fetch(`${API_BASE}/sync/${organizationId}/github/repos`, { headers });
      if (!res.ok) throw new Error(`Failed to load repos: ${res.status}`);
      const data = (await res.json()) as { repos: GitHubRepo[] };
      setGithubAvailableRepos(data.repos ?? []);
    } catch (e) {
      setGithubReposError(e instanceof Error ? e.message : 'Failed to load repos');
      setGithubAvailableRepos([]);
    } finally {
      setGithubReposLoading(false);
    }
  }, [organizationId]);

  const fetchGitHubTrackedRepos = useCallback(async (): Promise<void> => {
    if (!organizationId) return;
    try {
      const headers = await getAuthenticatedRequestHeaders();
      const res = await fetch(`${API_BASE}/sync/${organizationId}/github/repos/tracked`, { headers });
      if (!res.ok) return;
      const data = (await res.json()) as { repos: { github_repo_id: number; full_name?: string }[] };
      const repos = data.repos ?? [];
      const ids = new Set(repos.map((r) => r.github_repo_id));
      setGithubTrackedIds(ids);
      setGithubSelectedIds(ids);
      setGithubTrackedNames(repos.map((r) => r.full_name ?? '').filter(Boolean));
    } catch {
      setGithubTrackedIds(new Set());
      setGithubSelectedIds(new Set());
      setGithubTrackedNames([]);
    }
  }, [organizationId]);

  useEffect(() => {
    if (githubCurrentUserConnected && organizationId) {
      void fetchGitHubAvailableRepos();
      void fetchGitHubTrackedRepos();
    }
  }, [githubCurrentUserConnected, organizationId, fetchGitHubAvailableRepos, fetchGitHubTrackedRepos]);

  useEffect(() => {
    if (!githubConnected) {
      setGithubRequiresRepoReview(false);
      setGithubReposExpanded(false);
    }
  }, [githubConnected]);

  const handleGitHubTrackRepos = useCallback(async (): Promise<void> => {
    if (!organizationId || githubSaving) return;
    setGithubSaving(true);
    setGithubReposError(null);
    try {
      const authHeaders = await getAuthenticatedRequestHeaders();
      const res = await fetch(`${API_BASE}/sync/${organizationId}/github/repos/track`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders },
        body: JSON.stringify({ github_repo_ids: Array.from(githubSelectedIds) }),
      });
      if (!res.ok) {
        const err = (await res.json()) as { detail?: string };
        throw new Error(err.detail ?? `Failed to save: ${res.status}`);
      }
      await fetchGitHubTrackedRepos();
      void fetchIntegrations();
      setGithubReposExpanded(false);
      setGithubRequiresRepoReview(false);
    } catch (e) {
      setGithubReposError(e instanceof Error ? e.message : 'Failed to save');
    } finally {
      setGithubSaving(false);
    }
  }, [organizationId, githubSelectedIds, githubSaving, fetchGitHubTrackedRepos, fetchIntegrations]);

  // Transform raw integrations to display integrations with UI metadata
  // Filter out raw "microsoft" integration - it's a meta-integration from Nango's OAuth.
  // The actual data sources are microsoft_calendar and microsoft_mail.
  const integrations: DisplayIntegration[] = rawIntegrations
    .filter((integration) => {
      if (integration.provider === 'microsoft') {
        return false;
      }
      if (!isSupportedProvider(integration.provider)) {
        console.warn('[DataSources] Hiding unsupported integration provider from UI:', integration.provider);
        return false;
      }
      return true;
    })
    .map((integration) => {
      const config = getConnectorDisplay(integration.provider);
      const name: string = integration.displayName ?? config.name;
      return {
        ...integration,
        name,
        description: config.description,
        icon: config.icon,
        color: config.color,
        scope: config.scope,
        connected: integration.isActive,
      };
    });

  // Also include available (not connected) integrations
  const connectedProviders = new Set(integrations.map((i) => i.provider));
  const connectorSlugs = connectorsFromApi.length > 0
    ? connectorsFromApi.map((c) => c.slug)
    : Object.keys(INTEGRATION_CONFIG_FALLBACK);
  const availableProviders = connectorSlugs.filter((p) => !connectedProviders.has(p));
  const availableIntegrationsDisplay: DisplayIntegration[] = availableProviders.map((provider) => {
    const config = getConnectorDisplay(provider);
    const defaults = config.default_sharing ?? { shareSyncedData: false, shareQueryAccess: false, shareWriteAccess: false };
    return {
      id: provider,
      provider,
      userId: null,
      isActive: false,
      lastSyncAt: null,
      lastError: null,
      connectedAt: null,
      connectedBy: null,
      scope: config.scope,
      currentUserConnected: false,
      teamConnections: [],
      teamTotal: 0,
      syncStats: null,
      displayName: null,
      shareSyncedData: defaults.shareSyncedData,
      shareQueryAccess: defaults.shareQueryAccess,
      shareWriteAccess: defaults.shareWriteAccess,
      pendingSharingConfig: false,
      isOwner: false,
      name: config.name,
      description: config.description,
      icon: config.icon,
      color: config.color,
      connected: false,
    };
  });
  const allIntegrations: DisplayIntegration[] = [...integrations, ...availableIntegrationsDisplay];

  useEffect(() => {
    if (!githubAutoScrollPending || !githubReposExpanded) return;
    const githubCard = connectorCardRefs.current.github;
    if (!githubCard) return;
    githubCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
    setGithubAutoScrollPending(false);
  }, [allIntegrations.length, githubAutoScrollPending, githubReposExpanded]);

  // Full list of all connectors for the add-connector modal (from API or fallback)
  const allConnectorsForModal: DisplayIntegration[] = connectorSlugs.map((provider: string): DisplayIntegration => {
    const config = getConnectorDisplay(provider);
    const defaults = config.default_sharing ?? { shareSyncedData: false, shareQueryAccess: false, shareWriteAccess: false };
    return {
      id: provider,
      provider,
      userId: null,
      isActive: false,
      lastSyncAt: null,
      lastError: null,
      connectedAt: null,
      connectedBy: null,
      scope: config.scope,
      currentUserConnected: false,
      teamConnections: [],
      teamTotal: 0,
      syncStats: null,
      displayName: null,
      shareSyncedData: defaults.shareSyncedData,
      shareQueryAccess: defaults.shareQueryAccess,
      shareWriteAccess: defaults.shareWriteAccess,
      pendingSharingConfig: false,
      isOwner: false,
      name: config.name,
      description: config.description,
      icon: config.icon,
      color: config.color,
      connected: false,
    };
  });

  const connectProvider = useCallback(async (provider: string): Promise<void> => {
    if (connectingProvider || !organizationId || !userId) return;

    setConnectingProvider(provider);

    try {
      const connectionFlow = getConnectorDisplay(provider).connection_flow;
      if (connectionFlow === 'custom_credentials') {
        setConnectingProvider(null);
        if (provider === 'mcp') {
          setMcpName('');
          setMcpEndpointUrl('');
          setMcpBearerToken('');
          setMcpError(null);
          setShowMcpForm(true);
        } else if (provider === 'ispot_tv') {
          setIspotClientId('');
          setIspotClientSecret('');
          setIspotError(null);
          setShowIspotForm(true);
        } else {
          // Unknown custom_credentials provider — the classifier should only
          // route mcp/ispot_tv here. Surface loudly instead of silently no-op'ing.
          console.error(`[DataSources] No custom_credentials form registered for provider "${provider}"`);
          throw new Error(`Connector "${provider}" is mis-configured: no credential form is registered.`);
        }
        return;
      }

      if (connectionFlow === 'builtin') {
        if (provider === 'code_sandbox' && !canConnectCodeSandbox) {
          throw new Error('Code Sandbox can only be connected by organization admins or global admins');
        }
        await connectBuiltinConnector(provider);
        void fetchIntegrations();
        setConnectingProvider(null);
        return;
      }

      // Get session token from backend for OAuth connectors (JWT + org header)
      const connectAuthHeaders = await getAuthenticatedRequestHeaders();
      const response = await fetch(`${API_BASE}/auth/connect/${provider}/session`, {
        headers: connectAuthHeaders,
      });

      if (!response.ok) {
        throw new Error('Failed to get session token');
      }

      const data: { session_token: string; connection_id: string } = await response.json();
      const { session_token, connection_id } = data;

      // Initialize Nango and open connect UI in popup
      const nango = new Nango();

      nango.openConnectUI({
        sessionToken: session_token,
        onEvent: async (event) => {
          // Handle different possible event types from Nango
          const eventType = event.type as string;
          if (
            eventType === 'connect' ||
            eventType === 'connection-created' ||
            eventType === 'success'
          ) {
            // Connection successful - confirm and create integration record
            const eventData = event as { type: string; connectionId?: string; connection_id?: string; payload?: { connectionId?: string } };
            const nangoConnectionId = eventData.connectionId || eventData.connection_id || eventData.payload?.connectionId || connection_id;

            const shouldDeferSync: boolean = provider === "slack" || provider === "github";
            try {
              const confirmResponse = await fetch(`${API_BASE}/auth/integrations/confirm`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  provider,
                  connection_id: nangoConnectionId,
                  organization_id: organizationId,
                  user_id: userId,
                  skip_initial_sync: shouldDeferSync,
                }),
              });

              if (!confirmResponse.ok) {
                console.error('Failed to confirm integration:', await confirmResponse.text());
                void fetchIntegrations();
                setConnectingProvider(null);
                return;
              }

              await confirmResponse.json();
              await fetchIntegrations();

              if (provider === "slack") {
                setIdentityMappingProvider("slack");
              }
              if (provider === 'github') {
                setGithubReposExpanded(true);
                setGithubRequiresRepoReview(true);
                setGithubAutoScrollPending(true);
              }
            } catch (confirmError) {
              console.error('Error confirming integration:', confirmError);
            }

            setConnectingProvider(null);
          } else if (eventType === 'close' || eventType === 'closed') {
            // User closed the popup
            setConnectingProvider(null);
          }
        },
      });
    } catch (error) {
      console.error('Failed to connect:', error);
      setConnectingProvider(null);
    }
  }, [canConnectCodeSandbox, connectBuiltinConnector, connectingProvider, fetchIntegrations, getConnectorDisplay, organizationId, userId]);

  const handleConnect = useCallback(async (provider: string): Promise<void> => {
    if (provider === 'code_sandbox') {
      if (!canConnectCodeSandbox) {
        console.warn('[DataSources] Blocked non-admin Code Sandbox connection attempt');
        return;
      }
      setShowCodeSandboxWarning(true);
      return;
    }

    await connectProvider(provider);
  }, [canConnectCodeSandbox, connectProvider]);

  const handleConfirmCodeSandboxConnect = useCallback(async (): Promise<void> => {
    setShowCodeSandboxWarning(false);
    await connectProvider('code_sandbox');
  }, [connectProvider]);

  const handleMcpConnect = useCallback(async (): Promise<void> => {
    if (!organizationId || !userId || mcpConnecting) return;
    const trimmedUrl: string = mcpEndpointUrl.trim();
    const trimmedName: string = mcpName.trim();
    if (!trimmedName) {
      setMcpError('Name is required');
      return;
    }
    if (!trimmedUrl) {
      setMcpError('Endpoint URL is required');
      return;
    }

    setMcpConnecting(true);
    setMcpError(null);
    try {
      await connectBuiltinConnector('mcp', {
        display_name: trimmedName,
        endpoint_url: trimmedUrl,
        auth_header: mcpBearerToken.trim() || null,
      });
      setShowMcpForm(false);
      void fetchIntegrations();
    } catch (error) {
      setMcpError(error instanceof Error ? error.message : 'Failed to connect');
    } finally {
      setMcpConnecting(false);
    }
  }, [connectBuiltinConnector, fetchIntegrations, mcpBearerToken, mcpConnecting, mcpEndpointUrl, mcpName, organizationId, userId]);

  const handleIspotConnect = useCallback(async (): Promise<void> => {
    if (!organizationId || !userId || ispotConnecting) return;
    const clientId: string = ispotClientId.trim();
    const clientSecret: string = ispotClientSecret.trim();
    if (!clientId) {
      setIspotError('Client ID is required');
      return;
    }
    if (!clientSecret) {
      setIspotError('Client Secret is required');
      return;
    }
    setIspotConnecting(true);
    setIspotError(null);
    try {
      await connectBuiltinConnector('ispot_tv', { client_id: clientId, client_secret: clientSecret });
      setShowIspotForm(false);
      void fetchIntegrations();
    } catch (error) {
      setIspotError(error instanceof Error ? error.message : 'Failed to connect');
    } finally {
      setIspotConnecting(false);
    }
  }, [connectBuiltinConnector, fetchIntegrations, ispotClientId, ispotClientSecret, ispotConnecting, organizationId, userId]);

  const handleDisconnect = (provider: string): void => {
    if (!organizationId || !userId || disconnectingProviders.has(provider)) return;
    setSyncError(null);
    setDisconnectError(null);
    setDisconnectModal({ provider, step: 'confirm' });
  };

  const executeDisconnect = async (provider: string, deleteData: boolean): Promise<void> => {
    setDisconnectModal(null);

    // Set disconnecting state immediately for instant UI feedback
    setDisconnectingProviders((prev) => new Set(prev).add(provider));

    const params = new URLSearchParams({ organization_id: organizationId, user_id: userId });
    if (deleteData) {
      params.set('delete_data', 'true');
    }
    const url = `${API_BASE}/auth/integrations/${provider}?${params.toString()}`;

    try {
      const response = await fetch(url, { method: 'DELETE' });
      const responseText = await response.text();

      if (!response.ok) {
        let message = `Failed to disconnect ${getConnectorDisplay(provider).name}`;
        if (responseText) {
          try {
            const payload = JSON.parse(responseText) as { detail?: string; message?: string } | string;
            if (typeof payload === 'string' && payload.trim()) {
              message = payload;
            } else if (payload && typeof payload === 'object') {
              message = payload.detail ?? payload.message ?? message;
            }
          } catch {
            message = responseText;
          }
        }
        throw new Error(message);
      }

      // Parse response to show deletion summary
      try {
        const data = JSON.parse(responseText) as {
          deleted_activities?: number;
          deleted_contacts?: number;
          deleted_accounts?: number;
          deleted_deals?: number;
          deleted_goals?: number;
          deleted_pipelines?: number;
          deleted_meetings?: number;
        };
        const counts: string[] = [];
        if (data.deleted_activities)  counts.push(`${data.deleted_activities} activities`);
        if (data.deleted_deals)       counts.push(`${data.deleted_deals} deals`);
        if (data.deleted_contacts)    counts.push(`${data.deleted_contacts} contacts`);
        if (data.deleted_accounts)    counts.push(`${data.deleted_accounts} accounts`);
        if (data.deleted_goals)       counts.push(`${data.deleted_goals} goals`);
        if (data.deleted_pipelines)   counts.push(`${data.deleted_pipelines} pipelines`);
        if (data.deleted_meetings)    counts.push(`${data.deleted_meetings} orphaned meetings`);

        if (counts.length > 0) {
          setDisconnectSuccess(`Disconnected ${provider}. Deleted ${counts.join(', ')}.`);
          setTimeout(() => setDisconnectSuccess(null), 6000);
        }
      } catch {
        // Response wasn't JSON or didn't have deletion info, that's fine
      }

      try {
        await fetchIntegrations();
      } catch (fetchError) {
        console.error('Failed to refresh integrations after disconnect:', fetchError);
      }
      setDisconnectingProviders((prev) => {
        if (!prev.has(provider)) return prev;
        const next = new Set(prev);
        next.delete(provider);
        return next;
      });
    } catch (error) {
      console.error('Failed to disconnect:', error);
      setDisconnectError(`Failed to disconnect: ${error instanceof Error ? error.message : 'Unknown error'}`);
      setTimeout(() => setDisconnectError(null), 6000);
      setDisconnectingProviders((prev) => {
        const next = new Set(prev);
        next.delete(provider);
        return next;
      });
    }
  };

  // Save sharing preferences (POST for initial setup, PATCH for updates)
  const persistSharingSettings = async (): Promise<void> => {
    if (!sharingModal || sharingSaving) return;

    setSharingSaving(true);
    try {
      const endpoint = sharingModal.isInitialSetup
        ? `${API_BASE}/auth/integrations/${sharingModal.integrationId}/sharing`
        : `${API_BASE}/auth/integrations/${sharingModal.integrationId}/sharing`;
      const method = sharingModal.isInitialSetup ? 'POST' : 'PATCH';

      const params = userId ? new URLSearchParams({ user_id: userId }) : '';
      const response = await fetch(`${endpoint}?${params}`, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          share_synced_data: sharingModal.shareSyncedData,
          share_query_access: sharingModal.shareQueryAccess,
          share_write_access: sharingModal.shareWriteAccess,
        }),
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: response.statusText }));
        throw new Error((err as { detail?: string }).detail ?? 'Failed to save sharing settings');
      }

      setSharingModal(null);
      void fetchIntegrations();
    } catch (error) {
      console.error('Failed to save sharing settings:', error);
      setSharingError(`Failed to save: ${error instanceof Error ? error.message : 'Unknown error'}`);
      setTimeout(() => setSharingError(null), 6000);
    } finally {
      setSharingSaving(false);
    }
  };

  const shouldShowCalendarSharingWarning = (): boolean => {
    if (!sharingModal) return false;
    if (!CALENDAR_SHARING_WARNING_PROVIDERS.has(sharingModal.provider)) return false;
    if (sharingModal.initiallySharedWithTeam) return false;
    return isSharedWithTeam(sharingModal);
  };

  const handleSaveSharing = async (): Promise<void> => {
    if (sharingSaving) return;
    if (shouldShowCalendarSharingWarning()) {
      setCalendarSharingWarningOpen(true);
      return;
    }
    await persistSharingSettings();
  };

  const handleConfirmCalendarSharingWarning = async (): Promise<void> => {
    setCalendarSharingWarningOpen(false);
    await persistSharingSettings();
  };

  // Open sharing modal for editing an existing integration
  const handleOpenSharingSettings = (integration: DisplayIntegration): void => {
    setSharingModal({
      isOpen: true,
      integrationId: integration.id,
      provider: integration.provider,
      providerName: integration.name,
      shareSyncedData: integration.shareSyncedData,
      shareQueryAccess: integration.shareQueryAccess,
      shareWriteAccess: integration.shareWriteAccess,
      isInitialSetup: false,
      initiallySharedWithTeam: isSharedWithTeam(integration),
    });
  };

  const handleSync = async (provider: string, sinceIso?: string): Promise<void> => {
    if (syncingProviders.has(provider) || !organizationId) return;
    if (provider === 'github' && githubRequiresRepoReview) {
      setGithubReposExpanded(true);
      setSyncError('Select and save GitHub repositories before syncing.');
      setTimeout(() => setSyncError(null), 8000);
      return;
    }

    setSyncError(null);
    markProviderSyncing(provider);

    try {
      // Google Drive uses its own sync endpoint (user-scoped)
      if (provider === 'google_drive') {
        const params = new URLSearchParams({ organization_id: organizationId, user_id: userId });
        const { error } = await apiRequest<{ status: string; message: string }>(`/drive/sync?${params.toString()}`, { method: 'POST' });
        if (error) throw new Error(error);
        // Drive sync runs in background — wait a bit then refresh integrations
        setTimeout(() => {
          finishProviderSync(provider);
          void fetchIntegrations();
        }, 15000);
        return;
      }

      const syncUrl: string =
        sinceIso !== undefined && sinceIso.length > 0
          ? `${API_BASE}/sync/${organizationId}/${provider}?since=${encodeURIComponent(sinceIso)}`
          : `${API_BASE}/sync/${organizationId}/${provider}`;

      const authHeaders = await getAuthenticatedRequestHeaders();
      const response = await fetch(syncUrl, {
        method: 'POST',
        headers: authHeaders,
      });

      if (!response.ok) throw new Error(await getResponseErrorMessage(response, `Failed to sync ${getConnectorDisplay(provider).name}`));

      // Poll for completion (GitHub sync can take 1–2 min; allow 2.5 min)
      let attempts = 0;
      const maxAttempts = 150;
      const checkStatus = async (): Promise<void> => {
        const statusRes = await fetch(`${API_BASE}/sync/${organizationId}/${provider}/status`, {
          headers: authHeaders,
        });
        const status = await statusRes.json();

        if (status.status === 'completed' || status.status === 'failed' || attempts >= maxAttempts) {
          finishProviderSync(provider);

          if (status.status === 'failed') {
            const providerName = getConnectorDisplay(provider).name;
            const detail = typeof status.error === 'string' && status.error.trim() ? status.error : `Failed to sync ${providerName}`;
            setSyncError(detail);
            setTimeout(() => setSyncError(null), 8000);
          }

          // Always refetch: on completion, failure, or timeout (slow syncs like GitHub can exceed 30s)
          void fetchIntegrations();
          // If we timed out, sync may still be running; refetch again after delay to pick up result
          if (attempts >= maxAttempts) {
            setTimeout(() => void fetchIntegrations(), 60000);
          }
        } else {
          attempts++;
          setTimeout(() => void checkStatus(), 2000);
        }
      };

      void checkStatus();
    } catch (error) {
      console.error('Sync error:', error);
      setSyncError(error instanceof Error ? error.message : `Failed to sync ${getConnectorDisplay(provider).name}`);
      setTimeout(() => setSyncError(null), 8000);
      finishProviderSync(provider);
    }
  };

  const handleSyncAll = useCallback(async (): Promise<void> => {
    if (!organizationId || !canSyncAllConnectors || syncingAll) return;
    if (githubRequiresRepoReview) {
      setGithubReposExpanded(true);
      setSyncError('Review and save your GitHub repository selection before running Sync All.');
      setTimeout(() => setSyncError(null), 8000);
      return;
    }

    setSyncError(null);
    setSyncingAll(true);

    const syncAllAuthHeaders = await getAuthenticatedRequestHeaders();

    const { data, error } = await apiRequest<{
      status: string;
      organization_id: string;
      integrations: string[];
    }>(`/sync/${organizationId}/all`, { method: 'POST' });

    if (error !== null || data === null) {
      setSyncError(error ?? 'Failed to start sync');
      setTimeout(() => setSyncError(null), 8000);
      setSyncingAll(false);
      return;
    }

    const providers: readonly string[] = data.integrations;
    if (providers.length === 0) {
      setSyncingAll(false);
      return;
    }

    for (const provider of providers) {
      markProviderSyncing(provider);
    }

    const maxAttempts: number = 150;
    const pollOne = async (provider: string): Promise<void> => {
      let attempts: number = 0;
      for (;;) {
        const statusRes: Response = await fetch(`${API_BASE}/sync/${organizationId}/${provider}/status`, {
          headers: syncAllAuthHeaders,
        });
        const status: { status: string; error?: string } = (await statusRes.json()) as {
          status: string;
          error?: string;
        };
        if (status.status === 'completed' || status.status === 'failed' || attempts >= maxAttempts) {
          finishProviderSync(provider);
          if (status.status === 'failed') {
            const providerName: string = getConnectorDisplay(provider).name;
            const detail: string =
              typeof status.error === 'string' && status.error.trim().length > 0
                ? status.error
                : `Failed to sync ${providerName}`;
            setSyncError(detail);
            setTimeout(() => setSyncError(null), 8000);
          }
          return;
        }
        attempts += 1;
        await new Promise<void>((resolve) => {
          setTimeout(resolve, 2000);
        });
      }
    };

    await Promise.all(providers.map((p: string) => pollOne(p)));
    void fetchIntegrations();
    setSyncingAll(false);
  }, [
    organizationId,
    canSyncAllConnectors,
    syncingAll,
    githubRequiresRepoReview,
    fetchIntegrations,
    getConnectorDisplay,
    finishProviderSync,
    markProviderSyncing,
  ]);

  const handleSlackRequestCode = async (): Promise<void> => {
    if (!organizationId || !userId || !slackEmailInput.trim()) return;
    setSlackMappingStatus(null);
    setSlackSendCodeLoading(true);
    try {
      const slackAuthHeaders = await getAuthenticatedRequestHeaders();
      const response = await fetch(`${API_BASE}/slack/user-mappings/request-code`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...slackAuthHeaders },
        body: JSON.stringify({
          user_id: userId,
          organization_id: organizationId,
          email: slackEmailInput.trim(),
        }),
      });
      if (!response.ok) {
        let message = `Failed to send code: ${response.status}`;
        try {
          const data = await response.json();
          if (data && typeof data.detail === 'string') {
            message = data.detail;
          } else if (typeof data === 'string') {
            message = data;
          }
        } catch {
          const text = await response.text();
          if (text) message = text;
        }
        throw new Error(message);
      }
      setSlackMappingStatus('Verification code sent via Slack DM.');
    } catch (error) {
      console.error('[DataSources] Failed to request Slack code:', error);
      setSlackMappingStatus(
        error instanceof Error ? error.message : 'Failed to send verification code.',
      );
    } finally {
      setSlackSendCodeLoading(false);
    }
  };

  const handleSlackVerifyCode = async (): Promise<void> => {
    if (!organizationId || !userId || !slackEmailInput.trim() || !slackCodeInput.trim()) return;
    setSlackMappingStatus(null);
    setSlackVerifyCodeLoading(true);
    try {
      const slackVerifyHeaders = await getAuthenticatedRequestHeaders();
      const response = await fetch(`${API_BASE}/slack/user-mappings/verify-code`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...slackVerifyHeaders },
        body: JSON.stringify({
          user_id: userId,
          organization_id: organizationId,
          email: slackEmailInput.trim(),
          code: slackCodeInput.trim(),
        }),
      });
      if (!response.ok) {
        let message = `Failed to verify code: ${response.status}`;
        try {
          const data = await response.json();
          if (data && typeof data.detail === 'string') {
            message = data.detail;
          } else if (typeof data === 'string') {
            message = data;
          }
        } catch {
          const text = await response.text();
          if (text) message = text;
        }
        throw new Error(message);
      }
      setSlackMappingStatus('Slack account connected.');
      setSlackCodeInput('');
      setSlackEmailInput('');
      void fetchSlackMappings();
    } catch (error) {
      console.error('[DataSources] Failed to verify Slack code:', error);
      setSlackMappingStatus(
        error instanceof Error ? error.message : 'Failed to verify code.',
      );
    } finally {
      setSlackVerifyCodeLoading(false);
    }
  };

  const handleSlackDeleteMapping = async (mappingId: string): Promise<void> => {
    if (!organizationId || !userId) return;
    try {
      const params = new URLSearchParams({ organization_id: organizationId, user_id: userId });
      const delHeaders = await getAuthenticatedRequestHeaders();
      const response = await fetch(
        `${API_BASE}/slack/user-mappings/${mappingId}?${params.toString()}`,
        { method: 'DELETE', headers: delHeaders },
      );
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || `Failed to delete mapping: ${response.status}`);
      }
      void fetchSlackMappings();
    } catch (error) {
      console.error('[DataSources] Failed to delete Slack mapping:', error);
      setSlackMappingStatus(
        error instanceof Error ? error.message : 'Failed to delete Slack mapping.',
      );
    }
  };

  // 1. My connectors — user-scoped integrations current user has connected (exclude org-scoped)
  // 2. Team Connectors — org-scoped integrations (Slack, Web Search, etc.); always separate, regardless of who connected
  // 3. From your team — user-scoped integrations connected by teammates (prompt user to add own)
  // 4. Available — no one in org has connected yet
  const myConnectors = allIntegrations.filter((i) => i.currentUserConnected && i.scope === 'user');
  const orgConnectors = allIntegrations.filter((i) => i.connected && i.scope === 'organization');
  const fromTeamConnectors = allIntegrations.filter(
    (i) => i.connected && !i.currentUserConnected && i.scope === 'user' && i.teamConnections.length > 0
  );

  const sortByConnectorName = (a: DisplayIntegration, b: DisplayIntegration): number =>
    a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });

  const myConnectorsSorted: DisplayIntegration[] = [...myConnectors].sort(sortByConnectorName);
  const orgConnectorsSorted: DisplayIntegration[] = [...orgConnectors].sort(sortByConnectorName);
  const fromTeamConnectorsSorted: DisplayIntegration[] = [...fromTeamConnectors].sort(sortByConnectorName);

  const renderIcon = (iconId: string): JSX.Element => {
    if (isImageIcon(iconId)) {
      return <img src={iconId} alt="" className="w-full h-full rounded-xl object-cover" />;
    }
    const IconComponent = ICON_MAP[iconId] ?? HiGlobeAlt;
    return <IconComponent className="w-8 h-8" />;
  };

  const renderIconCompact = (iconId: string): JSX.Element => {
    if (isImageIcon(iconId)) {
      return <img src={iconId} alt="" className="h-6 w-6 rounded-md object-cover" />;
    }
    const IconComponent = ICON_MAP[iconId] ?? HiGlobeAlt;
    return <IconComponent className="h-5 w-5 text-surface-400" />;
  };

  // Tile state type for unified rendering (available only used in modal / legacy helpers)
  type TileState = 'connected' | 'org-connected' | 'team-only' | 'available';

  const connectedIntegrationPool: DisplayIntegration[] = [
    ...myConnectorsSorted,
    ...orgConnectorsSorted,
    ...fromTeamConnectorsSorted,
  ];
  const detailIntegration: DisplayIntegration | null =
    detailProvider === null
      ? null
      : connectedIntegrationPool.find((i) => i.provider === detailProvider) ?? null;

  const detailTileState: TileState | null =
    detailIntegration === null
      ? null
      : myConnectorsSorted.some((i) => i.provider === detailIntegration.provider)
        ? 'connected'
        : orgConnectorsSorted.some((i) => i.provider === detailIntegration.provider)
          ? 'org-connected'
          : 'team-only';

  const renderSharedWithTeamPill = (integration: DisplayIntegration): JSX.Element | null => {
    if (!isSharedWithTeam(integration)) return null;
    return (
      <span className="inline-flex shrink-0 items-center gap-1 rounded px-2 py-0.5 text-xs bg-primary-500/20 text-primary-400">
        <HiShare className="h-3 w-3" />
        Shared with team
      </span>
    );
  };

  const renderSharingBadgeBlock = (integration: DisplayIntegration, state: TileState): JSX.Element | null => {
    const sharedPill = renderSharedWithTeamPill(integration);
    if (sharedPill) return sharedPill;
    if (state !== 'connected') return null;
    return (
      <span className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs bg-surface-700 text-surface-400">
        <HiLockClosed className="h-3 w-3" />
        Private
      </span>
    );
  };

  const renderTeamInfoBlock = (integration: DisplayIntegration, state: TileState): JSX.Element | null => {
    if (state === 'team-only' || state === 'org-connected' || integration.teamTotal === 0) return null;
    const connectedCount = integration.teamConnections.length;
    const names = integration.teamConnections.map((tc) => tc.userName);
    const displayNames = names.slice(0, 3);
    const remaining = names.length - 3;
    const nameText =
      remaining > 0 ? `${displayNames.join(', ')}, +${remaining} more` : displayNames.join(', ');
    return (
      <div className="mt-4 border-t border-surface-700/50 pt-4">
        <div className="flex items-center gap-2 text-sm text-surface-400">
          <HiUserGroup className="h-4 w-4" />
          <span>
            {connectedCount}/{integration.teamTotal} team members connected
          </span>
        </div>
        {connectedCount > 0 && <p className="mt-1 pl-6 text-xs text-surface-500">{nameText}</p>}
      </div>
    );
  };

  const renderSlackDetailBlock = (integration: DisplayIntegration, state: TileState): JSX.Element | null => {
    if (integration.provider !== 'slack' || state !== 'connected') return null;
    return (
      <div className="mt-4 space-y-3 border-t border-surface-700/50 pt-4">
        <div className="space-y-1 text-xs text-surface-400">
          <p>
            <strong className="text-surface-300">To sync:</strong> Invite @Basebase to channels—type{' '}
            <code className="text-surface-300">/invite @Basebase</code> or add it from channel details.
          </p>
          <p>
            <strong className="text-surface-300">To chat:</strong> Mention @Basebase in any channel it&apos;s in;
            it&apos;ll reply in the thread.
          </p>
        </div>
        <div className="flex items-center justify-between">
          <div>
            <h4 className="text-sm font-semibold text-surface-100">Slack Identity</h4>
            <p className="mt-0.5 text-xs text-surface-400">
              {slackMappings.length > 0
                ? `${slackMappings.length} linked email${slackMappings.length !== 1 ? 's' : ''}`
                : 'Link your Slack email to connect your account'}
            </p>
          </div>
          <button
            type="button"
            onClick={() => setShowSlackVerificationModal(true)}
            className="rounded-lg border border-primary-500/30 px-3 py-1.5 text-xs font-medium text-primary-300 transition-colors hover:bg-primary-500/10"
          >
            {slackMappings.length > 0 ? 'Manage' : 'Link Account'}
          </button>
        </div>
      </div>
    );
  };

  const renderGitHubDetailBlock = (integration: DisplayIntegration, state: TileState): JSX.Element | null => {
    if (integration.provider !== 'github' || state !== 'connected') return null;
    const trackedCount = githubTrackedIds.size;
    const trackedNames =
      githubTrackedNames.length > 0
        ? githubTrackedNames
        : githubAvailableRepos.filter((r) => githubTrackedIds.has(r.github_repo_id)).map((r) => r.full_name);
    const showCompact = trackedCount > 0 && !githubReposExpanded;

    const toggleRepo = (id: number): void => {
      setGithubSelectedIds((prev) => {
        const next = new Set(prev);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
      });
    };
    const selectAll = (): void => setGithubSelectedIds(new Set(githubAvailableRepos.map((r) => r.github_repo_id)));
    const selectNone = (): void => setGithubSelectedIds(new Set());

    return (
      <div className="mt-4 space-y-3 border-t border-surface-700/50 pt-4">
        <div className="flex items-start justify-between gap-2">
          <div>
            <h4 className="text-sm font-semibold text-surface-100">Repos to track</h4>
            <p className="mt-0.5 text-xs text-surface-400">
              {showCompact
                ? `${trackedCount} repo${trackedCount !== 1 ? 's' : ''} tracked`
                : 'Select which repositories to sync. Tracking for this team.'}
            </p>
          </div>
          {showCompact && (
            <button
              type="button"
              onClick={() => setGithubReposExpanded(true)}
              className="whitespace-nowrap text-xs font-medium text-primary-400 hover:text-primary-300"
            >
              Change
            </button>
          )}
        </div>
        {showCompact ? (
          <p className="text-sm text-surface-300">{trackedNames.length > 0 ? trackedNames.join(', ') : '—'}</p>
        ) : (
          <>
            {githubReposError && <p className="text-xs text-red-400">{githubReposError}</p>}
            {githubReposLoading ? (
              <p className="text-sm text-surface-500">Loading repos…</p>
            ) : githubAvailableRepos.length === 0 ? (
              <p className="text-sm text-surface-500">No repos found. Check GitHub scopes (e.g. repo).</p>
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={selectAll}
                    className="text-xs text-primary-400 hover:text-primary-300"
                  >
                    Select all
                  </button>
                  <span className="text-surface-600">|</span>
                  <button
                    type="button"
                    onClick={selectNone}
                    className="text-xs text-primary-400 hover:text-primary-300"
                  >
                    Select none
                  </button>
                  {trackedCount > 0 && (
                    <>
                      <span className="text-surface-600">|</span>
                      <button
                        type="button"
                        onClick={() => setGithubReposExpanded(false)}
                        className="text-xs text-primary-400 hover:text-primary-300"
                      >
                        Done
                      </button>
                    </>
                  )}
                </div>
                <ul className="max-h-48 space-y-1.5 overflow-y-auto rounded-lg border border-surface-700/60 p-2">
                  {githubAvailableRepos.map((repo) => {
                    const id = repo.github_repo_id;
                    const checked = githubSelectedIds.has(id);
                    return (
                      <li key={id} className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          id={`gh-repo-drawer-${id}`}
                          checked={checked}
                          onChange={() => toggleRepo(id)}
                          className="rounded border-surface-600 bg-surface-800 text-primary-500 focus:ring-primary-500"
                        />
                        <label
                          htmlFor={`gh-repo-drawer-${id}`}
                          className="min-w-0 flex-1 cursor-pointer truncate text-sm text-surface-200"
                        >
                          <span className="font-medium">{repo.full_name}</span>
                          {repo.is_private && <span className="ml-2 text-xs text-surface-500">Private</span>}
                        </label>
                      </li>
                    );
                  })}
                </ul>
                <button
                  type="button"
                  onClick={() => void handleGitHubTrackRepos()}
                  disabled={githubSaving}
                  className="rounded-lg border border-primary-500/30 px-3 py-2 text-sm font-medium text-primary-300 transition-colors hover:bg-primary-500/10 disabled:opacity-50"
                >
                  {githubSaving ? 'Saving…' : 'Save tracked repos'}
                </button>
              </>
            )}
          </>
        )}
        <p className="text-xs text-surface-500">
          If you want to map users other than yourself, admins can manage identity mappings in the{' '}
          <button
            type="button"
            onClick={openTeamMembersPanel}
            className="text-primary-400 underline hover:text-primary-300"
          >
            Team UI
          </button>
          .
        </p>
      </div>
    );
  };

  const renderConnectorRow = (
    integration: DisplayIntegration,
    state: TileState,
  ): JSX.Element => {
    const isConnecting = connectingProvider === integration.provider;
    const codeSandboxConnectBlocked = integration.provider === 'code_sandbox' && !canConnectCodeSandbox;
    const isSyncingFromServer =
      (state === 'connected' || state === 'org-connected') &&
      getConnectorDisplay(integration.provider).hasSync !== false &&
      isFreshSyncStartedAt(integration.syncStats?.sync_started_at);
    const isSyncing = syncingProviders.has(integration.provider) || isSyncingFromServer;
    const isDisconnecting = disconnectingProviders.has(integration.provider);
    const syncPercent = isSyncing ? (syncProgressPercent[integration.provider] ?? 8) : 0;

    const hasSyncCapability: boolean = getConnectorDisplay(integration.provider).hasSync !== false;
    const showResyncInMenu: boolean =
      (state === 'connected' || state === 'org-connected') &&
      integration.provider !== 'google_drive' &&
      hasSyncCapability;

    const getButtonConfig = (): {
      text: string;
      className: string;
      action: () => void;
      disabled: boolean;
      hidden?: boolean;
    } => {
      if (state === 'connected' || state === 'org-connected') {
        if (!hasSyncCapability) {
          return { text: '', className: '', action: () => {}, disabled: true, hidden: true };
        }
        return {
          text: isSyncing ? 'Syncing...' : 'Sync',
          className:
            'inline-flex h-7 shrink-0 items-center justify-center gap-1.5 rounded-lg border border-surface-600 bg-surface-800 px-3 text-xs font-medium text-surface-200 transition-colors hover:bg-surface-700 disabled:opacity-50',
          action: () => void handleSync(integration.provider),
          disabled: isSyncing,
        };
      }
      return {
        text: codeSandboxConnectBlocked ? 'Admins only' : isConnecting ? 'Connecting...' : 'Connect',
        className: codeSandboxConnectBlocked
          ? 'inline-flex h-7 cursor-not-allowed items-center rounded-lg border border-surface-700 px-3 text-xs font-medium text-surface-500'
          : 'inline-flex h-7 items-center justify-center rounded-lg border border-primary-500/30 px-3 text-xs font-medium text-primary-400 transition-colors hover:bg-primary-500/10 disabled:opacity-50',
        action: () => {
          void handleConnect(integration.provider);
        },
        disabled: isConnecting || codeSandboxConnectBlocked,
      };
    };
    const buttonConfig = getButtonConfig();

    const canDisconnect: boolean =
      (state === 'connected' && integration.isOwner) || state === 'org-connected';

    const showRowMenu: boolean =
      (state === 'connected' && integration.isOwner) ||
      state === 'team-only' ||
      showResyncInMenu ||
      canDisconnect;

    const menuBtnClass =
      'inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-surface-600 text-surface-300 transition-colors hover:bg-surface-800 disabled:opacity-50';

    return (
      <li
        key={integration.id}
        className={
          isDisconnecting ? 'pointer-events-none opacity-50 transition-opacity duration-200' : undefined
        }
        ref={(el) => {
          connectorCardRefs.current[integration.provider] = el;
        }}
      >
        <div className="flex items-center gap-2 px-2 py-2 sm:gap-3">
          <button
            type="button"
            className="flex min-w-0 flex-1 items-center gap-2 rounded-md text-left outline-none ring-primary-500/40 hover:bg-surface-900/80 focus-visible:ring-2 sm:gap-3"
            onClick={() => setDetailProvider(integration.provider)}
            title={integration.name}
          >
            <span className="flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-md bg-surface-900">
              {renderIconCompact(integration.icon)}
            </span>
            <span className="flex min-w-0 flex-1 items-center gap-2">
              <span className="truncate text-sm text-surface-100">{integration.name}</span>
              {integration.provider.startsWith('mcp_') && (
                <span className="shrink-0 rounded bg-surface-700 px-1.5 py-0 text-[10px] font-medium uppercase tracking-wide text-surface-400">
                  Custom
                </span>
              )}
              {(state === 'org-connected' || state === 'team-only') && (
                <span className="shrink-0 rounded bg-surface-800 px-1.5 py-0 text-[10px] font-medium text-surface-500">
                  Team
                </span>
              )}
              {renderSharedWithTeamPill(integration)}
              {(state === 'connected' || state === 'org-connected') &&
                integration.lastError &&
                !isSyncing && (
                  <span className="h-2 w-2 shrink-0 rounded-full bg-red-500" title={integration.lastError} />
                )}
            </span>
          </button>

          {!buttonConfig.hidden && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                buttonConfig.action();
              }}
              disabled={buttonConfig.disabled}
              className={buttonConfig.className}
            >
              {(isConnecting || isSyncing) && (
                <svg className="h-3.5 w-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                  />
                </svg>
              )}
              {buttonConfig.text}
            </button>
          )}

          {showRowMenu ? (
            <div className="relative shrink-0" data-row-menu-root>
              <button
                type="button"
                className={menuBtnClass}
                aria-expanded={rowMenuOpenForId === integration.id}
                aria-haspopup="menu"
                aria-label="More actions"
                onPointerDown={(e) => e.stopPropagation()}
                onClick={() =>
                  setRowMenuOpenForId((cur) => (cur === integration.id ? null : integration.id))
                }
              >
                <HiChevronDown className="h-4 w-4" />
              </button>
              {rowMenuOpenForId === integration.id && (
                <div
                  role="menu"
                  className="absolute right-0 top-full z-[200] mt-1 min-w-[12rem] rounded-lg border border-surface-700 bg-surface-900 py-1 shadow-lg"
                >
                  {state === 'connected' && integration.isOwner && (
                    <button
                      type="button"
                      role="menuitem"
                      className="w-full px-3 py-2 text-left text-sm text-surface-200 hover:bg-surface-800"
                      onClick={() => {
                        setRowMenuOpenForId(null);
                        handleOpenSharingSettings(integration);
                      }}
                    >
                      Configure sharing
                    </button>
                  )}
                  {state === 'team-only' && (
                    <button
                      type="button"
                      role="menuitem"
                      className="w-full px-3 py-2 text-left text-sm text-surface-200 hover:bg-surface-800"
                      onClick={() => {
                        setRowMenuOpenForId(null);
                        void handleConnect(integration.provider);
                      }}
                    >
                      Connect your account
                    </button>
                  )}
                  {showResyncInMenu && (
                    <>
                      <button
                        type="button"
                        role="menuitem"
                        className="w-full px-3 py-2 text-left text-sm text-surface-200 hover:bg-surface-800 disabled:opacity-50"
                        disabled={isSyncing}
                        onClick={() => {
                          setRowMenuOpenForId(null);
                          void handleSync(integration.provider);
                        }}
                      >
                        Sync now
                      </button>
                      <button
                        type="button"
                        role="menuitem"
                        className="w-full px-3 py-2 text-left text-sm text-surface-200 hover:bg-surface-800 disabled:opacity-50"
                        disabled={isSyncing}
                        onClick={() => {
                          setRowMenuOpenForId(null);
                          void handleSync(integration.provider, isoUtcSubtractMs(RESYNC_OFFSET_MS.hours24));
                        }}
                      >
                        Resync · last 24 hours
                      </button>
                      <button
                        type="button"
                        role="menuitem"
                        className="w-full px-3 py-2 text-left text-sm text-surface-200 hover:bg-surface-800 disabled:opacity-50"
                        disabled={isSyncing}
                        onClick={() => {
                          setRowMenuOpenForId(null);
                          void handleSync(integration.provider, isoUtcSubtractMs(RESYNC_OFFSET_MS.days7));
                        }}
                      >
                        Resync · last 7 days
                      </button>
                      <button
                        type="button"
                        role="menuitem"
                        className="w-full px-3 py-2 text-left text-sm text-surface-200 hover:bg-surface-800 disabled:opacity-50"
                        disabled={isSyncing}
                        onClick={() => {
                          setRowMenuOpenForId(null);
                          void handleSync(integration.provider, isoUtcSubtractMs(RESYNC_OFFSET_MS.days30));
                        }}
                      >
                        Resync · last 30 days
                      </button>
                    </>
                  )}
                  {canDisconnect && (
                    <button
                      type="button"
                      role="menuitem"
                      className="w-full px-3 py-2 text-left text-sm text-red-400 hover:bg-surface-800 disabled:opacity-50"
                      disabled={isDisconnecting}
                      onClick={() => {
                        setRowMenuOpenForId(null);
                        void handleDisconnect(integration.provider);
                      }}
                    >
                      {isDisconnecting ? 'Disconnecting…' : 'Disconnect'}
                    </button>
                  )}
                </div>
              )}
            </div>
          ) : (
            <div className="h-7 w-7 shrink-0" aria-hidden />
          )}
        </div>
        {isSyncing && (
          <div
            className="mx-2 mb-1 h-0.5 overflow-hidden rounded-full bg-primary-500/20"
            role="progressbar"
            aria-label={`${integration.name} sync progress`}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={syncPercent}
          >
            <div
              className="h-full rounded-full bg-primary-400/80 transition-[width] duration-700 ease-out"
              style={{ width: `${syncPercent}%` }}
            />
          </div>
        )}
      </li>
    );
  };

  if (integrationsLoading && rawIntegrations.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-primary-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  // Filtered list for the add-connector modal (always starts from full connector list)
  const filteredConnectModalIntegrations: DisplayIntegration[] = allConnectorsForModal.filter(
    (i: DisplayIntegration): boolean => {
      if (!connectSearch.trim()) return true;
      const query: string = connectSearch.toLowerCase();
      return (
        i.name.toLowerCase().includes(query) ||
        i.description.toLowerCase().includes(query) ||
        i.provider.toLowerCase().includes(query)
      );
    }
  );

  const openAddConnectorModal = (): void => {
    setShowConnectModal(true);
    setConnectSearch('');
  };

  const openCustomMcpForm = (): void => {
    setMcpName('');
    setMcpEndpointUrl('');
    setMcpBearerToken('');
    setMcpError(null);
    setShowMcpForm(true);
  };

  return (
    <div className="flex-1 overflow-y-auto overflow-x-hidden">
      {/* Mobile — Browse connectors + overflow for Sync all */}
      <div className="sticky top-0 z-20 flex-shrink-0 border-b border-surface-800 bg-surface-950/95 px-4 py-2 backdrop-blur-sm md:hidden">
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={openAddConnectorModal}
            className="inline-flex items-center gap-1.5 rounded-lg border border-surface-600 px-3 py-2 text-sm font-medium text-surface-100 transition-colors hover:bg-surface-800"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            Browse connectors
          </button>
          {canSyncAllConnectors && (
            <div className="relative shrink-0" data-page-overflow-root>
              <button
                type="button"
                onPointerDown={(e) => e.stopPropagation()}
                onClick={() => setPageOverflowOpen((o) => !o)}
                className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-surface-700 text-surface-300 hover:bg-surface-800"
                aria-expanded={pageOverflowOpen}
                aria-label="More actions"
              >
                <HiDotsVertical className="h-5 w-5" />
              </button>
              {pageOverflowOpen && (
                <div className="absolute right-0 top-full z-30 mt-1 min-w-[11rem] rounded-lg border border-surface-700 bg-surface-900 py-1 shadow-lg">
                  <button
                    type="button"
                    disabled={syncingAll}
                    className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-surface-200 hover:bg-surface-800 disabled:opacity-50"
                    onClick={() => {
                      setPageOverflowOpen(false);
                      void handleSyncAll();
                    }}
                  >
                    {syncingAll ? (
                      <>
                        <span className="h-4 w-4 animate-spin rounded-full border-2 border-surface-400 border-t-transparent" />
                        Syncing…
                      </>
                    ) : (
                      <>
                        <HiLightningBolt className="h-4 w-4 text-amber-400" />
                        Sync all
                      </>
                    )}
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      <header className="sticky top-0 z-20 hidden border-b border-surface-800 bg-surface-950 px-4 py-4 md:block md:px-8 md:py-5">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h1 className="text-xl font-bold text-surface-100">Connectors</h1>
            <p className="mt-1 text-sm text-surface-400">Connect your tools so the AI can use them.</p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={openAddConnectorModal}
              className="rounded-lg border border-surface-600 px-4 py-2 text-sm font-medium text-surface-100 transition-colors hover:bg-surface-800"
            >
              Browse connectors
            </button>
            {canSyncAllConnectors && (
              <div className="relative" data-page-overflow-root>
                <button
                  type="button"
                  onPointerDown={(e) => e.stopPropagation()}
                  onClick={() => setPageOverflowOpen((o) => !o)}
                  className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-surface-600 text-surface-300 hover:bg-surface-800"
                  aria-expanded={pageOverflowOpen}
                  aria-label="More actions"
                >
                  <HiDotsVertical className="h-5 w-5" />
                </button>
                {pageOverflowOpen && (
                  <div className="absolute right-0 top-full z-30 mt-1 min-w-[11rem] rounded-lg border border-surface-700 bg-surface-900 py-1 shadow-lg">
                    <button
                      type="button"
                      disabled={syncingAll}
                      className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-surface-200 hover:bg-surface-800 disabled:opacity-50"
                      onClick={() => {
                        setPageOverflowOpen(false);
                        void handleSyncAll();
                      }}
                    >
                      {syncingAll ? (
                        <>
                          <span className="h-4 w-4 animate-spin rounded-full border-2 border-surface-400 border-t-transparent" />
                          Syncing…
                        </>
                      ) : (
                        <>
                          <HiLightningBolt className="h-4 w-4 text-amber-400" />
                          Sync all
                        </>
                      )}
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </header>

      {/* Add connector modal */}
      {showConnectModal && (
        <div className="fixed inset-0 z-50 flex items-start justify-center pt-[10vh]">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={() => setShowConnectModal(false)}
          />
          {/* Modal */}
          <div className="relative bg-surface-900 border border-surface-700 rounded-2xl shadow-2xl w-full max-w-lg mx-4 overflow-hidden">
            <div className="p-5 border-b border-surface-700/50">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-semibold text-surface-100">Browse connectors</h2>
                <button
                  onClick={() => setShowConnectModal(false)}
                  className="text-surface-400 hover:text-surface-200 transition-colors"
                >
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
              <input
                type="text"
                value={connectSearch}
                onChange={(e) => setConnectSearch(e.target.value)}
                placeholder="Search connectors..."
                autoFocus
                className="w-full rounded-lg bg-surface-800 border border-surface-600 px-4 py-2.5 text-sm text-surface-100 placeholder:text-surface-500 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500/30"
              />
            </div>
            <ul className="max-h-[50vh] overflow-y-auto p-2">
              {connectorsLoading ? (
                <li className="px-4 py-8 text-center text-sm text-surface-500">
                  Loading connectors...
                </li>
              ) : connectorsError && allConnectorsForModal.length === 0 ? (
                <li className="px-4 py-8 text-center text-sm text-red-400">
                  {connectorsError}
                </li>
              ) : filteredConnectModalIntegrations.length === 0 ? (
                <li className="px-4 py-8 text-center text-sm text-surface-500">
                  No connectors match your search.
                </li>
              ) : (
                filteredConnectModalIntegrations.map((integration) => {
                  const isConnecting: boolean = connectingProvider === integration.provider;
                  const codeSandboxBlocked: boolean = integration.provider === 'code_sandbox' && !canConnectCodeSandbox;
                  return (
                    <li key={integration.provider}>
                      <button
                        onClick={() => {
                          setShowConnectModal(false);
                          void handleConnect(integration.provider);
                        }}
                        disabled={isConnecting || codeSandboxBlocked}
                        className="w-full flex items-center gap-4 px-4 py-3 rounded-xl hover:bg-surface-800 transition-colors text-left group disabled:opacity-50"
                      >
                        <div className={`${isImageIcon(integration.icon) ? '' : getColorClass(integration.color) + ' p-2 text-white'} rounded-lg flex-shrink-0 w-10 h-10 flex items-center justify-center overflow-hidden`}>
                          {renderIcon(integration.icon)}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="font-medium text-surface-100 group-hover:text-white transition-colors">
                            {integration.name}
                          </div>
                          <div className="text-xs text-surface-500 truncate mt-0.5">
                            {codeSandboxBlocked
                              ? `${integration.description} • Admin access required to connect`
                              : integration.description}
                          </div>
                        </div>
                        {isConnecting ? (
                          <svg className="w-5 h-5 animate-spin text-primary-400 flex-shrink-0" fill="none" viewBox="0 0 24 24">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                          </svg>
                        ) : (
                          <svg className="w-5 h-5 text-surface-600 group-hover:text-surface-400 transition-colors flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                          </svg>
                        )}
                      </button>
                    </li>
                  );
                })
              )}
            </ul>
          </div>
        </div>
      )}

      {/* MCP Connect Form Modal */}
      {showMcpForm && (
        <div className="fixed inset-0 z-50 flex items-start justify-center pt-[10vh]">
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={() => { if (!mcpConnecting) setShowMcpForm(false); }}
          />
          <div className="relative bg-surface-900 border border-surface-700 rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden">
            <div className="p-5 border-b border-surface-700/50">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="bg-gradient-to-br from-cyan-500 to-blue-600 p-2 rounded-lg text-white">
                    <HiLink className="w-5 h-5" />
                  </div>
                  <h2 className="text-lg font-semibold text-surface-100">Connect MCP Server</h2>
                </div>
                <button
                  onClick={() => { if (!mcpConnecting) setShowMcpForm(false); }}
                  className="text-surface-400 hover:text-surface-200 transition-colors"
                >
                  <HiX className="w-5 h-5" />
                </button>
              </div>
            </div>
            <form
              onSubmit={(e) => { e.preventDefault(); void handleMcpConnect(); }}
              className="p-5 space-y-4"
            >
              <div>
                <label htmlFor="mcp-name" className="block text-sm font-medium text-surface-300 mb-1.5">
                  Name <span className="text-red-400">*</span>
                </label>
                <input
                  id="mcp-name"
                  type="text"
                  value={mcpName}
                  onChange={(e) => setMcpName(e.target.value)}
                  placeholder="e.g. SimilarWeb, Stripe, Notion"
                  required
                  disabled={mcpConnecting}
                  autoFocus
                  className="w-full rounded-lg bg-surface-800 border border-surface-600 px-4 py-2.5 text-sm text-surface-100 placeholder:text-surface-500 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500/30 disabled:opacity-50"
                />
              </div>
              <div>
                <label htmlFor="mcp-url" className="block text-sm font-medium text-surface-300 mb-1.5">
                  Endpoint URL <span className="text-red-400">*</span>
                </label>
                <input
                  id="mcp-url"
                  type="url"
                  value={mcpEndpointUrl}
                  onChange={(e) => setMcpEndpointUrl(e.target.value)}
                  placeholder="https://mcp.example.com/mcp"
                  required
                  disabled={mcpConnecting}
                  className="w-full rounded-lg bg-surface-800 border border-surface-600 px-4 py-2.5 text-sm text-surface-100 placeholder:text-surface-500 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500/30 disabled:opacity-50"
                />
              </div>
              <div>
                <label htmlFor="mcp-token" className="block text-sm font-medium text-surface-300 mb-1.5">
                  Auth Header <span className="text-surface-500 font-normal">(optional)</span>
                </label>
                <input
                  id="mcp-token"
                  type="password"
                  value={mcpBearerToken}
                  onChange={(e) => setMcpBearerToken(e.target.value)}
                  placeholder="e.g. api-key: abc123  or  Bearer token"
                  disabled={mcpConnecting}
                  className="w-full rounded-lg bg-surface-800 border border-surface-600 px-4 py-2.5 text-sm text-surface-100 placeholder:text-surface-500 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500/30 disabled:opacity-50"
                />
              </div>
              {mcpError && (
                <div className="text-sm text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2">
                  {mcpError}
                </div>
              )}
              <div className="flex gap-3 pt-1">
                <button
                  type="button"
                  onClick={() => setShowMcpForm(false)}
                  disabled={mcpConnecting}
                  className="flex-1 px-4 py-2.5 text-sm font-medium text-surface-300 bg-surface-800 hover:bg-surface-700 border border-surface-600 rounded-lg transition-colors disabled:opacity-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={mcpConnecting || !mcpName.trim() || !mcpEndpointUrl.trim()}
                  className="flex-1 px-4 py-2.5 text-sm font-semibold text-white bg-primary-600 hover:bg-primary-500 rounded-lg transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
                >
                  {mcpConnecting ? (
                    <>
                      <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                      Connecting...
                    </>
                  ) : (
                    'Connect'
                  )}
                </button>
              </div>
              <p className="text-xs text-surface-500">
                We&apos;ll validate the connection and discover available tools from the MCP server.
              </p>
            </form>
          </div>
        </div>
      )}

      {/* Code Sandbox Risk Warning Modal */}
      {showCodeSandboxWarning && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="w-full max-w-lg rounded-2xl border border-amber-500/30 bg-surface-900 shadow-2xl">
            <div className="border-b border-surface-700/60 p-5">
              <div className="flex items-start gap-3">
                <div className="mt-0.5 rounded-xl bg-amber-500/15 p-2 text-amber-300">
                  <HiLightningBolt className="h-5 w-5" />
                </div>
                <div>
                  <h2 className="text-lg font-semibold text-surface-100">
                    Warning: Code Sandbox can run insecure code
                  </h2>
                  <p className="mt-1 text-sm text-surface-400">
                    This connector can execute arbitrary code and shell commands. If misused, it may
                    expose secrets, enable data exfiltration, or lead to a data breach.
                  </p>
                </div>
              </div>
            </div>
            <div className="space-y-4 p-5">
              <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 p-4 text-sm text-amber-100">
                <p className="font-medium text-amber-200">Admin-only connector</p>
                <p className="mt-1 text-amber-100/90">
                  Only organization admins or global admins should connect Code Sandbox. Continue
                  only if you understand the risk and explicitly want to enable it for your org.
                </p>
              </div>
              <p className="text-sm text-surface-400">
                Use this connector only at your own risk.
              </p>
              <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
                <button
                  onClick={() => setShowCodeSandboxWarning(false)}
                  className="rounded-lg border border-surface-600 px-4 py-2 text-sm font-medium text-surface-200 transition-colors hover:bg-surface-800"
                >
                  Cancel
                </button>
                <button
                  onClick={() => void handleConfirmCodeSandboxConnect()}
                  className="rounded-lg bg-amber-500 px-4 py-2 text-sm font-semibold text-surface-950 transition-colors hover:bg-amber-400"
                >
                  Connect at my own risk
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {showIspotForm && (
        <div className="fixed inset-0 z-50 flex items-start justify-center pt-[10vh]">
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={() => { if (!ispotConnecting) setShowIspotForm(false); }}
          />
          <div className="relative bg-surface-900 border border-surface-700 rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden">
            <div className="p-5 border-b border-surface-700/50">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="bg-gradient-to-br from-emerald-500 to-teal-600 p-2 rounded-lg text-white">
                    <HiGlobeAlt className="w-5 h-5" />
                  </div>
                  <h2 className="text-lg font-semibold text-surface-100">Connect iSpot.tv</h2>
                </div>
                <button
                  onClick={() => { if (!ispotConnecting) setShowIspotForm(false); }}
                  className="text-surface-400 hover:text-surface-200 transition-colors"
                >
                  <HiX className="w-5 h-5" />
                </button>
              </div>
            </div>
            <form
              onSubmit={(e) => { e.preventDefault(); void handleIspotConnect(); }}
              className="p-5 space-y-4"
            >
              <p className="text-sm text-surface-400">
                Enter your iSpot.tv OAuth client credentials (from your iSpot account manager). No browser sign-in required.
              </p>
              <div>
                <label htmlFor="ispot-client-id" className="block text-sm font-medium text-surface-300 mb-1.5">
                  OAuth Client ID <span className="text-red-400">*</span>
                </label>
                <input
                  id="ispot-client-id"
                  type="text"
                  value={ispotClientId}
                  onChange={(e) => setIspotClientId(e.target.value)}
                  placeholder="Client ID"
                  required
                  disabled={ispotConnecting}
                  autoFocus
                  className="w-full rounded-lg bg-surface-800 border border-surface-600 px-4 py-2.5 text-sm text-surface-100 placeholder:text-surface-500 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500/30 disabled:opacity-50"
                />
              </div>
              <div>
                <label htmlFor="ispot-client-secret" className="block text-sm font-medium text-surface-300 mb-1.5">
                  OAuth Client Secret <span className="text-red-400">*</span>
                </label>
                <input
                  id="ispot-client-secret"
                  type="password"
                  value={ispotClientSecret}
                  onChange={(e) => setIspotClientSecret(e.target.value)}
                  placeholder="Client Secret"
                  required
                  disabled={ispotConnecting}
                  className="w-full rounded-lg bg-surface-800 border border-surface-600 px-4 py-2.5 text-sm text-surface-100 placeholder:text-surface-500 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500/30 disabled:opacity-50"
                />
              </div>
              {ispotError && (
                <div className="text-sm text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2">
                  {ispotError}
                </div>
              )}
              <div className="flex gap-3 pt-1">
                <button
                  type="button"
                  onClick={() => setShowIspotForm(false)}
                  disabled={ispotConnecting}
                  className="flex-1 px-4 py-2.5 text-sm font-medium text-surface-300 bg-surface-800 hover:bg-surface-700 border border-surface-600 rounded-lg transition-colors disabled:opacity-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={ispotConnecting || !ispotClientId.trim() || !ispotClientSecret.trim()}
                  className="flex-1 px-4 py-2.5 text-sm font-semibold text-white bg-primary-600 hover:bg-primary-500 rounded-lg transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
                >
                  {ispotConnecting ? (
                    <>
                      <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                      Connecting...
                    </>
                  ) : (
                    'Connect'
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      <div className="mx-auto max-w-4xl space-y-8 px-4 py-6 md:space-y-10 md:px-8 md:py-6">
        {connectedIntegrationPool.length === 0 ? (
          <div className="rounded-lg border border-surface-800 bg-surface-900/30 px-6 py-10 text-center">
            <p className="text-sm text-surface-400">
              No connectors yet.{' '}
              <button
                type="button"
                onClick={openAddConnectorModal}
                className="font-medium text-primary-400 underline underline-offset-2 hover:text-primary-300"
              >
                Browse connectors
              </button>{' '}
              to add one.
            </p>
          </div>
        ) : (
          <>
            {myConnectorsSorted.length > 0 && (
              <section>
                <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-surface-500">
                  My connectors
                </h2>
                <ul className="divide-y divide-surface-800 rounded-lg border border-surface-800 bg-surface-950/40">
                  {myConnectorsSorted.map((integration) => renderConnectorRow(integration, 'connected'))}
                </ul>
              </section>
            )}

            {orgConnectorsSorted.length > 0 && (
              <section>
                <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-surface-500">
                  Team connectors
                </h2>
                <p className="mb-2 text-xs text-surface-500">
                  Org-wide connectors. Anyone on the team can sync or disconnect.
                </p>
                <ul className="divide-y divide-surface-800 rounded-lg border border-surface-800 bg-surface-950/40">
                  {orgConnectorsSorted.map((integration) => renderConnectorRow(integration, 'org-connected'))}
                </ul>
              </section>
            )}

            {fromTeamConnectorsSorted.length > 0 && (
              <section>
                <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-surface-500">
                  From your team
                </h2>
                <p className="mb-2 text-xs text-surface-500">
                  Teammates connected these. Add your own account so Basebase can access your data.
                </p>
                <ul className="divide-y divide-surface-800 rounded-lg border border-surface-800 bg-surface-950/40">
                  {fromTeamConnectorsSorted.map((integration) => renderConnectorRow(integration, 'team-only'))}
                </ul>
              </section>
            )}
          </>
        )}

        <div className="pt-1">
          <button
            type="button"
            onClick={openCustomMcpForm}
            className="rounded-lg border border-surface-600 px-4 py-2 text-sm font-medium text-surface-200 transition-colors hover:bg-surface-800"
          >
            Add custom connector
          </button>
        </div>
      </div>

      {/* Connector detail drawer */}
      {detailIntegration !== null && detailTileState !== null && (() => {
        const d = detailIntegration;
        const st = detailTileState;
        const isSyncingDrawerFromServer =
          (st === 'connected' || st === 'org-connected') &&
          getConnectorDisplay(d.provider).hasSync !== false &&
          isFreshSyncStartedAt(d.syncStats?.sync_started_at);
        const isSyncingDrawer = syncingProviders.has(d.provider) || isSyncingDrawerFromServer;
        const syncPercentDrawer = isSyncingDrawer ? (syncProgressPercent[d.provider] ?? 8) : 0;
        const hasSyncDrawer = getConnectorDisplay(d.provider).hasSync !== false;
        const showResyncDrawer =
          (st === 'connected' || st === 'org-connected') &&
          d.provider !== 'google_drive' &&
          hasSyncDrawer;
        const canDisconnectDrawer = (st === 'connected' && d.isOwner) || st === 'org-connected';

        return (
          <>
            <button
              type="button"
              className="fixed inset-0 z-[44] bg-black/50"
              aria-label="Close details"
              onClick={() => setDetailProvider(null)}
            />
            <aside className="fixed inset-y-0 right-0 z-[45] flex w-full max-w-full flex-col border-l border-surface-800 bg-surface-950 shadow-2xl sm:max-w-md">
              <div className="flex items-start justify-between gap-3 border-b border-surface-800 px-4 py-4">
                <div className="flex min-w-0 items-start gap-3">
                  <div
                    className={`flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-xl ${
                      isImageIcon(d.icon) ? '' : `${getColorClass(d.color)} text-white`
                    }`}
                  >
                    {isImageIcon(d.icon) ? (
                      <img src={d.icon} alt="" className="h-full w-full object-cover" />
                    ) : (
                      renderIcon(d.icon)
                    )}
                  </div>
                  <div className="min-w-0">
                    <h2 className="text-lg font-semibold text-surface-100">{d.name}</h2>
                    <p className="mt-1 text-sm text-surface-400">{d.description}</p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setDetailProvider(null)}
                  className="rounded-lg p-2 text-surface-400 hover:bg-surface-800 hover:text-surface-200"
                  aria-label="Close"
                >
                  <HiX className="h-5 w-5" />
                </button>
              </div>

              <div className="flex-1 overflow-y-auto px-4 py-4">
                <div className="flex flex-wrap items-center gap-2">
                  {renderSharingBadgeBlock(d, st)}
                  {d.provider.startsWith('mcp_') && (
                    <span className="rounded bg-surface-700 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-surface-400">
                      Custom
                    </span>
                  )}
                </div>

                {st === 'connected' && d.connectedBy && !d.isOwner && (
                  <p className="mt-3 text-xs text-surface-500">Connected by {d.connectedBy}</p>
                )}

                {(st === 'connected' || st === 'org-connected') && d.lastSyncAt && !isSyncingDrawer && (
                  <p className="mt-3 text-xs text-surface-500">
                    Last synced: {new Date(d.lastSyncAt).toLocaleString()}
                  </p>
                )}

                {(st === 'connected' || st === 'org-connected') &&
                  (isSyncingDrawer ||
                    syncProgress[d.provider] !== undefined ||
                    d.syncStats) && (
                  <div className="mt-2 space-y-2 text-xs text-surface-400">
                    {isSyncingDrawer ? (
                      <>
                        <span className="text-primary-400">
                          Syncing
                          {syncStep[d.provider] ? ` ${syncStep[d.provider]}` : ''}
                          {syncProgress[d.provider] !== undefined
                            ? `… ${getActivityLabel(d.provider, syncProgress[d.provider] ?? 0, syncStep[d.provider])}`
                            : '…'}
                        </span>
                        <div
                          className="h-1.5 overflow-hidden rounded-full bg-primary-500/20"
                          role="progressbar"
                          aria-label={`${d.name} sync progress`}
                          aria-valuemin={0}
                          aria-valuemax={100}
                          aria-valuenow={syncPercentDrawer}
                        >
                          <div
                            className="h-full rounded-full bg-primary-400/80 transition-[width] duration-700 ease-out"
                            style={{ width: `${syncPercentDrawer}%` }}
                          />
                        </div>
                      </>
                    ) : syncProgress[d.provider] !== undefined ? (
                      <span className="text-primary-400">
                        Syncing
                        {syncStep[d.provider] ? ` ${syncStep[d.provider]}` : ''}
                        …{' '}
                        {getActivityLabel(
                          d.provider,
                          syncProgress[d.provider] ?? 0,
                          syncStep[d.provider],
                        )}
                      </span>
                    ) : d.syncStats ? (
                      formatSyncStats(d.syncStats, d.provider)
                    ) : null}
                  </div>
                )}

                {(st === 'connected' || st === 'org-connected') && d.lastError && !isSyncingDrawer && (
                  <p className="mt-2 text-xs text-red-400">Error: {d.lastError}</p>
                )}

                {st === 'org-connected' && (
                  <p className="mt-3 text-xs text-surface-400">
                    Connected by {d.teamConnections.map((tc) => tc.userName).join(', ')}
                  </p>
                )}

                {st === 'team-only' && (
                  <div className="mt-3 space-y-1 text-xs text-surface-400">
                    <p>Connected by {d.teamConnections.map((tc) => tc.userName).join(', ')}</p>
                    {d.shareSyncedData || d.shareQueryAccess || d.shareWriteAccess ? (
                      <p className="text-surface-300">
                        Shared with you:{' '}
                        {[
                          d.shareSyncedData && 'synced data',
                          d.shareQueryAccess && 'query access',
                          d.shareWriteAccess && 'write access',
                        ]
                          .filter(Boolean)
                          .join(', ')}
                      </p>
                    ) : (
                      <p className="text-surface-500">No sharing enabled yet</p>
                    )}
                  </div>
                )}

                {d.provider === 'code_sandbox' && !canConnectCodeSandbox && (
                  <p className="mt-3 text-xs text-amber-400">
                    Code Sandbox can only be connected by organization admins or global admins.
                  </p>
                )}

                {d.provider === 'ispot_tv' && (
                  <div className="mt-4">
                    <button
                      type="button"
                      onClick={() => {
                        setIspotClientId('');
                        setIspotClientSecret('');
                        setIspotError(null);
                        setShowIspotForm(true);
                      }}
                      className="rounded-lg border border-surface-600 px-3 py-2 text-sm font-medium text-surface-200 hover:bg-surface-800"
                    >
                      Manage credentials
                    </button>
                  </div>
                )}

                {renderTeamInfoBlock(d, st)}
                {renderGitHubDetailBlock(d, st)}
                {renderSlackDetailBlock(d, st)}
              </div>

              <div className="flex flex-wrap gap-2 border-t border-surface-800 px-4 py-4">
                {st === 'connected' && d.isOwner && (
                  <button
                    type="button"
                    onClick={() => handleOpenSharingSettings(d)}
                    className="inline-flex items-center gap-2 rounded-lg border border-surface-600 px-3 py-2 text-xs font-medium text-surface-200 hover:bg-surface-800"
                  >
                    <HiCog className="h-4 w-4" />
                    Configure sharing
                  </button>
                )}
                {hasSyncDrawer && (st === 'connected' || st === 'org-connected') && (
                  <button
                    type="button"
                    disabled={isSyncingDrawer}
                    onClick={() => void handleSync(d.provider)}
                    className="rounded-lg border border-surface-600 bg-surface-800 px-3 py-2 text-xs font-medium text-surface-100 hover:bg-surface-700 disabled:opacity-50"
                  >
                    {isSyncingDrawer ? 'Syncing…' : 'Sync now'}
                  </button>
                )}
                {showResyncDrawer && (
                  <>
                    <button
                      type="button"
                      disabled={isSyncingDrawer}
                      onClick={() => void handleSync(d.provider, isoUtcSubtractMs(RESYNC_OFFSET_MS.hours24))}
                      className="rounded-lg border border-surface-600 px-3 py-2 text-xs font-medium text-surface-200 hover:bg-surface-800 disabled:opacity-50"
                    >
                      Resync 24h
                    </button>
                    <button
                      type="button"
                      disabled={isSyncingDrawer}
                      onClick={() => void handleSync(d.provider, isoUtcSubtractMs(RESYNC_OFFSET_MS.days7))}
                      className="rounded-lg border border-surface-600 px-3 py-2 text-xs font-medium text-surface-200 hover:bg-surface-800 disabled:opacity-50"
                    >
                      Resync 7d
                    </button>
                    <button
                      type="button"
                      disabled={isSyncingDrawer}
                      onClick={() => void handleSync(d.provider, isoUtcSubtractMs(RESYNC_OFFSET_MS.days30))}
                      className="rounded-lg border border-surface-600 px-3 py-2 text-xs font-medium text-surface-200 hover:bg-surface-800 disabled:opacity-50"
                    >
                      Resync 30d
                    </button>
                  </>
                )}
                {st === 'team-only' && (
                  <button
                    type="button"
                    onClick={() => void handleConnect(d.provider)}
                    className="rounded-lg border border-primary-500/30 px-3 py-2 text-xs font-medium text-primary-400 hover:bg-primary-500/10"
                  >
                    Connect your account
                  </button>
                )}
                {canDisconnectDrawer && (
                  <button
                    type="button"
                    onClick={() => void handleDisconnect(d.provider)}
                    className="rounded-lg px-3 py-2 text-xs font-medium text-red-400 hover:bg-red-500/10"
                  >
                    Disconnect
                  </button>
                )}
              </div>
            </aside>
          </>
        );
      })()}

      {/* Disconnect / error / success banners */}
      {syncError && (
        <div className="fixed bottom-4 right-4 z-50 bg-red-500/10 border border-red-500/30 text-red-400 px-4 py-3 rounded-lg text-sm max-w-sm shadow-lg">
          {syncError}
        </div>
      )}
      {disconnectError && (
        <div className="fixed bottom-4 right-4 z-50 bg-red-500/10 border border-red-500/30 text-red-400 px-4 py-3 rounded-lg text-sm max-w-sm shadow-lg">
          {disconnectError}
        </div>
      )}
      {disconnectSuccess && (
        <div className="fixed bottom-4 right-4 z-50 bg-primary-500/10 border border-primary-500/30 text-primary-400 px-4 py-3 rounded-lg text-sm max-w-sm shadow-lg">
          {disconnectSuccess}
        </div>
      )}

      {/* Disconnect Confirmation Modal */}
      {disconnectModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setDisconnectModal(null)}>
          <div className="bg-surface-900 border border-surface-700 rounded-xl shadow-xl w-full max-w-md mx-4" onClick={(e) => e.stopPropagation()}>
            <div className="p-6">
              {disconnectModal.step === 'confirm' ? (
                <>
                  <h2 className="text-lg font-semibold text-surface-100 mb-2">Disconnect {disconnectModal.provider}?</h2>
                  <p className="text-sm text-surface-400 mb-6">
                    This will remove the connection. You can reconnect later.
                  </p>
                  <div className="flex justify-end gap-3">
                    <button
                      onClick={() => setDisconnectModal(null)}
                      className="px-4 py-2 text-sm font-medium text-surface-300 hover:text-surface-100 transition-colors"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={() => setDisconnectModal({ ...disconnectModal, step: 'ask-delete' })}
                      className="px-4 py-2 text-sm font-medium bg-red-600 hover:bg-red-500 text-white rounded-lg transition-colors"
                    >
                      Disconnect
                    </button>
                  </div>
                </>
              ) : (
                <>
                  <h2 className="text-lg font-semibold text-surface-100 mb-2">Delete synced data?</h2>
                  <p className="text-sm text-surface-400 mb-6">
                    Do you also want to delete all data synced from {disconnectModal.provider}? This includes contacts, companies, deals, pipelines, activities, and meetings imported from this integration.
                  </p>
                  <div className="flex justify-end gap-3">
                    <button
                      onClick={() => void executeDisconnect(disconnectModal.provider, false)}
                      className="px-4 py-2 text-sm font-medium text-surface-300 hover:text-surface-100 transition-colors"
                    >
                      Keep Data
                    </button>
                    <button
                      onClick={() => void executeDisconnect(disconnectModal.provider, true)}
                      className="px-4 py-2 text-sm font-medium bg-red-600 hover:bg-red-500 text-white rounded-lg transition-colors"
                    >
                      Delete Data
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Slack Identity Verification Modal */}
      {showSlackVerificationModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setShowSlackVerificationModal(false)}>
          <div className="bg-surface-900 border border-surface-700 rounded-xl shadow-xl w-full max-w-md mx-4" onClick={(e) => e.stopPropagation()}>
            <div className="p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-semibold text-surface-100">Link Slack Account</h2>
                <button
                  onClick={() => setShowSlackVerificationModal(false)}
                  className="p-1 text-surface-400 hover:text-surface-200 rounded"
                >
                  <HiX className="w-5 h-5" />
                </button>
              </div>

              <p className="text-sm text-surface-400 mb-4">
                Enter your Slack email to link your account. We&apos;ll DM you a 6-digit code to confirm.
              </p>

              {/* Email + Send Code */}
              <div className="grid gap-2 sm:grid-cols-[1fr_auto] mb-3">
                <input
                  type="email"
                  value={slackEmailInput}
                  onChange={(event) => setSlackEmailInput(event.target.value)}
                  placeholder="you@company.com"
                  className="w-full rounded-lg bg-surface-800 border border-surface-700 px-3 py-2 text-sm text-surface-100 placeholder:text-surface-500 focus:border-primary-500 focus:outline-none"
                />
                <button
                  onClick={() => void handleSlackRequestCode()}
                  disabled={!slackEmailInput.trim() || slackSendCodeLoading}
                  className="px-4 py-2 text-sm font-medium text-primary-300 border border-primary-500/30 hover:bg-primary-500/10 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors"
                >
                  {slackSendCodeLoading ? (
                    <span className="inline-flex items-center justify-center gap-2">
                      <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                      </svg>
                      Sending…
                    </span>
                  ) : (
                    'Send code'
                  )}
                </button>
              </div>

              {/* Code + Verify */}
              <div className="grid gap-2 sm:grid-cols-[1fr_auto] mb-3">
                <input
                  type="text"
                  value={slackCodeInput}
                  onChange={(event) => setSlackCodeInput(event.target.value)}
                  placeholder="Enter 6-digit code"
                  className="w-full rounded-lg bg-surface-800 border border-surface-700 px-3 py-2 text-sm text-surface-100 placeholder:text-surface-500 focus:border-primary-500 focus:outline-none"
                />
                <button
                  onClick={() => void handleSlackVerifyCode()}
                  disabled={!slackEmailInput.trim() || !slackCodeInput.trim() || slackVerifyCodeLoading}
                  className="px-4 py-2 text-sm font-medium text-emerald-300 border border-emerald-500/30 hover:bg-emerald-500/10 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors"
                >
                  {slackVerifyCodeLoading ? (
                    <span className="inline-flex items-center justify-center gap-2">
                      <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                      </svg>
                      Verifying…
                    </span>
                  ) : (
                    'Verify'
                  )}
                </button>
              </div>

              {slackMappingStatus && (
                <p className="text-xs text-surface-300 mb-2">{slackMappingStatus}</p>
              )}
              {slackMappingsError && (
                <p className="text-xs text-red-400 mb-2">{slackMappingsError}</p>
              )}

              {/* Linked accounts */}
              <div className="mt-4 pt-4 border-t border-surface-700 space-y-2">
                <div className="flex items-center justify-between">
                  <h5 className="text-xs font-semibold uppercase tracking-wide text-surface-400">
                    Linked Slack emails
                  </h5>
                  {slackMappingsLoading && (
                    <span className="text-xs text-surface-500">Loading...</span>
                  )}
                </div>
                {slackMappings.length === 0 ? (
                  <p className="text-xs text-surface-500">No linked Slack emails yet.</p>
                ) : (
                  <ul className="space-y-2">
                    {slackMappings.map((mapping) => (
                      <li
                        key={mapping.id}
                        className="flex items-center justify-between rounded-lg border border-surface-700/60 px-3 py-2 text-xs text-surface-200"
                      >
                        <div className="min-w-0">
                          <div className="truncate">{mapping.external_email ?? 'Unknown email'}</div>
                          <div className="text-[11px] text-surface-500">
                            {mapping.external_userid} · {mapping.match_source}
                          </div>
                        </div>
                        <button
                          onClick={() => void handleSlackDeleteMapping(mapping.id)}
                          className="ml-3 text-red-400 hover:text-red-300 text-xs"
                        >
                          Remove
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              {/* Close button */}
              <div className="flex justify-end mt-4 pt-4 border-t border-surface-700">
                <button
                  onClick={() => setShowSlackVerificationModal(false)}
                  className="px-4 py-2 text-sm font-medium text-surface-300 hover:text-surface-100 transition-colors"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Sharing Preferences Modal */}
      {sharingModal?.isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-surface-900 border border-surface-700 rounded-xl shadow-xl w-full max-w-md mx-4">
            <div className="p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-semibold text-surface-100">
                  {sharingModal.isInitialSetup
                    ? `${sharingModal.providerName} Connected`
                    : `${sharingModal.providerName} Sharing Settings`}
                </h2>
                <button
                  onClick={() => { setCalendarSharingWarningOpen(false); setSharingModal(null); }}
                  className="p-1 text-surface-400 hover:text-surface-200 rounded"
                >
                  <HiX className="w-5 h-5" />
                </button>
              </div>

              <p className="text-sm text-surface-400 mb-6">
                {sharingModal.isInitialSetup
                  ? 'Configure how your team can access data from this connection.'
                  : 'Update sharing settings for this integration.'}
              </p>

              <div className="space-y-4">
                <label className="flex items-start gap-3 cursor-pointer group">
                  <input
                    type="checkbox"
                    checked={sharingModal.shareSyncedData}
                    onChange={(e) => setSharingModal({ ...sharingModal, shareSyncedData: e.target.checked })}
                    className="mt-1 w-4 h-4 rounded border-surface-600 bg-surface-800 text-primary-500 focus:ring-primary-500 focus:ring-offset-0"
                  />
                  <div>
                    <div className="font-medium text-surface-100 group-hover:text-white">
                      Others can read
                    </div>
                    <div className="text-xs text-surface-500 mt-0.5">
                      When on: teammates and Basebase can see synced records (emails, meetings, etc.). When off: only you can see it.
                    </div>
                  </div>
                </label>

                <label className="flex items-start gap-3 cursor-pointer group">
                  <input
                    type="checkbox"
                    checked={sharingModal.shareQueryAccess}
                    onChange={(e) => setSharingModal({ ...sharingModal, shareQueryAccess: e.target.checked })}
                    className="mt-1 w-4 h-4 rounded border-surface-600 bg-surface-800 text-primary-500 focus:ring-primary-500 focus:ring-offset-0"
                  />
                  <div>
                    <div className="font-medium text-surface-100 group-hover:text-white">
                      Allow team to query live data
                    </div>
                    <div className="text-xs text-surface-500 mt-0.5">
                      Team can run queries using your connection (not recommended for personal data)
                    </div>
                  </div>
                </label>

                <label className="flex items-start gap-3 cursor-pointer group">
                  <input
                    type="checkbox"
                    checked={sharingModal.shareWriteAccess}
                    onChange={(e) => setSharingModal({ ...sharingModal, shareWriteAccess: e.target.checked })}
                    className="mt-1 w-4 h-4 rounded border-surface-600 bg-surface-800 text-primary-500 focus:ring-primary-500 focus:ring-offset-0"
                  />
                  <div>
                    <div className="font-medium text-surface-100 group-hover:text-white">
                      Allow team to write data
                    </div>
                    <div className="text-xs text-surface-500 mt-0.5">
                      Team can create/update records as you (rarely needed)
                    </div>
                  </div>
                </label>
              </div>

              {sharingError && (
                <p className="text-sm text-red-400 mt-4">{sharingError}</p>
              )}

              <div className="flex justify-end gap-3 mt-6 pt-4 border-t border-surface-700">
                <button
                  onClick={() => { setCalendarSharingWarningOpen(false); setSharingModal(null); }}
                  className="px-4 py-2 text-sm font-medium text-surface-300 hover:text-surface-100 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={() => void handleSaveSharing()}
                  disabled={sharingSaving}
                  className="px-4 py-2 text-sm font-medium bg-primary-600 hover:bg-primary-500 text-white rounded-lg disabled:opacity-50 transition-colors flex items-center gap-2"
                >
                  {sharingSaving && (
                    <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                  )}
                  {sharingModal.isInitialSetup ? 'Save & Start Sync' : 'Save Changes'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Calendar Sharing Warning Modal */}
      {calendarSharingWarningOpen && sharingModal && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 backdrop-blur-sm">
          <div className="bg-surface-900 border border-amber-500/40 rounded-xl shadow-2xl w-full max-w-lg mx-4">
            <div className="p-6">
              <div className="flex items-start justify-between gap-4 mb-4">
                <div>
                  <h2 className="text-lg font-semibold text-surface-100">
                    Share calendar data with your team?
                  </h2>
                  <p className="text-sm text-amber-300 mt-1">
                    This setting can expose personal calendar context.
                  </p>
                </div>
                <button
                  onClick={() => setCalendarSharingWarningOpen(false)}
                  className="p-1 text-surface-400 hover:text-surface-200 rounded"
                  aria-label="Close calendar sharing warning"
                >
                  <HiX className="w-5 h-5" />
                </button>
              </div>

              <p className="text-sm leading-6 text-surface-300">
                Checking this box will share your personal and private data with teams and may make mixed context items
                that have both private and shareable data shared — for example, private meeting notes on an otherwise
                public meeting.
              </p>

              <div className="flex justify-end gap-3 mt-6 pt-4 border-t border-surface-700">
                <button
                  onClick={() => setCalendarSharingWarningOpen(false)}
                  className="px-4 py-2 text-sm font-medium text-surface-300 hover:text-surface-100 transition-colors"
                >
                  Go Back
                </button>
                <button
                  onClick={() => void handleConfirmCalendarSharingWarning()}
                  disabled={sharingSaving}
                  className="px-4 py-2 text-sm font-medium bg-amber-600 hover:bg-amber-500 text-white rounded-lg disabled:opacity-50 transition-colors"
                >
                  I Understand, Share with Team
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Identity Mapping Wizard */}
      {identityMappingProvider && organizationId && (
        <IdentityMappingWizard
          organizationId={organizationId}
          provider={identityMappingProvider}
          onComplete={async () => {
            const provider: string = identityMappingProvider;
            setIdentityMappingProvider(null);
            if (organizationId) {
              const authHeaders = await getAuthenticatedRequestHeaders();
              void fetch(`${API_BASE}/sync/${organizationId}/${provider}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...authHeaders },
              });
            }
            void fetchIntegrations();
          }}
          onSkip={async () => {
            const provider: string = identityMappingProvider;
            setIdentityMappingProvider(null);
            if (organizationId) {
              const authHeaders = await getAuthenticatedRequestHeaders();
              void fetch(`${API_BASE}/sync/${organizationId}/${provider}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...authHeaders },
              });
            }
            void fetchIntegrations();
          }}
        />
      )}

    </div>
  );
}
