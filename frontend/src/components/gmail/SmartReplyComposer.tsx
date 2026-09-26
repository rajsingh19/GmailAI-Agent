import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Sparkles,
  Copy,
  Check,
  RefreshCw,
  Trash2,
  AlertCircle,
  SlidersHorizontal,
  Info,
  Clock,
  ExternalLink,
  MailCheck,
  SendHorizontal,
} from 'lucide-react';
import {
  GmailReplyDraftRequest,
  GmailReplyDraftResponse,
  generateGmailReplyDraft,
  fetchSavedGmailReplyDraft,
  saveGmailReplyDraft,
  saveGmailReplyDraftToMailbox,
  deleteSavedGmailReplyDraft,
  getGoogleOAuthUrl,
} from '../../services/api';

export type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';

export interface SmartReplyState {
  replyBody: string;
  tone: string;
  customInstructions: string;
  loading: boolean;
  error: string | null;
  isDailyQuotaExhausted?: boolean;
  retryCountdown?: number | null;
  placeholders: string[];
  generated: boolean;
  saveStatus?: SaveStatus;
  lastSavedAt?: string | null;
  initialFetchDone?: boolean;
  // Gmail Draft state
  gmailDraftId?: string | null;
  gmailSaveStatus?: SaveStatus;
  gmailSaveError?: string | null;
  gmailWebUrl?: string | null;
  isMissingComposeScope?: boolean;
}

interface SmartReplyComposerProps {
  messageId: string;
  threadId?: string;
  subject?: string;
  recipient?: string;
  state: SmartReplyState;
  onUpdateState: (updater: (prev: SmartReplyState) => SmartReplyState) => void;
  onDiscard?: () => void;
  compact?: boolean;
}

const AVAILABLE_TONES = [
  { id: 'professional', label: 'Professional' },
  { id: 'friendly', label: 'Friendly' },
  { id: 'concise', label: 'Concise' },
  { id: 'formal', label: 'Formal' },
  { id: 'direct', label: 'Direct' },
];

