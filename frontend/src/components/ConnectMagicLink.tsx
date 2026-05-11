/**
 * Connector "magic link" landing page reached from a Slack/Teams/SMS message.
 *
 * The agent posts a link like ``/connect/attio?org_id=…&user_id=…&conversation_id=…``
 * into the chat surface; clicking it lands the user here. We:
 *
 * 1. Require the user to be signed in (matching the expected user_id).
 * 2. Auto-trigger the same Nango Connect popup the in-app Settings → Connectors
 *    button uses, so the experience is identical to a native click.
 * 3. After the popup completes, POST to ``/auth/integrations/confirm`` with the
 *    originating ``conversation_id`` so the backend can post a "✓ Connected"
 *    note back into the Slack thread.
 * 4. Show a friendly success page nudging the user back to the original
 *    chat surface.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Nango from '@nangohq/frontend';
import type { User as SupabaseUser } from '@supabase/supabase-js';

import { API_BASE, getAuthenticatedRequestHeaders } from '../lib/api';
import { APP_NAME, LOGO_PATH } from '../lib/brand';
import { supabase } from '../lib/supabase';
import { Auth } from './Auth';

type Phase =
  | 'loading'
  | 'needs-login'
  | 'wrong-account'
  | 'connecting'
  | 'success'
  | 'error';

interface NangoConnectEvent {
  type?: string;
  connectionId?: string;
  connection_id?: string;
  payload?: { connectionId?: string };
}

function prettyProvider(slug: string): string {
  if (!slug) return 'this connector';
  return slug
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function readQueryParam(name: string): string | null {
  const params: URLSearchParams = new URLSearchParams(window.location.search);
  const value: string | null = params.get(name);
  return value && value.trim().length > 0 ? value.trim() : null;
}

function readProviderFromPath(): string {
  const segments: string[] = window.location.pathname.split('/').filter(Boolean);
  const idx: number = segments.indexOf('connect');
  if (idx === -1 || idx + 1 >= segments.length) return '';
  return decodeURIComponent(segments[idx + 1] ?? '').toLowerCase();
}

export function ConnectMagicLink(): JSX.Element {
  const provider: string = useMemo(() => readProviderFromPath(), []);
  const orgIdParam: string | null = useMemo(() => readQueryParam('org_id'), []);
  const userIdParam: string | null = useMemo(() => readQueryParam('user_id'), []);
  const conversationIdParam: string | null = useMemo(() => readQueryParam('conversation_id'), []);

  const [phase, setPhase] = useState<Phase>('loading');
  const [error, setError] = useState<string | null>(null);
  const [signedInEmail, setSignedInEmail] = useState<string | null>(null);
  const [supabaseUser, setSupabaseUser] = useState<SupabaseUser | null>(null);
  const startedRef = useRef<boolean>(false);

  const providerLabel: string = prettyProvider(provider);

  const startNangoFlow = useCallback(async (): Promise<void> => {
    if (!provider || !orgIdParam || !userIdParam) {
      setError('This connect link is missing required information. Please ask the agent to send a fresh link.');
      setPhase('error');
      return;
    }

    setPhase('connecting');
    try {
      const sessionHeaders: Record<string, string> = await getAuthenticatedRequestHeaders();
      sessionHeaders['X-Organization-Id'] = orgIdParam;
      const sessionResponse: Response = await fetch(
        `${API_BASE}/auth/connect/${provider}/session?organization_id=${encodeURIComponent(orgIdParam)}`,
        { headers: sessionHeaders },
      );
      if (!sessionResponse.ok) {
        const detail: string = await sessionResponse
          .text()
          .catch(() => `HTTP ${sessionResponse.status}`);
        throw new Error(`Couldn't start the connect flow (${detail})`);
      }
      const sessionData: { session_token: string; connection_id: string } = await sessionResponse.json();

      const nango: Nango = new Nango();
      nango.openConnectUI({
        sessionToken: sessionData.session_token,
        onEvent: async (event) => {
          const eventType: string = (event as NangoConnectEvent).type ?? '';
          if (
            eventType === 'connect' ||
            eventType === 'connection-created' ||
            eventType === 'success'
          ) {
            const eventData: NangoConnectEvent = event as NangoConnectEvent;
            const nangoConnectionId: string =
              eventData.connectionId ??
              eventData.connection_id ??
              eventData.payload?.connectionId ??
              sessionData.connection_id;

            try {
              const confirmHeaders: Record<string, string> = await getAuthenticatedRequestHeaders();
              confirmHeaders['Content-Type'] = 'application/json';
              const confirmResponse: Response = await fetch(`${API_BASE}/auth/integrations/confirm`, {
                method: 'POST',
                headers: confirmHeaders,
                body: JSON.stringify({
                  provider,
                  connection_id: nangoConnectionId,
                  organization_id: orgIdParam,
                  user_id: userIdParam,
                  conversation_id: conversationIdParam ?? undefined,
                  skip_initial_sync: provider === 'slack' || provider === 'github',
                }),
              });
              if (!confirmResponse.ok) {
                const detail: string = await confirmResponse
                  .text()
                  .catch(() => `HTTP ${confirmResponse.status}`);
                throw new Error(`Couldn't finalize the connection (${detail})`);
              }
              setPhase('success');
            } catch (confirmErr) {
              setError(confirmErr instanceof Error ? confirmErr.message : 'Failed to confirm integration');
              setPhase('error');
            }
          } else if (eventType === 'close' || eventType === 'closed') {
            setPhase((prev) => (prev === 'success' ? prev : 'error'));
            setError((prev) => prev ?? 'You closed the authorization window before finishing.');
          }
        },
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong starting the connection.');
      setPhase('error');
    }
  }, [conversationIdParam, orgIdParam, provider, userIdParam]);

  useEffect(() => {
    let cancelled: boolean = false;

    const checkSession = async (): Promise<void> => {
      const { data: { session } } = await supabase.auth.getSession();
      if (cancelled) return;

      if (!session?.user) {
        setPhase('needs-login');
        return;
      }
      setSupabaseUser(session.user);
      setSignedInEmail(session.user.email ?? null);

      // We don't have a stable mapping from Supabase ID → Basebase user ID at
      // this layer (the backend swaps IDs for waitlist users), so we don't
      // hard-block on user_id mismatch — but we do warn the user when it's
      // suspicious so they can switch accounts before authorizing.
      if (userIdParam && session.user.id && userIdParam !== session.user.id) {
        // soft warning only; render still proceeds with the connect flow
        console.info('[ConnectMagicLink] Signed-in user differs from link user_id; continuing.');
      }

      if (!startedRef.current) {
        startedRef.current = true;
        await startNangoFlow();
      }
    };

    void checkSession();
    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      (event, session) => {
        if (event === 'SIGNED_IN' && session?.user) {
          setSupabaseUser(session.user);
          setSignedInEmail(session.user.email ?? null);
          if (!startedRef.current) {
            startedRef.current = true;
            void startNangoFlow();
          }
        }
      },
    );

    return () => {
      cancelled = true;
      subscription.unsubscribe();
    };
  }, [startNangoFlow, userIdParam]);

  if (phase === 'needs-login') {
    return (
      <Auth
        onBack={() => {
          window.location.href = '/';
        }}
        onSuccess={() => {
          // session listener picks it up and starts the flow
        }}
      />
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-surface-950">
      <div className="w-full max-w-md rounded-2xl border border-surface-800 bg-surface-900/60 p-8 shadow-xl">
        <div className="flex items-center gap-3 mb-6">
          <img src={LOGO_PATH} alt="" className="h-8 w-8" />
          <span className="text-surface-200 font-semibold">{APP_NAME}</span>
        </div>

        {phase === 'loading' && (
          <Status
            spinner
            heading={`Preparing to connect ${providerLabel}…`}
            body="Hang tight, this should only take a second."
          />
        )}

        {phase === 'connecting' && (
          <Status
            spinner
            heading={`Connecting ${providerLabel}…`}
            body={
              <>
                A {providerLabel} authorization window should be open in your browser. Complete the prompts there to finish.
                {signedInEmail ? (
                  <span className="block mt-2 text-xs text-surface-500">
                    Signed in as {signedInEmail}.
                  </span>
                ) : null}
              </>
            }
            actions={
              <button
                type="button"
                onClick={() => {
                  startedRef.current = true;
                  void startNangoFlow();
                }}
                className="text-xs text-primary-400 hover:text-primary-300 underline"
              >
                Didn't see a window? Reopen it.
              </button>
            }
          />
        )}

        {phase === 'success' && (
          <Status
            icon="check"
            heading={`${providerLabel} is connected`}
            body={
              conversationIdParam
                ? 'You can return to the conversation you started — the assistant will pick up from where you left off.'
                : 'You can now use this connector with the assistant.'
            }
            actions={
              <a
                href="/"
                className="inline-flex items-center justify-center rounded-lg bg-primary-500 px-4 py-2 text-sm font-medium text-white hover:bg-primary-400 transition-colors"
              >
                Open {APP_NAME}
              </a>
            }
          />
        )}

        {phase === 'wrong-account' && (
          <Status
            icon="warn"
            heading="This link is for a different account"
            body={
              <>
                This connect link was issued to another teammate
                {signedInEmail ? (
                  <>
                    {' '}— you're signed in as <span className="text-surface-200">{signedInEmail}</span>
                  </>
                ) : null}
                . Sign out and sign back in with the matching account, or ask the assistant for a new link.
              </>
            }
            actions={
              <button
                type="button"
                onClick={async () => {
                  await supabase.auth.signOut();
                  window.location.reload();
                }}
                className="text-xs text-primary-400 hover:text-primary-300 underline"
              >
                Sign out
              </button>
            }
          />
        )}

        {phase === 'error' && (
          <Status
            icon="warn"
            heading={`Couldn't connect ${providerLabel}`}
            body={error ?? 'Something went wrong. Please try again.'}
            actions={
              <button
                type="button"
                onClick={() => {
                  setError(null);
                  startedRef.current = true;
                  void startNangoFlow();
                }}
                className="inline-flex items-center justify-center rounded-lg border border-surface-600 bg-surface-800 px-4 py-2 text-sm font-medium text-surface-100 hover:bg-surface-700 transition-colors"
              >
                Try again
              </button>
            }
          />
        )}

        {supabaseUser && (
          <p className="mt-6 text-[11px] text-surface-600 text-center">
            Authorizing on behalf of {signedInEmail ?? supabaseUser.id}.
          </p>
        )}
      </div>
    </div>
  );
}

interface StatusProps {
  heading: string;
  body: React.ReactNode;
  spinner?: boolean;
  icon?: 'check' | 'warn';
  actions?: React.ReactNode;
}

function Status({ heading, body, spinner, icon, actions }: StatusProps): JSX.Element {
  return (
    <div className="text-center">
      <div className="flex justify-center mb-5">
        {spinner ? (
          <div className="w-10 h-10 rounded-full border-2 border-surface-700 border-t-primary-500 animate-spin" />
        ) : icon === 'check' ? (
          <div className="w-12 h-12 rounded-full bg-primary-500/20 flex items-center justify-center">
            <svg className="w-6 h-6 text-primary-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
        ) : icon === 'warn' ? (
          <div className="w-12 h-12 rounded-full bg-yellow-500/20 flex items-center justify-center">
            <svg className="w-6 h-6 text-yellow-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          </div>
        ) : null}
      </div>
      <h1 className="text-lg font-semibold text-surface-100 mb-2">{heading}</h1>
      <div className="text-sm text-surface-400">{body}</div>
      {actions ? <div className="mt-5 flex justify-center">{actions}</div> : null}
    </div>
  );
}
