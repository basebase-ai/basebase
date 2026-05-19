/**
 * DataPage: tabbed hub for Documents, Apps, Workflows, Search Data, and Activity.
 * Consolidates multiple views into a single sidebar entry point.
 */

import { useState, Suspense, lazy } from 'react';
import { Data } from './Data';
import { Workflows } from './Workflows';
import { ActivityLog } from './ActivityLog';
import { useIsOrgAdmin } from '../store';

const AppsGallery = lazy(() => import('./apps/AppsGallery').then((m) => ({ default: m.AppsGallery })));
const DocumentsGallery = lazy(() => import('./documents/DocumentsGallery').then((m) => ({ default: m.DocumentsGallery })));

type DataTab = 'documents' | 'apps' | 'workflows' | 'search' | 'activity';

const LOADING_SPINNER: JSX.Element = (
  <div className="flex items-center justify-center h-64">
    <div className="animate-spin w-8 h-8 border-2 border-surface-500 border-t-primary-500 rounded-full" />
  </div>
);

export function DataPage(): JSX.Element {
  const isOrgAdmin: boolean = useIsOrgAdmin();
  const [activeTab, setActiveTab] = useState<DataTab>('documents');

  const tabs: readonly { id: DataTab; label: string; adminOnly?: boolean }[] = [
    { id: 'documents', label: 'Documents' },
    { id: 'apps', label: 'Apps' },
    { id: 'workflows', label: 'Workflows' },
    { id: 'search', label: 'Search Data' },
    { id: 'activity', label: 'Activity', adminOnly: true },
  ];

  const visibleTabs = tabs.filter((t) => !t.adminOnly || isOrgAdmin);

  return (
    <div className="flex flex-col h-full">
      <div className="flex border-b border-surface-800 px-6 sm:px-8 overflow-x-auto flex-shrink-0">
        {visibleTabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-3 text-sm font-medium transition-colors whitespace-nowrap ${
              activeTab === tab.id
                ? 'text-primary-400 border-b-2 border-primary-500'
                : 'text-surface-400 hover:text-surface-200'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto">
        {activeTab === 'documents' && (
          <Suspense fallback={LOADING_SPINNER}>
            <DocumentsGallery />
          </Suspense>
        )}
        {activeTab === 'apps' && (
          <Suspense fallback={LOADING_SPINNER}>
            <AppsGallery />
          </Suspense>
        )}
        {activeTab === 'workflows' && <Workflows />}
        {activeTab === 'search' && <Data />}
        {activeTab === 'activity' && isOrgAdmin && <ActivityLog />}
      </div>
    </div>
  );
}