export const SmartReplyComposer: React.FC<SmartReplyComposerProps> = ({
  messageId,
  threadId,
  subject,
  recipient,
  state,
  onUpdateState,
  onDiscard,
  compact = false,
}) => {
  const [copied, setCopied] = useState<boolean>(false);
  const [showOptions, setShowOptions] = useState<boolean>(false);
  const [showDiscardConfirm, setShowDiscardConfirm] = useState<boolean>(false);
  const [isDiscarding, setIsDiscarding] = useState<boolean>(false);
  const [isSavingToGmail, setIsSavingToGmail] = useState<boolean>(false);
  const [countdown, setCountdown] = useState<number | null>(state.retryCountdown ?? null);

  const autosaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const stateRef = useRef(state);
  stateRef.current = state;

  // Cross-device draft hydration: Fetch saved draft (and existing Gmail draft info) on mount / messageId change
  useEffect(() => {
    let isSubscribed = true;

    async function loadSavedDraft() {
      if (!messageId) return;
      try {
        const saved = await fetchSavedGmailReplyDraft(messageId);
        if (!isSubscribed) return;

        if (saved && saved.reply_body) {
          onUpdateState((prev) => ({
            ...prev,
            replyBody: saved.reply_body,
            tone: saved.tone_used || 'professional',
            customInstructions: saved.custom_instructions || '',
            placeholders: saved.placeholders_detected || [],
            generated: true,
            saveStatus: 'saved',
            lastSavedAt: saved.updated_at || saved.created_at || new Date().toISOString(),
            initialFetchDone: true,
            error: null,
            gmailDraftId: saved.gmail_draft_id || null,
            gmailWebUrl: saved.gmail_web_url || (saved.gmail_draft_id ? 'https://mail.google.com/mail/u/0/#drafts' : null),
            gmailSaveStatus: saved.gmail_draft_id ? 'saved' : 'idle',
            gmailSaveError: null,
            isMissingComposeScope: false,
          }));
        } else {
          onUpdateState((prev) => ({
            ...prev,
            initialFetchDone: true,
          }));
        }
      } catch (e) {
        if (!isSubscribed) return;
        onUpdateState((prev) => ({
          ...prev,
          initialFetchDone: true,
        }));
      }
    }

    loadSavedDraft();

    return () => {
      isSubscribed = false;
      if (autosaveTimerRef.current) {
        clearTimeout(autosaveTimerRef.current);
      }
    };
  }, [messageId]);

  // Sync internal countdown with parent state if modified externally
  useEffect(() => {
    if (state.retryCountdown !== undefined) {
      setCountdown(state.retryCountdown);
    }
  }, [state.retryCountdown]);

  // Active timer decrement effect for temporary rate limits
  useEffect(() => {
    if (countdown === null || countdown <= 0) return;

    const timer = setInterval(() => {
      setCountdown((prev) => {
        if (prev === null || prev <= 1) {
          clearInterval(timer);
          return null;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, [countdown]);

  // Execute background persistence save to local backend DB
  const persistDraft = useCallback(
    async (bodyToSave: string, toneToSave: string, customInstToSave: string, placeholdersToSave: string[]) => {
      if (!messageId || !bodyToSave.trim()) return;

      onUpdateState((prev) => ({ ...prev, saveStatus: 'saving' }));

      try {
        const res = await saveGmailReplyDraft(messageId, {
          reply_body: bodyToSave,
          tone: toneToSave || 'professional',
          custom_instructions: customInstToSave.trim() || undefined,
          placeholders_detected: placeholdersToSave,
          thread_id: threadId,
          subject: subject,
          recipient: recipient,
          gmail_draft_id: stateRef.current.gmailDraftId || undefined,
        });

        onUpdateState((prev) => ({
          ...prev,
          saveStatus: 'saved',
          lastSavedAt: res.updated_at || new Date().toISOString(),
        }));
      } catch (err: any) {
        onUpdateState((prev) => ({
          ...prev,
          saveStatus: 'error',
        }));
      }
    },
    [messageId, threadId, subject, recipient, onUpdateState]
  );

  // Debounced Autosave Trigger for editor changes
  const triggerAutosave = useCallback(
    (newBody: string, newTone: string, newInst: string, newPlaceholders: string[]) => {
      if (autosaveTimerRef.current) {
        clearTimeout(autosaveTimerRef.current);
      }

      onUpdateState((prev) => ({ ...prev, saveStatus: 'saving' }));

      autosaveTimerRef.current = setTimeout(() => {
        persistDraft(newBody, newTone, newInst, newPlaceholders);
      }, 800);
    },
    [onUpdateState, persistDraft]
  );

  // Explicit Action: Save draft directly into Gmail mailbox Drafts folder
  const handleSaveToGmail = async () => {
    if (!messageId || !state.replyBody.trim() || isSavingToGmail) return;

    setIsSavingToGmail(true);
    onUpdateState((prev) => ({
      ...prev,
      gmailSaveStatus: 'saving',
      gmailSaveError: null,
      isMissingComposeScope: false,
    }));

    try {
      const res = await saveGmailReplyDraftToMailbox(messageId, {
        reply_body: state.replyBody,
        tone: state.tone || 'professional',
        custom_instructions: state.customInstructions.trim() || undefined,
        placeholders_detected: state.placeholders,
        thread_id: threadId,
        subject: subject,
        recipient: recipient,
        gmail_draft_id: state.gmailDraftId || undefined,
      });

      onUpdateState((prev) => ({
        ...prev,
        gmailDraftId: res.gmail_draft_id,
        gmailWebUrl: res.gmail_web_url || 'https://mail.google.com/mail/u/0/#drafts',
        gmailSaveStatus: 'saved',
        gmailSaveError: null,
        isMissingComposeScope: false,
        saveStatus: 'saved',
        lastSavedAt: res.updated_at || new Date().toISOString(),
      }));
    } catch (err: any) {
      const errMsg = err.message || 'Failed to save draft to Gmail.';
      const isScopeError =
        err.status === 403 ||
        errMsg.toLowerCase().includes('scope') ||
        errMsg.toLowerCase().includes('compose') ||
        errMsg.toLowerCase().includes('permission') ||
        errMsg.toLowerCase().includes('reconnect');

      onUpdateState((prev) => ({
        ...prev,
        gmailSaveStatus: 'error',
        gmailSaveError: errMsg,
        isMissingComposeScope: isScopeError,
      }));
    } finally {
      setIsSavingToGmail(false);
    }
  };

  const handleGenerate = async (overrideTone?: string) => {
    // If daily quota is exhausted or temporary countdown is active, block generation
    if (state.isDailyQuotaExhausted) return;
    if (countdown !== null && countdown > 0) return;

    const toneToUse = overrideTone || state.tone || 'professional';
    onUpdateState((prev) => ({
      ...prev,
      loading: true,
      error: null,
      tone: toneToUse,
    }));

    try {
      const payload: GmailReplyDraftRequest = {
        tone: toneToUse,
        custom_instructions: state.customInstructions.trim() || undefined,
        include_thread_context: true,
      };

      const res: GmailReplyDraftResponse = await generateGmailReplyDraft(messageId, payload);
      setCountdown(null);
      onUpdateState((prev) => ({
        ...prev,
        replyBody: res.reply_body,
        tone: res.tone_used,
        placeholders: res.placeholders_detected || [],
        loading: false,
        generated: true,
        saveStatus: 'saved',
        lastSavedAt: res.updated_at || res.created_at || new Date().toISOString(),
        error: null,
        isDailyQuotaExhausted: false,
        retryCountdown: null,
      }));
    } catch (err: any) {
      const isDailyQuota = !!(
        err.isDailyQuota ||
        err.message?.toLowerCase().includes('daily quota') ||
        err.message?.toLowerCase().includes('billing-enabled')
      );

      if (isDailyQuota) {
        setCountdown(null);
        onUpdateState((prev) => ({
          ...prev,
          loading: false,
          error:
            'Gemini daily quota exhausted. Smart Reply will work when your quota resets or you configure a billing-enabled plan.',
          isDailyQuotaExhausted: true,
          retryCountdown: null,
        }));
        return;
      }

      const is429 = err.status === 429 || (err.message && err.message.toLowerCase().includes('rate limit'));
      let retrySecs = err.retryAfter;

      if (is429 && !retrySecs) {
        const match = err.message?.match(/(?:~|in\s+)?([0-9]+)\s*s/i);
        retrySecs = match ? parseInt(match[1], 10) : 30;
      }

      if (is429 && retrySecs) {
        setCountdown(retrySecs);
      }

      onUpdateState((prev) => ({
        ...prev,
        loading: false,
        error: err.message || 'Failed to generate smart reply draft.',
        isDailyQuotaExhausted: false,
        retryCountdown: retrySecs || null,
      }));
    }
  };

  const handleCopy = async () => {
    if (!state.replyBody) return;
    try {
      await navigator.clipboard.writeText(state.replyBody);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch (e) {
      const textArea = document.createElement('textarea');
      textArea.value = state.replyBody;
      document.body.appendChild(textArea);
      textArea.select();
      document.execCommand('copy');
      document.body.removeChild(textArea);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    }
  };

  const handleTextChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const newText = e.target.value;
    const matches = newText.match(/\[([A-Za-z0-9\s/_\-:,]+)\]/g) || [];
    const dedupedPlaceholders = Array.from(new Set(matches));

    onUpdateState((prev) => ({
      ...prev,
      replyBody: newText,
      placeholders: dedupedPlaceholders,
      generated: newText.trim().length > 0 ? true : prev.generated,
    }));

    if (newText.trim().length > 0) {
      triggerAutosave(newText, state.tone, state.customInstructions, dedupedPlaceholders);
    }
  };

  const handleToneSelect = (toneId: string) => {
    onUpdateState((prev) => ({ ...prev, tone: toneId }));
    if (state.generated && !state.isDailyQuotaExhausted && (!countdown || countdown <= 0)) {
      handleGenerate(toneId);
    } else if (state.replyBody.trim()) {
      triggerAutosave(state.replyBody, toneId, state.customInstructions, state.placeholders);
    }
  };

  const handleCustomInstructionsChange = (newInst: string) => {
    onUpdateState((prev) => ({ ...prev, customInstructions: newInst }));
    if (state.replyBody.trim()) {
      triggerAutosave(state.replyBody, state.tone, newInst, state.placeholders);
    }
  };

  const handleConfirmDiscard = async () => {
    setIsDiscarding(true);
    try {
      if (autosaveTimerRef.current) {
        clearTimeout(autosaveTimerRef.current);
      }
      await deleteSavedGmailReplyDraft(messageId);
    } catch (e) {
      // Ignore 404 or backend discard failure for local reset
    } finally {
      setIsDiscarding(false);
      setShowDiscardConfirm(false);
      onUpdateState(() => ({
        replyBody: '',
        tone: 'professional',
        customInstructions: '',
        loading: false,
        error: null,
        isDailyQuotaExhausted: false,
        retryCountdown: null,
        placeholders: [],
        generated: false,
        saveStatus: 'idle',
        lastSavedAt: null,
        initialFetchDone: true,
        gmailDraftId: null,
        gmailSaveStatus: 'idle',
        gmailSaveError: null,
        gmailWebUrl: null,
        isMissingComposeScope: false,
      }));
      onDiscard?.();
    }
  };

  const isRateLimited = countdown !== null && countdown > 0;
  const hasGmailDraft = !!state.gmailDraftId && state.gmailSaveStatus === 'saved';

  return (
    <div
      className={`rounded-xl border border-indigo-100 bg-gradient-to-b from-indigo-50/30 to-white shadow-xs transition-all ${
        compact ? 'p-3' : 'p-4 sm:p-5'
      }`}
    >
      {/* Composer Header */}
      <div className="flex items-center justify-between gap-3 mb-3">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-lg bg-indigo-600 text-white shadow-xs">
            <Sparkles className="w-4 h-4" />
          </div>
          <div>
            <h4 className="text-xs sm:text-sm font-semibold text-gray-900 flex items-center gap-1.5 flex-wrap">
              <span>Smart Reply Draft</span>
              <span className="px-1.5 py-0.2 rounded text-[10px] font-medium bg-indigo-100 text-indigo-700">
                Gemini AI
              </span>

              {/* Confirmed Real Gmail Draft Status Badge */}
              {hasGmailDraft && (
                <span
                  className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200"
                  title="Saved in your actual Gmail Drafts folder. Accessible on your phone and all devices."
                >
                  <MailCheck className="w-3 h-3 text-emerald-600" />
                  <span>Saved to Gmail</span>
                </span>
              )}

              {/* Local / In-Progress Cloud Sync Status Badge (when not yet in Gmail or saving) */}
              {state.generated && !hasGmailDraft && (
                <span className="inline-flex items-center gap-1 text-[11px] font-medium">
                  {state.saveStatus === 'saving' && (
                    <span className="inline-flex items-center gap-1 text-amber-600 bg-amber-50 px-2 py-0.5 rounded border border-amber-200">
                      <RefreshCw className="w-2.5 h-2.5 animate-spin text-amber-600" />
                      <span>Saving...</span>
                    </span>
                  )}
                  {state.saveStatus === 'saved' && (
                    <span
                      className="inline-flex items-center gap-1 text-slate-600 bg-slate-50 px-2 py-0.5 rounded border border-slate-200"
                      title={state.lastSavedAt ? `Saved locally at ${new Date(state.lastSavedAt).toLocaleTimeString()}` : 'Saved locally'}
                    >
                      <Check className="w-2.5 h-2.5 text-slate-500" />
                      <span>Draft ready</span>
                    </span>
                  )}
                  {state.saveStatus === 'error' && (
                    <span className="inline-flex items-center gap-1 text-red-700 bg-red-50 px-2 py-0.5 rounded border border-red-200">
                      <AlertCircle className="w-2.5 h-2.5 text-red-600" />
                      <span>Save failed</span>
                      <button
                        type="button"
                        onClick={() =>
                          persistDraft(
                            state.replyBody,
                            state.tone,
                            state.customInstructions,
                            state.placeholders
                          )
                        }
                        className="ml-1 underline font-semibold hover:text-red-900"
                      >
                        Retry
                      </button>
                    </span>
                  )}
                </span>
              )}
            </h4>
            <p className="text-[11px] text-gray-500">
              {hasGmailDraft
                ? 'Saved directly to your Gmail Drafts folder & synced to mobile'
                : state.generated
                ? 'Review, edit, and click "Save to Gmail Drafts" to sync to phone'
                : 'Generate a context-aware reply on demand'}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => setShowOptions(!showOptions)}
            className={`p-1.5 rounded-lg text-xs font-medium transition-colors border ${
              showOptions
                ? 'bg-indigo-50 border-indigo-200 text-indigo-700'
                : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'
            }`}
            title="Toggle tone and custom guidelines"
          >
            <SlidersHorizontal className="w-3.5 h-3.5" />
          </button>

          {!state.generated && (
            <button
              type="button"
              onClick={() => handleGenerate()}
              disabled={state.loading || isRateLimited || !!state.isDailyQuotaExhausted}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium shadow-xs transition-colors ${
                state.isDailyQuotaExhausted
                  ? 'bg-amber-100 text-amber-800 border border-amber-300 cursor-not-allowed opacity-90'
                  : isRateLimited
                  ? 'bg-amber-100 text-amber-800 border border-amber-300 cursor-not-allowed'
                  : 'bg-indigo-600 hover:bg-indigo-700 text-white disabled:opacity-50'
              }`}
            >
              {state.loading ? (
                <>
                  <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                  <span>Drafting...</span>
                </>
              ) : state.isDailyQuotaExhausted ? (
                <>
                  <AlertCircle className="w-3.5 h-3.5 text-amber-700" />
                  <span>Daily Quota Exhausted</span>
                </>
              ) : isRateLimited ? (
                <>
                  <Clock className="w-3.5 h-3.5 animate-pulse" />
                  <span>Retry in {countdown}s</span>
                </>
              ) : (
                <>
                  <Sparkles className="w-3.5 h-3.5" />
                  <span>Generate Reply</span>
                </>
              )}
            </button>
          )}
        </div>
      </div>

      {/* Optional Tone & Guideline Controls */}
      {showOptions && (
        <div className="mb-3.5 p-3 bg-white border border-gray-200 rounded-lg shadow-2xs space-y-2.5">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-[11px] font-medium text-gray-500 mr-1">Tone:</span>
            {AVAILABLE_TONES.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => handleToneSelect(t.id)}
                className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors border ${
                  state.tone === t.id
                    ? 'bg-indigo-600 border-indigo-600 text-white shadow-2xs'
                    : 'bg-gray-50 hover:bg-gray-100 border-gray-200 text-gray-700'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          <div>
            <label className="block text-[11px] font-medium text-gray-600 mb-1">
              Custom instructions or scheduling notes (optional):
            </label>
            <input
              type="text"
              value={state.customInstructions}
              onChange={(e) => handleCustomInstructionsChange(e.target.value)}
              placeholder="e.g. Free on Friday morning, ask for Zoom link, politely decline..."
              className="w-full px-3 py-1.5 bg-gray-50 border border-gray-200 rounded-md text-xs text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500"
            />
          </div>
        </div>
      )}

      {/* Daily Quota Exhausted Warning Banner */}
      {state.isDailyQuotaExhausted && (
        <div className="mb-3 p-2.5 bg-amber-50/90 border border-amber-300 rounded-lg flex items-center gap-2.5 text-amber-900 text-xs">
          <AlertCircle className="w-4 h-4 text-amber-600 flex-shrink-0" />
          <div className="flex-1 text-[11px] sm:text-xs leading-snug">
            <span className="font-semibold text-amber-950">Daily Quota Exhausted:</span>{' '}
            <span className="text-amber-800">
              Smart Reply will work when your quota resets or you configure a billing-enabled plan.
            </span>
          </div>
        </div>
      )}

      {/* Temporary Rate Limit Countdown Warning Alert */}
      {!state.isDailyQuotaExhausted && isRateLimited && (
        <div className="mb-3 p-3 bg-amber-50 border border-amber-200 rounded-lg flex items-center justify-between gap-3 text-amber-800 text-xs">
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-amber-600 flex-shrink-0 animate-pulse" />
            <span>
              <strong>Rate limit reached.</strong> Quota cooldown in progress. Please retry in{' '}
              <span className="font-bold text-amber-900">{countdown}s</span>.
            </span>
          </div>
        </div>
      )}

      {/* Generation Error Alert */}
      {state.error && !state.isDailyQuotaExhausted && !isRateLimited && (
        <div className="mb-3 p-3 bg-red-50 border border-red-200 rounded-lg flex items-start gap-2.5 text-red-700 text-xs">
          <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="font-medium">{state.error}</p>
          </div>
          <button
            type="button"
            onClick={() => handleGenerate()}
            disabled={state.loading}
            className="px-2 py-1 bg-red-100 hover:bg-red-200 text-red-800 rounded text-[11px] font-medium transition-colors cursor-pointer"
          >
            Retry
          </button>
        </div>
      )}

      {/* Missing Gmail Compose Scope Error & Reconnect CTA */}
      {state.isMissingComposeScope && (
        <div className="mb-3 p-3.5 bg-amber-50 border border-amber-300 rounded-xl text-amber-900 text-xs space-y-2">
          <div className="flex items-start gap-2">
            <AlertCircle className="w-4 h-4 text-amber-600 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <span className="font-semibold text-amber-950">Gmail Drafts Permission Required:</span>{' '}
              <span>
                To save drafts directly into your Gmail account so they appear on your phone, please reconnect with draft-creation permission. Sending remains strictly manual under your control.
              </span>
            </div>
          </div>
          <div className="pl-6">
            <a
              href={getGoogleOAuthUrl(true)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-amber-600 hover:bg-amber-700 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors"
            >
              <span>Reconnect Google Account</span>
              <ExternalLink className="w-3 h-3" />
            </a>
          </div>
        </div>
      )}

      {/* Gmail Save Error Banner (non-scope) */}
      {state.gmailSaveError && !state.isMissingComposeScope && (
        <div className="mb-3 p-3 bg-red-50 border border-red-200 rounded-lg flex items-start gap-2.5 text-red-700 text-xs">
          <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />
          <div className="flex-1">
            <span className="font-semibold">Failed to save to Gmail:</span> {state.gmailSaveError}
          </div>
          <button
            type="button"
            onClick={handleSaveToGmail}
            disabled={isSavingToGmail}
            className="px-2.5 py-1 bg-red-100 hover:bg-red-200 text-red-800 rounded text-[11px] font-medium transition-colors cursor-pointer"
          >
            Retry Save
          </button>
        </div>
      )}

      {/* Loading Skeleton during first generation */}
      {state.loading && !state.replyBody && (
        <div className="py-6 space-y-2.5">
          <div className="h-4 bg-indigo-100/60 rounded animate-pulse w-3/4" />
          <div className="h-4 bg-indigo-100/60 rounded animate-pulse w-full" />
          <div className="h-4 bg-indigo-100/60 rounded animate-pulse w-5/6" />
          <div className="h-4 bg-indigo-100/60 rounded animate-pulse w-1/2" />
        </div>
      )}

      {/* Generated Editable Area */}
      {(state.generated || state.replyBody) && (
        <div className="space-y-3">
          {/* Placeholder Banner Notice */}
          {state.placeholders.length > 0 && (
            <div className="p-2.5 bg-amber-50/80 border border-amber-200 rounded-lg flex items-start gap-2 text-amber-800 text-xs">
              <Info className="w-4 h-4 text-amber-600 flex-shrink-0 mt-0.5" />
              <div className="flex-1">
                <span className="font-semibold">Review Placeholders:</span>{' '}
                Please check or fill in{' '}
                <span className="font-mono text-[11px] font-bold text-amber-900">
                  {state.placeholders.join(', ')}
                </span>{' '}
                before saving or sending.
              </div>
            </div>
          )}

          {/* Text Area */}
          <div className="relative">
            <textarea
              value={state.replyBody}
              onChange={handleTextChange}
              rows={compact ? 5 : 8}
              placeholder="Draft reply will appear here..."
              className="w-full p-3.5 bg-white border border-gray-200 rounded-lg text-xs sm:text-sm text-gray-900 placeholder:text-gray-400 font-sans leading-relaxed focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 resize-y shadow-2xs break-words"
            />
            {state.loading && (
              <div className="absolute inset-0 bg-white/70 backdrop-blur-2xs flex items-center justify-center rounded-lg">
                <div className="flex items-center gap-2 text-xs font-semibold text-indigo-700 bg-white px-3 py-1.5 rounded-full shadow-sm border border-indigo-100">
                  <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                  <span>Regenerating reply...</span>
                </div>
              </div>
            )}
          </div>

          {/* Discard Confirmation Inline Box */}
          {showDiscardConfirm ? (
            <div className="p-3 bg-red-50/90 border border-red-200 rounded-lg flex items-center justify-between gap-3 text-xs animate-in fade-in duration-150">
              <div className="flex items-center gap-2 text-red-900 font-medium">
                <AlertCircle className="w-4 h-4 text-red-600 flex-shrink-0" />
                <span>Discard this draft from local storage & Gmail across all devices?</span>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                <button
                  type="button"
                  onClick={() => setShowDiscardConfirm(false)}
                  disabled={isDiscarding}
                  className="px-2.5 py-1 bg-white hover:bg-gray-100 border border-gray-300 text-gray-700 rounded-md text-xs font-medium transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleConfirmDiscard}
                  disabled={isDiscarding}
                  className="px-2.5 py-1 bg-red-600 hover:bg-red-700 text-white rounded-md text-xs font-medium shadow-xs transition-colors"
                >
                  {isDiscarding ? 'Discarding...' : 'Yes, Discard'}
                </button>
              </div>
            </div>
          ) : (
            /* Action Toolbar */
            <div className="flex items-center justify-between gap-2 flex-wrap pt-1">
              <div className="flex items-center gap-2 flex-wrap">
                {/* Primary Action: Save to Gmail Drafts / Update Gmail Draft */}
                <button
                  type="button"
                  id="save-to-gmail-drafts-btn"
                  onClick={handleSaveToGmail}
                  disabled={isSavingToGmail || !state.replyBody.trim()}
                  className={`inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold shadow-xs transition-all cursor-pointer ${
                    hasGmailDraft
                      ? 'bg-emerald-600 hover:bg-emerald-700 text-white'
                      : 'bg-indigo-600 hover:bg-indigo-700 text-white disabled:opacity-50'
                  }`}
                  title={hasGmailDraft ? 'Update draft in Gmail' : 'Save draft to Gmail Drafts folder'}
                >
                  {isSavingToGmail ? (
                    <>
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      <span>Saving to Gmail...</span>
                    </>
                  ) : hasGmailDraft ? (
                    <>
                      <Check className="w-3.5 h-3.5" />
                      <span>Update in Gmail Drafts</span>
                    </>
                  ) : (
                    <>
                      <SendHorizontal className="w-3.5 h-3.5" />
                      <span>Save to Gmail Drafts</span>
                    </>
                  )}
                </button>

                {/* Secondary Action: Open in Gmail (shown once saved to Gmail) */}
                {hasGmailDraft && (
                  <a
                    href={state.gmailWebUrl || 'https://mail.google.com/mail/u/0/#drafts'}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-white hover:bg-gray-50 border border-gray-200 text-gray-700 rounded-lg text-xs font-medium shadow-2xs transition-colors"
                    title="Open draft in Gmail web app"
                  >
                    <ExternalLink className="w-3.5 h-3.5 text-gray-500" />
                    <span>Open in Gmail</span>
                  </a>
                )}

                {/* Copy Reply Button */}
                <button
                  type="button"
                  onClick={handleCopy}
                  disabled={!state.replyBody}
                  className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium shadow-2xs transition-all border ${
                    copied
                      ? 'bg-emerald-50 border-emerald-300 text-emerald-700'
                      : 'bg-white border-gray-200 hover:bg-gray-50 text-gray-700'
                  }`}
                >
                  {copied ? (
                    <>
                      <Check className="w-3.5 h-3.5 text-emerald-600" />
                      <span>Copied!</span>
                    </>
                  ) : (
                    <>
                      <Copy className="w-3.5 h-3.5 text-gray-500" />
                      <span>Copy</span>
                    </>
                  )}
                </button>

                {/* Regenerate Button */}
                <button
                  type="button"
                  onClick={() => handleGenerate()}
                  disabled={state.loading || isRateLimited || !!state.isDailyQuotaExhausted}
                  className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium shadow-2xs transition-colors border ${
                    state.isDailyQuotaExhausted
                      ? 'bg-amber-50 border-amber-200 text-amber-800 cursor-not-allowed opacity-90'
                      : isRateLimited
                      ? 'bg-amber-50 border-amber-200 text-amber-800 cursor-not-allowed'
                      : 'bg-white border-gray-200 hover:bg-gray-50 text-gray-700 disabled:opacity-50'
                  }`}
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${state.loading ? 'animate-spin text-indigo-600' : ''}`} />
                  <span>
                    {state.isDailyQuotaExhausted
                      ? 'Quota Exhausted'
                      : isRateLimited
                      ? `Retry in ${countdown}s`
                      : 'Regenerate'}
                  </span>
                </button>
              </div>

              {/* Discard Draft Button */}
              <button
                type="button"
                onClick={() => setShowDiscardConfirm(true)}
                className="inline-flex items-center gap-1 px-2.5 py-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg text-xs font-medium transition-colors cursor-pointer"
                title="Discard draft across all devices"
              >
                <Trash2 className="w-3.5 h-3.5" />
                <span>Discard</span>
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
