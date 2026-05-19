/**
 * Home view - displays a custom app when configured for the org, otherwise a setup prompt.
 */

import { useCallback, useEffect, useState } from 'react';
import { apiRequest } from '../lib/api';
import { useAppStore, useIntegrations } from '../store';
import { SandpackAppRenderer } from './apps/SandpackAppRenderer';
import { HomeAppPicker } from './apps/HomeAppPicker';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface HomeAppData {
  id: string;
  title: string;
  description: string | null;
  frontendCode: string;
  frontendCodeCompiled?: string | null;
}

// ---------------------------------------------------------------------------
// Home Component
// ---------------------------------------------------------------------------

export function Home(): JSX.Element {
  const organization = useAppStore((state) => state.organization);
  const setCurrentView = useAppStore((state) => state.setCurrentView);

  const [homeApp, setHomeApp] = useState<HomeAppData | null>(null);
  const [homeAppLoading, setHomeAppLoading] = useState<boolean>(true);
  const [showPicker, setShowPicker] = useState<boolean>(false);
  const [orgAppCount, setOrgAppCount] = useState<number>(0);

  const integrations = useIntegrations();
  const hasConnectedSources: boolean = integrations.some((i) => i.isActive);

  useEffect(() => {
    setHomeApp(null);
    setHomeAppLoading(true);
    setOrgAppCount(0);
    const fetchHomeApp = async (): Promise<void> => {
      const resp = await apiRequest<{ app: HomeAppData | null; app_count: number }>('/apps/home');
      if (resp.data) {
        setHomeApp(resp.data.app);
        setOrgAppCount(resp.data.app_count);
      }
      setHomeAppLoading(false);
    };
    void fetchHomeApp();
  }, [organization?.id]);

  const handleAppSelected = useCallback((appId: string | null) => {
    if (appId === null) {
      setHomeApp(null);
    }
    setShowPicker(false);
    const reload = async (): Promise<void> => {
      const resp = await apiRequest<{ app: HomeAppData | null; app_count: number }>('/apps/home');
      if (resp.data) {
        setHomeApp(resp.data.app);
        setOrgAppCount(resp.data.app_count);
      }
    };
    void reload();
  }, []);

  if (homeAppLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="flex items-center gap-3 text-surface-400">
          <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
          </svg>
          <span>Loading...</span>
        </div>
      </div>
    );
  }

  if (homeApp !== null) {
    return (
      <div className="flex-1 flex flex-col overflow-hidden">
        <header className="hidden md:flex h-14 border-b border-surface-800 items-center justify-between px-4 md:px-6">
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-semibold text-surface-100">{homeApp.title}</h1>
            <span className="px-1.5 py-0.5 text-[10px] font-medium bg-primary-500/20 text-primary-400 rounded">
              Home App
            </span>
          </div>
          <button
            onClick={() => setShowPicker(true)}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md hover:bg-surface-800 text-surface-400 hover:text-surface-200 transition-colors text-xs"
            title="Customize Home"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            Customize
          </button>
        </header>

        <div className="flex-1 overflow-hidden">
          <SandpackAppRenderer
            appId={homeApp.id}
            frontendCode={homeApp.frontendCode}
            frontendCodeCompiled={homeApp.frontendCodeCompiled}
          />
        </div>

        {showPicker && (
          <HomeAppPicker
            currentAppId={homeApp.id}
            onSelect={handleAppSelected}
            onClose={() => setShowPicker(false)}
          />
        )}
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <header className="hidden md:flex h-14 border-b border-surface-800 items-center justify-between px-4 md:px-6">
        <h1 className="text-lg font-semibold text-surface-100">Home</h1>
        {orgAppCount > 0 && (
          <button
            onClick={() => setShowPicker(true)}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md hover:bg-surface-800 text-surface-400 hover:text-surface-200 transition-colors text-xs"
            title="Customize Home"
          >
            Customize Home
          </button>
        )}
      </header>

      <div className="flex-1 overflow-auto flex flex-col items-center justify-center px-6 py-12 text-center">
        {!hasConnectedSources && (
          <div className="mb-8 max-w-md">
            <h3 className="text-base md:text-lg font-semibold text-surface-100 mb-2">
              Connect your connectors to get started
            </h3>
            <p className="text-surface-400 text-sm mb-4">
              Link your CRM, calendar, and email to unlock AI-powered insights about your revenue pipeline.
            </p>
            <button
              onClick={() => {
                window.dispatchEvent(new CustomEvent('navigate', { detail: 'data-sources' }));
              }}
              className="inline-flex items-center gap-2 px-4 py-2 bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium rounded-lg transition-colors"
            >
              Connect Integrations
            </button>
          </div>
        )}

        <svg className="w-12 h-12 text-surface-600 mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z" />
        </svg>
        <h2 className="text-surface-200 font-medium mb-2">No Home app configured</h2>
        <p className="text-surface-500 text-sm max-w-sm mb-6">
          Your organization&apos;s Daily Digest runs overnight via Workflows and stores results in{' '}
          <code className="text-surface-400">temp_data</code>. Pick a Home app (or run the migration)
          to view the digest here.
        </p>
        <div className="flex flex-wrap gap-3 justify-center">
          {orgAppCount > 0 ? (
            <button
              type="button"
              onClick={() => setShowPicker(true)}
              className="btn-primary text-sm"
            >
              Choose Home app
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => setCurrentView('workflows')}
            className="btn-secondary text-sm"
          >
            View Workflows
          </button>
        </div>
      </div>

      {showPicker && (
        <HomeAppPicker
          currentAppId={null}
          onSelect={handleAppSelected}
          onClose={() => setShowPicker(false)}
        />
      )}
    </div>
  );
}
