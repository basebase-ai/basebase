/**
 * Collapsible sidebar navigation.
 *
 * Features:
 * - Org switcher with workspace links (Connectors, Apps, Workflows, etc.)
 * - New Chat button
 * - Recent chats list
 * - Organization identity (org switcher)
 * - Profile section
 */

import { useMemo, useState, useRef, useEffect, useCallback } from 'react';
import type { View, ChatSummary, OrganizationInfo } from './AppLayout';
import { useAppStore, useAuthStore, useChatStore, useIsGlobalAdmin, useIsOrgAdmin, useActiveTasksByConversation, type UserOrganization, type AdminPanelTab } from '../store';
import { apiRequest } from '../lib/api';
import { Avatar } from './Avatar';
import { ScopeLockIcon } from './ScopeVisibilityIcons';
import { APP_NAME, LOGO_PATH } from '../lib/brand';

const CHANNEL_PERSONALITY_MAX_LENGTH = 1000;
const CHANNEL_PERSONALITY_TEXTAREA_BASE_HEIGHT_PX = 160;
const CHANNEL_PERSONALITY_TEXTAREA_MAX_HEIGHT_PX = Math.round(CHANNEL_PERSONALITY_TEXTAREA_BASE_HEIGHT_PX * 1.5);

/** Shield icon for global admin console identity in the org switcher. */
function GlobalAdminShieldIcon({ className }: { className?: string }): JSX.Element {
  return (
    <svg className={className ?? 'w-5 h-5'} fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden>
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
    </svg>
  );
}

/** Single row in org dropdown for workspace (team) navigation. */
function OrgDropdownWorkspaceRow({
  label,
  icon,
  isActive,
  onSelect,
  badge,
  badgeColor = 'primary',
  colorTheme = 'surface',
}: {
  label: string;
  icon: JSX.Element;
  isActive: boolean;
  onSelect: () => void;
  badge?: number;
  badgeColor?: 'primary' | 'amber';
  colorTheme?: 'surface' | 'amber';
}): JSX.Element {
  const activeClass: string =
    colorTheme === 'amber'
      ? 'bg-amber-500/15 text-amber-300'
      : 'bg-surface-700 text-surface-100';
  const inactiveClass: string =
    colorTheme === 'amber'
      ? 'text-amber-400 hover:bg-amber-500/10 hover:text-amber-300'
      : 'text-surface-300 hover:bg-surface-700 hover:text-surface-100';
  const badgeBg: string = badgeColor === 'amber' ? 'bg-amber-500' : 'bg-primary-500';

  return (
    <button
      type="button"
      role="menuitem"
      onClick={onSelect}
      className={`w-full flex items-center gap-3 px-3 py-2 text-left text-sm transition-colors ${isActive ? activeClass : inactiveClass}`}
    >
      <span className="flex-shrink-0 w-5 h-5 flex items-center justify-center [&>svg]:w-4 [&>svg]:h-4">{icon}</span>
      <span className="truncate flex-1 min-w-0">{label}</span>
      {badge != null && badge > 0 ? (
        <span className={`shrink-0 min-w-[18px] h-[18px] px-1 rounded-full text-[10px] font-bold text-white flex items-center justify-center ${badgeBg}`}>
          {badge}
        </span>
      ) : null}
    </button>
  );
}

