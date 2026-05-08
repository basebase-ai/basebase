/**
 * AppPreview — universal app preview component.
 *
 * List views must never render live apps: they show the last stored screenshot
 * captured when the app was opened/created, falling back to a static icon.
 */

import { useEffect, useState } from 'react';
import { apiRequest } from '../../lib/api';
import type { WidgetConfig } from '../../store/types';

type PreviewMode = 'auto' | 'screenshot' | 'widget' | 'mini_app' | 'icon';

interface AppPreviewProps {
  appId: string;
  appTitle: string;
  widgetConfig?: WidgetConfig | null;
  onClick?: (appId: string) => void;
}

function ScreenshotView({ src, title }: { src: string; title: string }): JSX.Element {
  return (
    <img src={src} alt={title} className="w-full h-full object-cover object-top" />
  );
}

function DefaultIcon({ title }: { title: string }): JSX.Element {
  return (
    <div className="flex flex-col items-center justify-center flex-1 gap-2">
      <svg className="w-8 h-8 text-surface-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path
          strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
          d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
        />
      </svg>
      <span className="text-xs text-surface-400 truncate max-w-full">{title}</span>
    </div>
  );
}

export function AppPreview({ appId, appTitle, widgetConfig, onClick }: AppPreviewProps): JSX.Element {
  // Use preferred_mode from widgetConfig as the default mode
  const defaultMode: PreviewMode = widgetConfig?.preferred_mode ?? 'auto';

  // Screenshot: inline data URL or has_screenshot flag (stripped from list responses)
  const hasScreenshotFlag = Boolean(
    widgetConfig?.screenshot || widgetConfig?.has_screenshot
  );
  const hasWidget = Boolean(widgetConfig?.layout);
  const [screenshotUrl, setScreenshotUrl] = useState<string | null>(
    widgetConfig?.screenshot ?? null
  );

  // Lazy-fetch screenshot on demand when flag is set but no inline URL
  useEffect(() => {
    if (screenshotUrl || !hasScreenshotFlag || widgetConfig?.screenshot) return;
    let cancelled = false;
    apiRequest<{ screenshot: string | null }>(`/apps/widgets/${appId}/screenshot`).then((resp) => {
      if (!cancelled && resp.data?.screenshot) setScreenshotUrl(resp.data.screenshot);
    });
    return () => { cancelled = true; };
  }, [appId, hasScreenshotFlag, screenshotUrl, widgetConfig?.screenshot]);

  // List previews are static snapshots only. Even if a user previously chose
  // widget/mini_app as their preview mode, do not execute app code or queries here.
  const effectiveMode: 'screenshot' | 'icon' =
    defaultMode !== 'icon' && hasScreenshotFlag && screenshotUrl ? 'screenshot' : 'icon';

  useEffect(() => {
    if (hasWidget && defaultMode === 'widget') {
      console.debug('[AppPreview] Widget preview mode requested in list view; using stored screenshot instead', {
        appId,
        hasScreenshot: Boolean(screenshotUrl),
      });
    }
    if (defaultMode === 'mini_app') {
      console.debug('[AppPreview] Mini-app preview mode requested in list view; live render is disabled', {
        appId,
        hasScreenshot: Boolean(screenshotUrl),
      });
    }
  }, [appId, defaultMode, hasWidget, screenshotUrl]);

  return (
    <button
      onClick={() => onClick?.(appId)}
      className="flex flex-col bg-surface-900 border border-surface-800 rounded-xl overflow-hidden aspect-video w-full hover:border-surface-600 hover:bg-surface-800/50 transition-colors text-left cursor-pointer"
    >
      {effectiveMode === 'screenshot' && screenshotUrl ? (
        <ScreenshotView src={screenshotUrl} title={appTitle} />
      ) : (
        <DefaultIcon title={appTitle} />
      )}
    </button>
  );
}
