/**
 * Get help / contact support trigger.
 *
 * Renders an inline row trigger (icon + label) and a modal that posts a
 * message to /support/request. Designed to live in account/profile menus
 * where users expect to find help (Linear / Notion / Slack pattern).
 */

import { useCallback, useState } from 'react';
import { apiRequest } from '../lib/api';

interface HelpButtonProps {
  /** Optional className applied to the trigger row. */
  triggerClassName?: string;
  /** Override the label shown in the trigger row (default: "Get help"). */
  label?: string;
}

export function HelpButton({ triggerClassName, label = 'Get help' }: HelpButtonProps): JSX.Element {
  const [showModal, setShowModal] = useState<boolean>(false);
  const [message, setMessage] = useState<string>('');
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [success, setSuccess] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = useCallback(async (): Promise<void> => {
    const trimmed: string = message.trim();
    if (!trimmed || submitting) return;
    setSubmitting(true);
    setError(null);
    const { error: err } = await apiRequest<{ status: string; detail: string }>('/support/request', {
      method: 'POST',
      body: JSON.stringify({ message: trimmed }),
    });
    setSubmitting(false);
    if (err) {
      setError(err);
      return;
    }
    setSuccess(true);
    setMessage('');
  }, [message, submitting]);

  const handleClose = useCallback((): void => {
    setShowModal(false);
    setSuccess(false);
    setError(null);
    setMessage('');
  }, []);

  const defaultTriggerClass: string =
    'w-full flex items-center justify-center gap-2 px-4 py-3 text-surface-300 hover:text-surface-100 hover:bg-surface-800 rounded-lg transition-colors font-medium';

  return (
    <>
      <button
        type="button"
        onClick={() => setShowModal(true)}
        className={triggerClassName ?? defaultTriggerClass}
      >
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden>
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093M12 17h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        {label}
      </button>
      {showModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onClick={(e) => { if (e.target === e.currentTarget) handleClose(); }}
        >
          <div
            className="bg-surface-900 rounded-xl shadow-2xl ring-1 ring-white/10 max-w-md w-full p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-surface-100">Get help</h2>
              <button
                type="button"
                onClick={handleClose}
                className="p-1 text-surface-400 hover:text-surface-200 rounded transition-colors"
                aria-label="Close"
              >
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            {success ? (
              <p className="text-sm text-surface-300 mb-4">
                Your message has been sent. A team member will be notified immediately and will respond within a few minutes during business hours.
              </p>
            ) : (
              <>
                <p className="text-sm text-surface-300 mb-4">
                  You&apos;re our partner in building this product. Share questions, feedback, feature requests, or suggestions of any kind—we read every message and respond within a few minutes during business hours.
                </p>
                <textarea
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  placeholder="Questions, feedback, feature requests, or suggestions..."
                  rows={4}
                  className="w-full px-3 py-2 rounded-lg bg-surface-800 border border-surface-700 text-surface-100 placeholder-surface-500 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent resize-none mb-4"
                  maxLength={4000}
                />
                {error && <p className="text-sm text-red-400 mb-2">{error}</p>}
              </>
            )}
            <div className="flex justify-end gap-2">
              {success ? (
                <button
                  type="button"
                  onClick={handleClose}
                  className="px-4 py-2 rounded-lg bg-primary-600 hover:bg-primary-700 text-white font-medium transition-colors"
                >
                  Done
                </button>
              ) : (
                <>
                  <button
                    type="button"
                    onClick={handleClose}
                    className="px-4 py-2 rounded-lg text-surface-400 hover:text-surface-200 hover:bg-surface-800 transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleSubmit()}
                    disabled={!message.trim() || submitting}
                    className="px-4 py-2 rounded-lg bg-primary-600 hover:bg-primary-700 text-white font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {submitting ? 'Sending...' : 'Send'}
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