/** Organization switcher — displayed prominently at the top of the sidebar. */
/** Org identity row — toggles the in-sidebar org panel below it. */
function OrgSwitcherSection({
  organization,
  isMobile,
  currentView,
  panelOpen,
  onTogglePanel,
}: {
  organization: OrganizationInfo;
  isMobile: boolean;
  currentView: View;
  panelOpen: boolean;
  onTogglePanel: () => void;
}): JSX.Element {
  const isAdminConsole: boolean = currentView === 'admin';

  return (
    <div className="relative">
      <button
        type="button"
        onClick={onTogglePanel}
        aria-expanded={panelOpen}
        aria-label={panelOpen ? 'Hide workspace menu' : 'Show workspace menu'}
        className="w-full flex items-center gap-3 px-4 pt-3 pb-1 hover:bg-surface-800/50 transition-colors"
      >
        {isAdminConsole ? (
          <>
            <div className="w-9 h-9 rounded-lg bg-surface-800 flex items-center justify-center flex-shrink-0 self-start mt-0.5 text-amber-400">
              <GlobalAdminShieldIcon className="w-6 h-6" />
            </div>
            <div className="flex-1 min-w-0 text-left">
              <div className="text-lg font-semibold text-surface-100 truncate leading-tight">
                Global Admin
              </div>
            </div>
          </>
        ) : (
          <>
            {organization.logoUrl ? (
              <img
                src={organization.logoUrl}
                alt={organization.name}
                className="w-9 h-9 rounded-lg object-cover flex-shrink-0 self-start mt-0.5"
              />
            ) : (
              <div className="w-9 h-9 rounded-lg bg-surface-800 flex items-center justify-center flex-shrink-0 self-start mt-0.5">
                <img src={LOGO_PATH} alt={APP_NAME} className="w-6 h-6" />
              </div>
            )}
            <div className="flex-1 min-w-0 text-left">
              <div className="text-lg font-semibold text-surface-100 truncate leading-tight">
                {organization.name}
              </div>
            </div>
          </>
        )}
        <svg
          className={`w-4 h-4 text-surface-400 flex-shrink-0 transition-transform duration-200 ${panelOpen ? 'rotate-180' : ''}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          aria-hidden
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      <div className="pb-1" />
      {/* keep isMobile referenced (mobile-specific behavior may live here later) */}
      {isMobile ? null : null}
    </div>
  );
}

/** Org switcher + workspace nav, rendered in-place inside the sidebar body. */
function OrgPanel({
  currentView,
  onViewChange,
  onCreateNewOrg,
  connectedSourcesCount,
  workflowCount,
  pendingChangesCount,
  onClosePanel,
}: {
  currentView: View;
  onViewChange: (view: View) => void;
  onCreateNewOrg: () => void;
  connectedSourcesCount: number;
  workflowCount: number;
  pendingChangesCount: number;
  onClosePanel: () => void;
}): JSX.Element {
  const isGlobalAdmin: boolean = useIsGlobalAdmin();
  const isOrgAdmin: boolean = useIsOrgAdmin();
  const isAdminConsole: boolean = currentView === 'admin';
  const organizations: UserOrganization[] = useAppStore((state) => state.organizations);
  const switchActiveOrganization = useAppStore((state) => state.switchActiveOrganization);
  const fetchConversations = useAppStore((state) => state.fetchConversations);
  const fetchIntegrations = useAppStore((state) => state.fetchIntegrations);

  const handleSwitchOrg = useCallback(async (orgId: string): Promise<void> => {
    onClosePanel();
    useAuthStore.setState({ isSwitchingOrg: true });
    try {
      const switched: boolean = await switchActiveOrganization(orgId);
      if (!switched) {
        alert("You don't have access to that organization.");
        return;
      }
      await Promise.all([fetchConversations(), fetchIntegrations()]);
    } finally {
      useAuthStore.setState({ isSwitchingOrg: false });
    }
  }, [onClosePanel, switchActiveOrganization, fetchConversations, fetchIntegrations]);

  const handleEnterGlobalAdmin = useCallback((): void => {
    onClosePanel();
    useAuthStore.setState({
      organizations: organizations.map((o) => ({ ...o, isActive: false })),
    });
    onViewChange('admin');
  }, [onClosePanel, organizations, onViewChange]);

  const goTo = useCallback((view: View): void => {
    onClosePanel();
    onViewChange(view);
  }, [onClosePanel, onViewChange]);

  return (
    <div className="h-full overflow-y-auto scrollbar-thin px-2 pb-2" role="menu" aria-label="Workspace menu">
      <div className="text-[11px] uppercase tracking-wider text-surface-500 px-2 pt-1 pb-1 font-medium">
        Workspaces
      </div>
      <div className="space-y-0.5">
        {organizations.map((org) => (
          <button
            key={org.id}
            type="button"
            onClick={() => void handleSwitchOrg(org.id)}
            className={`w-full flex items-center gap-3 px-2 py-2 rounded-md text-left transition-colors ${
              org.isActive
                ? 'bg-primary-500/10 text-primary-400'
                : 'text-surface-300 hover:bg-surface-800/60'
            }`}
          >
            {org.logoUrl ? (
              <img src={org.logoUrl} alt={org.name} className="w-6 h-6 rounded object-cover flex-shrink-0" />
            ) : (
              <div className="w-6 h-6 rounded bg-surface-800 flex items-center justify-center flex-shrink-0">
                <img src={LOGO_PATH} alt={APP_NAME} className="w-4 h-4" />
              </div>
            )}
            <span className="text-sm truncate flex-1">{org.name}</span>
            {org.isActive && (
              <svg className="w-4 h-4 text-primary-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden>
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            )}
          </button>
        ))}
        <div className="flex items-center justify-between px-2 py-2">
          <span className="text-sm text-surface-400">New team</span>
          <button
            type="button"
            onClick={() => { onClosePanel(); onCreateNewOrg(); }}
            className="shrink-0 px-2.5 py-1 rounded-md bg-primary-600 hover:bg-primary-500 text-white text-xs font-medium transition-colors"
          >
            + Create
          </button>
        </div>
        {isGlobalAdmin && (
          <button
            type="button"
            onClick={handleEnterGlobalAdmin}
            className={`w-full flex items-center gap-3 px-2 py-2 rounded-md text-left transition-colors ${
              isAdminConsole
                ? 'bg-primary-500/10 text-primary-400'
                : 'text-surface-300 hover:bg-surface-800/60'
            }`}
          >
            <div className="w-6 h-6 rounded bg-surface-800 flex items-center justify-center flex-shrink-0 text-amber-400">
              <GlobalAdminShieldIcon className="w-4 h-4" />
            </div>
            <span className="text-sm truncate flex-1">Global Admin</span>
            {isAdminConsole && (
              <svg className="w-4 h-4 text-primary-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden>
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            )}
          </button>
        )}
      </div>

      {!isAdminConsole && (
        <>
          <div className="text-[11px] uppercase tracking-wider text-surface-500 px-2 pt-4 pb-1 font-medium">
            Workspace
          </div>
          <div className="space-y-0.5" role="group" aria-label="Workspace navigation">
            <OrgDropdownWorkspaceRow
              label="Home"
              isActive={currentView === 'home'}
              onSelect={() => goTo('home')}
              icon={
                <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden>
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
                </svg>
              }
            />
            <OrgDropdownWorkspaceRow
              label="All chats"
              isActive={currentView === 'chats'}
              onSelect={() => goTo('chats')}
              icon={
                <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden>
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                </svg>
              }
            />
            <OrgDropdownWorkspaceRow
              label="Connectors"
              badge={connectedSourcesCount}
              isActive={currentView === 'data-sources'}
              onSelect={() => goTo('data-sources')}
              icon={
                <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden>
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
                </svg>
              }
            />
            <OrgDropdownWorkspaceRow
              label="Search Data"
              isActive={currentView === 'data'}
              onSelect={() => goTo('data')}
              icon={
                <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden>
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 10h18M3 14h18m-9-4v8m-7 0h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
              }
            />
            <OrgDropdownWorkspaceRow
              label="Workflows"
              badge={workflowCount}
              isActive={currentView === 'workflows'}
              onSelect={() => goTo('workflows')}
              icon={
                <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden>
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
              }
            />
            <OrgDropdownWorkspaceRow
              label="Apps"
              isActive={currentView === 'apps' || currentView === 'app-view'}
              onSelect={() => goTo('apps')}
              icon={
                <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden>
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                </svg>
              }
            />
            <OrgDropdownWorkspaceRow
              label="Documents"
              isActive={currentView === 'documents' || currentView === 'artifact-view'}
              onSelect={() => goTo('documents')}
              icon={
                <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden>
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
              }
            />
            {isOrgAdmin && (
              <OrgDropdownWorkspaceRow
                label="Activity"
                isActive={currentView === 'activity-log'}
                onSelect={() => goTo('activity-log')}
                icon={
                  <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden>
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" />
                  </svg>
                }
              />
            )}
            <OrgDropdownWorkspaceRow
              label="Settings"
              isActive={currentView === 'org-settings'}
              onSelect={() => goTo('org-settings')}
              icon={
                <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden>
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
              }
            />
            {pendingChangesCount > 0 && (
              <OrgDropdownWorkspaceRow
                label="Changes"
                badge={pendingChangesCount}
                badgeColor="amber"
                colorTheme="amber"
                isActive={currentView === 'pending-changes'}
                onSelect={() => goTo('pending-changes')}
                icon={
                  <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden>
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                  </svg>
                }
              />
            )}
          </div>
        </>
      )}
    </div>
  );
}

interface SidebarProps {
  collapsed: boolean;
  onToggleCollapse: () => void;
  currentView: View;
  onViewChange: (view: View) => void;
  connectedSourcesCount: number;
  workflowCount: number;
  pendingChangesCount: number;
  recentChats: ChatSummary[];
  onSelectChat: (id: string) => void;
  currentChatId: string | null;
  onNewChat: () => void;
  organization: OrganizationInfo;
  onCreateNewOrg: () => void;
  onOpenProfilePanel: () => void;
  isMobile?: boolean;
  onCloseMobile?: () => void;
}

function GlobalAdminSidebarNavItem({
  label,
  collapsed,
  active,
  onClick,
  icon,
}: {
  label: string;
  collapsed: boolean;
  active: boolean;
  onClick: () => void;
  icon: JSX.Element;
}): JSX.Element {
  return (
    <button
      type="button"
      onClick={onClick}
      title={collapsed ? label : undefined}
      className={`w-full flex items-center gap-2 px-3 py-[5px] rounded-lg transition-colors ${
        active ? 'bg-surface-800 text-surface-100' : 'text-surface-300 hover:text-surface-200 hover:bg-surface-800/50'
      } ${collapsed ? 'justify-center' : ''}`}
    >
      {icon}
      {!collapsed && <span className="text-sm">{label}</span>}
    </button>
  );
}

const GLOBAL_ADMIN_NAV_ITEMS: ReadonlyArray<{
  id: AdminPanelTab;
  label: string;
  icon: JSX.Element;
}> = [
  {
    id: 'dashboard',
    label: 'Dashboard',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden>
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
      </svg>
    ),
  },
  {
    id: 'waitlist',
    label: 'Waitlist',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden>
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" />
      </svg>
    ),
  },
  {
    id: 'users',
    label: 'Users',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden>
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" />
      </svg>
    ),
  },
  {
    id: 'organizations',
    label: 'Teams',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden>
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
      </svg>
    ),
  },
  {
    id: 'sources',
    label: 'Sources & Health',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden>
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
      </svg>
    ),
  },
  {
    id: 'jobs',
    label: 'Running Jobs',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden>
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
      </svg>
    ),
  },
  {
    id: 'graph-magic',
    label: "Graph Magic",
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden>
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 19l6-6 4 4 6-10" />
      </svg>
    ),
  },
];

export function Sidebar({
  collapsed,
  // onToggleCollapse — kept in SidebarProps for future re-introduction
  currentView,
  onViewChange,
  connectedSourcesCount,
  workflowCount,
  pendingChangesCount,
  recentChats,
  onSelectChat,
  currentChatId,
  onNewChat,
  organization,
  onCreateNewOrg,
  onOpenProfilePanel,
  isMobile = false,
  onCloseMobile,
}: SidebarProps): JSX.Element {
  // Read user directly from store to ensure we always have the latest value
  const user = useAppStore((state) => state.user);
  const pinnedChatIds = useAppStore((state) => state.pinnedChatIds);
  const adminPanelTab = useAppStore((state) => state.adminPanelTab);
  const setAdminPanelTab = useAppStore((state) => state.setAdminPanelTab);
  const isGlobalAdmin = useIsGlobalAdmin();
  const activeTasksByConversation = useActiveTasksByConversation();
  const storedWidth = useAppStore((state) => state.sidebarWidth);
  const widthPx = collapsed ? 64 : storedWidth;

  const [panelMode, setPanelMode] = useState<'chats' | 'org'>('chats');
  const togglePanel = useCallback((): void => {
    setPanelMode((prev) => (prev === 'chats' ? 'org' : 'chats'));
  }, []);
  const closePanel = useCallback((): void => {
    setPanelMode('chats');
  }, []);

  const orderedChats = useMemo(() => {
    if (pinnedChatIds.length === 0) {
      return recentChats;
    }
    const pinnedSet = new Set(pinnedChatIds);
    const pinned = recentChats.filter((chat) => pinnedSet.has(chat.id));
    const unpinned = recentChats.filter((chat) => !pinnedSet.has(chat.id));
    return [...pinned, ...unpinned];
  }, [pinnedChatIds, recentChats]);

  return (
    <aside
      style={{ width: widthPx }}
      className="h-full bg-surface-950 flex flex-col transition-all duration-200 ease-in-out flex-shrink-0 overflow-hidden"
    >
      {/* Header: Organization identity */}
      <div className="relative min-w-0 overflow-hidden flex-shrink-0">
        <OrgSwitcherSection
          organization={organization}
          isMobile={isMobile}
          currentView={currentView}
          panelOpen={panelMode === 'org'}
          onTogglePanel={togglePanel}
        />
      </div>

      {currentView !== 'admin' && (
        <div className="relative flex-1 min-h-0">
          {/* Chats layer */}
          <div
            className={`absolute inset-0 flex flex-col transition-opacity duration-150 ${
              panelMode === 'chats' ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'
            }`}
            aria-hidden={panelMode !== 'chats'}
          >
            <div className={`px-3 py-2 flex-shrink-0 flex items-center gap-1.5 ${collapsed ? 'flex-col' : ''}`}>
              <button
                type="button"
                onClick={onNewChat}
                className={`flex-1 flex items-center gap-2 px-3 py-[5px] rounded-lg bg-primary-600 hover:bg-primary-700 text-white font-medium text-sm transition-colors ${collapsed ? 'w-full justify-center' : ''}`}
              >
                <svg className="w-5 h-5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden>
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
                {!collapsed && <span>New Chat</span>}
              </button>
              <button
                type="button"
                onClick={() => onViewChange('chats')}
                title="Search all chats"
                aria-label="Search all chats"
                className={`flex items-center justify-center rounded-lg text-surface-400 hover:text-surface-100 hover:bg-surface-800/60 transition-colors ${collapsed ? 'w-full py-[5px]' : 'h-8 w-8'}`}
              >
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden>
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
              </button>
            </div>

            <ChatAccordion
              collapsed={collapsed}
              orderedChats={orderedChats}
              currentChatId={currentChatId}
              activeTasksByConversation={activeTasksByConversation}
              onSelectChat={(id) => {
                onSelectChat(id);
                if (isMobile) onCloseMobile?.();
              }}
            />

            {collapsed && <div className="flex-1" />}
          </div>

          {/* Org / workspace layer */}
          {!collapsed && (
            <div
              className={`absolute inset-0 transition-opacity duration-150 ${
                panelMode === 'org' ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'
              }`}
              aria-hidden={panelMode !== 'org'}
            >
              <OrgPanel
                currentView={currentView}
                onViewChange={onViewChange}
                onCreateNewOrg={onCreateNewOrg}
                connectedSourcesCount={connectedSourcesCount}
                workflowCount={workflowCount}
                pendingChangesCount={pendingChangesCount}
                onClosePanel={closePanel}
              />
            </div>
          )}
        </div>
      )}

      {currentView === 'admin' && isGlobalAdmin && (
        <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
          <div className="px-2 py-2 overflow-y-auto scrollbar-thin flex-1">
            <nav className="space-y-0.5" aria-label="Global Admin sections">
              {GLOBAL_ADMIN_NAV_ITEMS.map((item) => (
                <GlobalAdminSidebarNavItem
                  key={item.id}
                  label={item.label}
                  collapsed={collapsed}
                  active={adminPanelTab === item.id}
                  onClick={() => setAdminPanelTab(item.id)}
                  icon={item.icon}
                />
              ))}
            </nav>
          </div>
        </div>
      )}

      {/* Bottom Section */}
      <div className="mt-auto">
        {user && (
          <button
            onClick={onOpenProfilePanel}
            className={`w-full flex items-center gap-3 px-4 py-3 hover:bg-surface-800/50 transition-colors ${collapsed ? 'justify-center' : ''}`}
          >
            <Avatar user={user} size="md" />
            {!collapsed && (
              <div className="flex-1 min-w-0 text-left">
                <div className="text-sm font-medium text-surface-200 truncate">
                  {user.name ?? 'User'}
                </div>
                <div className="text-xs text-surface-500 truncate">{user.email}</div>
              </div>
            )}
          </button>
        )}
      </div>
    </aside>
  );
}

function formatRelativeTime(date: Date): string {
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / (1000 * 60));
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString();
}

interface ChannelMemoryResponse {
  id: string;
  content: string;
}

function normalizeChannelIdForMemory(source: string | null | undefined, channelKey: string, normalizedChannelId?: string | null): string {
  const raw = (normalizedChannelId ?? '').trim() || channelKey.replace(/^channel:/, '').trim();
  if ((source ?? '').toLowerCase() === 'slack') {
    return raw.split(':', 1)[0] ?? raw;
  }
  return raw;
}

/** Recent chats: shared + private in one list (recency), pinned first; lock marks private. Row actions live in the chat ⋮ menu. */
function ChatAccordion({
  collapsed,
  orderedChats,
  currentChatId,
  activeTasksByConversation,
  onSelectChat,
}: {
  collapsed: boolean;
  orderedChats: ChatSummary[];
  currentChatId: string | null;
  activeTasksByConversation: Record<string, string>;
  onSelectChat: (id: string) => void;
}): JSX.Element | null {
  const hoverTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [collapsedSections, setCollapsedSections] = useState<Record<string, boolean>>({});
  const [channelPersonalityTarget, setChannelPersonalityTarget] = useState<{
    key: string;
    label: string;
    source: string | null;
    normalizedChannelId: string;
  } | null>(null);
  const prefetchConversation = useAppStore((s) => s.prefetchConversation);
  const pinnedChatIds = useAppStore((s) => s.pinnedChatIds);
  const organizationId = useAppStore((s) => s.organization?.id ?? null);
  const unreadConversationIds = useChatStore((s) => s.unreadConversationIds);

  useEffect(() => {
    return () => { if (hoverTimerRef.current) clearTimeout(hoverTimerRef.current); };
  }, []);

  const groupedSidebarChats = useMemo(() => {
    const pinnedSet = new Set(pinnedChatIds);
    const sorted = [...orderedChats].sort(
      (a, b) => b.lastMessageAt.getTime() - a.lastMessageAt.getTime(),
    );
    const direct: ChatSummary[] = [];
    const uncategorized: ChatSummary[] = [];
    const channels = new Map<string, {
      label: string;
      source: string | null;
      normalizedChannelId: string | null;
      chats: ChatSummary[];
      newestTs: number;
    }>();
    const pinned: ChatSummary[] = [];
    for (const chat of sorted) {
      const ts = chat.lastMessageAt.getTime();
      if (pinnedSet.has(chat.id)) pinned.push(chat);
      const bucket = chat.groupBucketType ?? 'uncategorized';
      if (bucket === 'direct') {
        direct.push(chat);
        continue;
      }
      if (bucket === 'channel' && chat.groupBucketKey) {
        const current = channels.get(chat.groupBucketKey) ?? {
          label: chat.resolvedChannelName ?? chat.normalizedChannelId ?? 'Channel',
          source: chat.source ?? null,
          normalizedChannelId: chat.normalizedChannelId ?? null,
          chats: [],
          newestTs: 0,
        };
        current.chats.push(chat);
        current.newestTs = Math.max(current.newestTs, ts);
        channels.set(chat.groupBucketKey, current);
        continue;
      }
      uncategorized.push(chat);
    }
    const globalLimit = 50;
    const byNewest = (a: ChatSummary, b: ChatSummary): number => b.lastMessageAt.getTime() - a.lastMessageAt.getTime();
    const channelSections = Array.from(channels.entries())
      .map(([key, value]) => ({
        key,
        label: value.label,
        source: value.source,
        normalizedChannelId: value.normalizedChannelId,
        chats: value.chats.sort(byNewest),
        newestTs: value.newestTs,
      }))
      .sort((a, b) => b.newestTs - a.newestTs);
    const flattenCount =
      pinned.length +
      direct.length +
      uncategorized.length +
      channelSections.reduce((acc, c) => acc + c.chats.length, 0);
    let remaining = globalLimit;
    const take = (items: ChatSummary[]): ChatSummary[] => {
      if (remaining <= 0) return [];
      const selected = items.slice(0, remaining);
      remaining -= selected.length;
      return selected;
    };
    const limitedPinned = take(pinned.sort(byNewest));
    const limitedDirect = take(direct.sort(byNewest));
    const limitedChannels = channelSections
      .map((section) => ({ ...section, chats: take(section.chats) }))
      .filter((section) => section.chats.length > 0);
    const limitedUncategorized = take(uncategorized.sort(byNewest));
    return {
      pinned: limitedPinned,
      direct: limitedDirect,
      uncategorized: limitedUncategorized,
      channels: limitedChannels,
      flattenCount,
    };
  }, [orderedChats, pinnedChatIds]);

  if (collapsed) return null;

  const isSectionCollapsed = (sectionKey: string): boolean => {
    const explicit = collapsedSections[sectionKey];
    if (typeof explicit === 'boolean') return explicit;
    return sectionKey !== 'direct';
  };

  const toggleSection = (sectionKey: string): void => {
    setCollapsedSections((prev) => ({
      ...prev,
      [sectionKey]:
        typeof prev[sectionKey] === 'boolean'
          ? !prev[sectionKey]
          : sectionKey === 'direct',
    }));
  };

  const renderChatItem = (chat: ChatSummary, itemKey: string): JSX.Element => {
    const hasActiveTask = chat.id in activeTasksByConversation;
    const isUnread = unreadConversationIds.has(chat.id);

    const isActive: boolean = currentChatId === chat.id;
    const hasParticipants: boolean =
      chat.scope === 'shared' && (chat.participants?.length ?? 0) > 0;

    return (
      <div
        key={itemKey}
        className={`group/chat relative w-full text-left px-2 py-1.5 rounded-md transition-colors cursor-pointer leading-tight ${
          isActive
            ? 'bg-surface-800 text-surface-100'
            : 'text-surface-400 hover:text-surface-200 hover:bg-surface-800/50'
        }`}
        onClick={() => onSelectChat(chat.id)}
        onMouseEnter={() => {
          if (isActive) return;
          hoverTimerRef.current = setTimeout(() => prefetchConversation(chat.id), 100);
        }}
        onMouseLeave={() => {
          if (hoverTimerRef.current) { clearTimeout(hoverTimerRef.current); hoverTimerRef.current = null; }
        }}
      >
        <div className="flex items-center gap-1.5 min-w-0">
          {chat.scope === 'private' && (
            <span className="flex shrink-0 text-surface-500" title="Private">
              <ScopeLockIcon className="w-3 h-3" />
            </span>
          )}
          {chat.type === 'workflow' && (
            <svg className="w-3.5 h-3.5 text-amber-500 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          )}
          <div className="truncate text-[15px] flex-1 leading-tight">
            {chat.title}
          </div>
          {isUnread && (
            <span
              className="h-2.5 w-2.5 shrink-0 rounded-full bg-primary-500 [background-image:none]"
              title="Unread"
              aria-label="Unread"
            />
          )}
          {hasActiveTask && (
            <svg className="w-3 h-3 text-primary-400 flex-shrink-0 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
          )}
          <div className="hidden group-hover/chat:flex items-center gap-1.5 leading-none flex-shrink-0">
            <span className="text-xs text-surface-500">
              {formatRelativeTime(chat.lastMessageAt)}
            </span>
            {hasParticipants && (
              <div className="flex -space-x-1">
                {chat.participants!.slice(0, 3).map((p, idx) => (
                  <Avatar
                    key={p.id}
                    user={p}
                    size="xs"
                    bordered
                    className="!w-4 !h-4 !text-[8px]"
                    style={{ zIndex: 3 - idx }}
                  />
                ))}
                {chat.participants!.length > 3 && (
                  <div
                    className="w-4 h-4 rounded-full border border-surface-700 dark:border-surface-600 bg-surface-700 flex items-center justify-center text-[8px] font-medium text-surface-300"
                    title={`${chat.participants!.length - 3} more`}
                  >
                    +{chat.participants!.length - 3}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  };
  
  return (
    <div className="flex-1 flex flex-col min-h-0 px-3 pt-1 pb-px">
      <div className="flex-1 overflow-y-auto scrollbar-thin space-y-0 min-h-0">
        {groupedSidebarChats.flattenCount > 0 ? (
          <>
            {groupedSidebarChats.pinned.length > 0 && (
              <>
                <SidebarSectionHeader
                  title="Pinned"
                  collapsed={isSectionCollapsed('pinned')}
                  onToggle={() => toggleSection('pinned')}
                />
                {!isSectionCollapsed('pinned') && groupedSidebarChats.pinned.map((chat) => renderChatItem(chat, `pinned-${chat.id}`))}
              </>
            )}
            {groupedSidebarChats.direct.length > 0 && (
              <>
                <SidebarSectionHeader
                  title="Direct"
                  collapsed={isSectionCollapsed('direct')}
                  onToggle={() => toggleSection('direct')}
                />
                {!isSectionCollapsed('direct') && groupedSidebarChats.direct.map((chat) => renderChatItem(chat, `direct-${chat.id}`))}
              </>
            )}
            {groupedSidebarChats.channels.map((channel) => (
              <div key={channel.key}>
                <SidebarSectionHeader
                  title={channel.label}
                  collapsed={isSectionCollapsed(`channel:${channel.key}`)}
                  onToggle={() => toggleSection(`channel:${channel.key}`)}
                  onOptionsClick={() => {
                    const normalizedChannelId = normalizeChannelIdForMemory(
                      channel.source,
                      channel.key,
                      channel.normalizedChannelId,
                    );
                    setChannelPersonalityTarget({
                      key: channel.key,
                      label: channel.label,
                      source: channel.source,
                      normalizedChannelId,
                    });
                  }}
                />
                {!isSectionCollapsed(`channel:${channel.key}`) &&
                  channel.chats.map((chat) => renderChatItem(chat, `channel-${channel.key}-${chat.id}`))}
              </div>
            ))}
            {groupedSidebarChats.uncategorized.length > 0 && (
              <>
                <SidebarSectionHeader
                  title="Uncategorized"
                  collapsed={isSectionCollapsed('uncategorized')}
                  onToggle={() => toggleSection('uncategorized')}
                />
                {!isSectionCollapsed('uncategorized') &&
                  groupedSidebarChats.uncategorized.map((chat) => renderChatItem(chat, `uncategorized-${chat.id}`))}
              </>
            )}
          </>
        ) : (
          <div className="px-2 py-1.5 text-xs text-surface-500 text-center">
            No conversations yet
          </div>
        )}
      </div>
      {channelPersonalityTarget && (
        <ChannelPersonalityPanel
          organizationId={organizationId}
          channelName={channelPersonalityTarget.label}
          source={channelPersonalityTarget.source}
          normalizedChannelId={channelPersonalityTarget.normalizedChannelId}
          onClose={() => setChannelPersonalityTarget(null)}
        />
      )}
    </div>
  );
}

function SidebarSectionHeader({
  title,
  collapsed,
  onToggle,
  onOptionsClick,
}: {
  title: string;
  collapsed: boolean;
  onToggle: () => void;
  onOptionsClick?: () => void;
}): JSX.Element {
  return (
    <div className="px-1 pt-2 pb-1 flex items-center gap-1">
      <button
        type="button"
        onClick={onToggle}
        className="flex-1 min-w-0 px-1 py-0.5 rounded-md hover:bg-surface-800/60 transition-colors flex items-center gap-1.5 text-left"
        aria-expanded={!collapsed}
        aria-label={`${collapsed ? 'Expand' : 'Collapse'} ${title}`}
      >
        <svg
          className={`w-3 h-3 text-surface-500 transition-transform ${collapsed ? '' : 'rotate-90'}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
        <h3 className="truncate text-[10px] uppercase tracking-wider text-surface-500 font-semibold">{title}</h3>
      </button>
      {onOptionsClick && (
        <button
          type="button"
          className="p-1 rounded-md text-surface-500 hover:bg-surface-800/60 hover:text-surface-300 transition-colors"
          aria-label={`${title} options`}
          onClick={onOptionsClick}
        >
          <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="5" cy="12" r="1.8" />
            <circle cx="12" cy="12" r="1.8" />
            <circle cx="19" cy="12" r="1.8" />
          </svg>
        </button>
      )}
    </div>
  );
}

function ChannelPersonalityPanel({
  organizationId,
  channelName,
  source,
  normalizedChannelId,
  onClose,
}: {
  organizationId: string | null;
  channelName: string;
  source: string | null;
  normalizedChannelId: string;
  onClose: () => void;
}): JSX.Element {
  const [draft, setDraft] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isDirty, setIsDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lastSavedRef = useRef('');
  const saveTimeoutRef = useRef<number | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = `${CHANNEL_PERSONALITY_TEXTAREA_BASE_HEIGHT_PX}px`;
    textarea.style.height = `${Math.min(textarea.scrollHeight, CHANNEL_PERSONALITY_TEXTAREA_MAX_HEIGHT_PX)}px`;
  }, [draft, isLoading]);

  useEffect(() => {
    let isActive = true;
    const load = async (): Promise<void> => {
      if (!organizationId || !source || !normalizedChannelId) {
        setError('Channel identity is unavailable for this section.');
        return;
      }
      setIsLoading(true);
      setError(null);
      const params = new URLSearchParams({
        source: source.toLowerCase(),
        channel_id: normalizedChannelId,
      });
      const { data, error: requestError } = await apiRequest<ChannelMemoryResponse | null>(`/memories/${organizationId}/channel?${params.toString()}`);
      if (!isActive) return;
      if (requestError) {
        setError(requestError);
      } else {
        const nextValue = data?.content ?? '';
        setDraft(nextValue);
        lastSavedRef.current = nextValue;
      }
      setIsDirty(false);
      setIsLoading(false);
    };
    void load();
    return () => {
      isActive = false;
      if (saveTimeoutRef.current) {
        window.clearTimeout(saveTimeoutRef.current);
      }
    };
  }, [organizationId, source, normalizedChannelId]);

  useEffect(() => {
    if (!isDirty || isLoading || !organizationId || !source || !normalizedChannelId) {
      return;
    }
    if (saveTimeoutRef.current) {
      window.clearTimeout(saveTimeoutRef.current);
    }
    saveTimeoutRef.current = window.setTimeout(() => {
      const persist = async (): Promise<void> => {
        if (draft.length > CHANNEL_PERSONALITY_MAX_LENGTH) return;
        const normalizedSource = source.toLowerCase();
        const trimmed = draft.trim();
        if (trimmed === lastSavedRef.current.trim()) {
          setIsDirty(false);
          return;
        }
        setIsSaving(true);
        setError(null);
        const params = new URLSearchParams({
          source: normalizedSource,
          channel_id: normalizedChannelId,
        });
        const endpoint = `/memories/${organizationId}/channel?${params.toString()}`;
        const result = trimmed
          ? await apiRequest<ChannelMemoryResponse>(endpoint, {
            method: 'PUT',
            body: JSON.stringify({ content: trimmed }),
          })
          : await apiRequest<{ status: string; memory_id: string }>(endpoint, { method: 'DELETE' });
        if (result.error) {
          setError(result.error);
          setIsDirty(false);
        } else {
          lastSavedRef.current = trimmed;
          setIsDirty(false);
        }
        setIsSaving(false);
      };
      void persist();
    }, 700);
    return () => {
      if (saveTimeoutRef.current) {
        window.clearTimeout(saveTimeoutRef.current);
      }
    };
  }, [draft, isDirty, isLoading, organizationId, source, normalizedChannelId]);

  return (
    <>
      <div className="fixed inset-0 bg-black/50 z-40" onClick={onClose} />
      <div className="fixed right-0 top-0 bottom-0 w-full max-w-md bg-surface-900 z-50 flex flex-col shadow-2xl">
        <header className="flex items-center justify-between px-6 py-4">
          <h2 className="font-semibold text-surface-100 truncate">{channelName}</h2>
          <button
            onClick={onClose}
            className="p-2 text-surface-400 hover:text-surface-200 hover:bg-surface-800 rounded-lg transition-colors"
            aria-label="Close channel personality panel"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </header>

        <div className="p-6 space-y-3">
          <div className="text-xs uppercase tracking-wide text-primary-300">Channel personality</div>
          <p className="text-xs text-surface-400">Applied on replies in this channel. Maximum {CHANNEL_PERSONALITY_MAX_LENGTH} characters.</p>
          {isLoading ? (
            <p className="text-sm text-surface-400">Loading channel personality...</p>
          ) : (
            <>
              <textarea
                ref={textareaRef}
                className="w-full rounded-lg bg-surface-800 border border-surface-700 px-3 py-2 text-sm text-surface-100 overflow-y-auto"
                value={draft}
                onChange={(e) => {
                  setDraft(e.target.value);
                  setIsDirty(true);
                }}
                style={{
                  minHeight: `${CHANNEL_PERSONALITY_TEXTAREA_BASE_HEIGHT_PX}px`,
                  maxHeight: `${CHANNEL_PERSONALITY_TEXTAREA_MAX_HEIGHT_PX}px`,
                }}
                placeholder="e.g. Keep answers concise, action-oriented, and include channel-specific context."
                maxLength={CHANNEL_PERSONALITY_MAX_LENGTH}
              />
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs text-surface-500">
                  {draft.length}/{CHANNEL_PERSONALITY_MAX_LENGTH}
                </span>
                {isSaving && <span className="text-xs text-surface-500">Saving...</span>}
              </div>
            </>
          )}
          {error && <p className="text-xs text-red-400">{error}</p>}
        </div>
      </div>
    </>
  );
}
