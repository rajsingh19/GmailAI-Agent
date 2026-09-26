import React, { useState, useEffect, useCallback } from 'react';
import {
  Mail,
  Search,
  RefreshCw,
  Star,
  Paperclip,
  ArrowUpRight,
  X,
  FileText,
  AlertCircle,
  Sparkles,
  Edit3,
  ShieldCheck,
} from 'lucide-react';
import {
  AuthStatusResponse,
  GmailMessageSummary,
  GmailMessageDetail,
  fetchGmailMessages,
  fetchGmailMessageDetail,
  getGoogleOAuthUrl,
} from '../../services/api';
import { SmartReplyComposer, SmartReplyState } from '../gmail/SmartReplyComposer';
import { EmailBodyViewer } from '../gmail/EmailBodyViewer';

interface GmailPageProps {
  authStatus: AuthStatusResponse | null;
}

const createDefaultDraftState = (): SmartReplyState => ({
  replyBody: '',
  tone: 'professional',
  customInstructions: '',
  loading: false,
  error: null,
  isDailyQuotaExhausted: false,
  retryCountdown: null,
  placeholders: [],
  generated: false,
});

export const GmailPage: React.FC<GmailPageProps> = ({ authStatus }) => {
  const [messages, setMessages] = useState<GmailMessageSummary[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Search & Filters
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [filterStatus, setFilterStatus] = useState<'all' | 'unread' | 'read'>('all');
  const [filterAttachments, setFilterAttachments] = useState<boolean>(false);

  // Detail Modal
  const [selectedMessageId, setSelectedMessageId] = useState<string | null>(null);
  const [messageDetail, setMessageDetail] = useState<GmailMessageDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState<boolean>(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  // Isolated Smart Reply Drafts State (keyed by messageId)
  const [draftsState, setDraftsState] = useState<Record<string, SmartReplyState>>({});

  // Starred local state toggle for visual feedback
  const [starredIds, setStarredIds] = useState<Set<string>>(new Set());

  const getDraftState = (id: string): SmartReplyState => {
    return draftsState[id] || createDefaultDraftState();
  };

  const updateDraftState = (
    id: string,
    updater: (prev: SmartReplyState) => SmartReplyState
  ) => {
    setDraftsState((prev) => {
      const current = prev[id] || createDefaultDraftState();
      return {
        ...prev,
        [id]: updater(current),
      };
    });
  };

  const discardDraft = (id: string) => {
    setDraftsState((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
  };

  const isConnected = authStatus?.google_account?.connected ?? false;
  const isGmailConnected = isConnected && authStatus?.google_account?.gmail_connected !== false;
  const requiresConsent = isConnected && (authStatus?.google_account?.requires_consent || !isGmailConnected);
  const googleEmail = authStatus?.google_account?.email;

  const loadEmails = useCallback(
    async (queryOverride?: string) => {
      if (!isConnected || !isGmailConnected) return;
      setLoading(true);
      setError(null);
      try {
        const queryToUse = queryOverride !== undefined ? queryOverride : searchQuery;
        const res = await fetchGmailMessages({
          max_results: 20,
          query: queryToUse || undefined,
        });
        setMessages(res.messages || []);
      } catch (err: any) {
        setError(err.message || 'Failed to fetch Gmail messages');
      } finally {
        setLoading(false);
      }
    },
    [isConnected, isGmailConnected, searchQuery]
  );

  useEffect(() => {
    loadEmails();
  }, [loadEmails]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && selectedMessageId) {
        setSelectedMessageId(null);
        setMessageDetail(null);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [selectedMessageId]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    loadEmails(searchQuery);
  };

  const handleOpenDetail = async (id: string) => {
    setSelectedMessageId(id);
    setDetailLoading(true);
    setDetailError(null);
    try {
      const detail = await fetchGmailMessageDetail(id);
      setMessageDetail(detail);
    } catch (err: any) {
      setDetailError(err.message || 'Failed to load email details');
    } finally {
      setDetailLoading(false);
    }
  };

  const toggleStar = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setStarredIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  // Filter messages locally by status and attachments
  const filteredMessages = messages.filter((msg) => {
    if (filterStatus === 'unread' && !msg.is_unread) return false;
    if (filterStatus === 'read' && msg.is_unread) return false;
    if (filterAttachments && !msg.has_attachments) return false;
    return true;
  });

  const formatMessageDate = (dateStr?: string | null) => {
    if (!dateStr) return '';
    const date = new Date(dateStr);
    const now = new Date();
    const isToday = date.toDateString() === now.toDateString();
    if (isToday) {
      return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
    return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
  };

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-gray-900 tracking-tight">Gmail Inbox</h1>
            {isConnected ? (
              requiresConsent ? (
                <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-50 text-amber-700 border border-amber-200">
                  <span className="w-1.5 h-1.5 rounded-full bg-amber-500"></span>
                  Permissions Missing
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
                  Connected
                </span>
              )
            ) : (
              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600 border border-gray-200">
                Disconnected
              </span>
            )}
          </div>
          <p className="text-xs text-gray-500 mt-0.5 flex items-center gap-1">
            <span>{googleEmail ? googleEmail : 'Strictly read-only OAuth integration'}</span>
            <span className="text-gray-300">•</span>
            <span className="text-gray-400">Read-Only</span>
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            onClick={() => loadEmails()}
            disabled={loading || !isGmailConnected}
            title="Refresh Inbox"
            className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg border border-gray-200 bg-white transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin text-indigo-600' : ''}`} />
          </button>
          {!isConnected ? (
            <a
              href={getGoogleOAuthUrl()}
              className="flex items-center gap-1.5 px-3.5 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-medium shadow-sm transition-colors"
            >
              <span>Connect Google</span>
              <ArrowUpRight className="w-4 h-4" />
            </a>
          ) : requiresConsent ? (
            <a
              href={getGoogleOAuthUrl(true)}
              className="flex items-center gap-1.5 px-3.5 py-2 bg-amber-600 hover:bg-amber-700 text-white rounded-lg text-sm font-medium shadow-sm transition-colors"
            >
              <span>Grant Permissions</span>
              <ArrowUpRight className="w-4 h-4" />
            </a>
          ) : null}
        </div>
      </div>

      {/* Search & Filter Toolbar */}
      <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm space-y-3">
        <form onSubmit={handleSearchSubmit} className="flex gap-2">
          <div className="relative flex-1">
            <Search className="w-4 h-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search emails... (e.g. from:google.com, is:unread, label:important)"
              className="w-full pl-9 pr-4 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500"
            />
          </div>
          <button
            type="submit"
            disabled={loading || !isConnected}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-lg shadow-sm transition-colors disabled:opacity-50"
          >
            Search
          </button>
          {searchQuery && (
            <button
              type="button"
              onClick={() => {
                setSearchQuery('');
                loadEmails('');
              }}
              className="px-3 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 text-sm font-medium rounded-lg transition-colors"
            >
              Clear
            </button>
          )}
        </form>

        {/* Quick Filter Controls */}
        <div className="flex items-center gap-2 flex-wrap pt-1 border-t border-gray-100">
          <span className="text-xs font-medium text-gray-500 mr-1">Filter:</span>
          <button
            onClick={() => setFilterStatus('all')}
            className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
              filterStatus === 'all'
                ? 'bg-indigo-50 text-indigo-700 border border-indigo-200'
                : 'bg-gray-50 text-gray-600 hover:bg-gray-100 border border-gray-200'
            }`}
          >
            All Status
          </button>
          <button
            onClick={() => setFilterStatus('unread')}
            className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
              filterStatus === 'unread'
                ? 'bg-indigo-50 text-indigo-700 border border-indigo-200'
                : 'bg-gray-50 text-gray-600 hover:bg-gray-100 border border-gray-200'
            }`}
          >
            Unread Only
          </button>
          <button
            onClick={() => setFilterStatus('read')}
            className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
              filterStatus === 'read'
                ? 'bg-indigo-50 text-indigo-700 border border-indigo-200'
                : 'bg-gray-50 text-gray-600 hover:bg-gray-100 border border-gray-200'
            }`}
          >
            Read
          </button>

          <div className="h-4 w-px bg-gray-200 mx-1" />

          <button
            onClick={() => setFilterAttachments(!filterAttachments)}
            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
              filterAttachments
                ? 'bg-indigo-50 text-indigo-700 border border-indigo-200'
                : 'bg-gray-50 text-gray-600 hover:bg-gray-100 border border-gray-200'
            }`}
          >
            <Paperclip className="w-3 h-3" />
            <span>Has Attachments</span>
          </button>
        </div>
      </div>

      {/* Error Alert */}
      {error && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-xl flex items-center gap-3 text-red-700 text-sm">
          <AlertCircle className="w-5 h-5 flex-shrink-0 text-red-500" />
          <span>{error}</span>
          <button
            onClick={() => loadEmails()}
            className="ml-auto text-xs font-medium text-red-700 underline hover:no-underline"
          >
            Retry
          </button>
        </div>
      )}

      {/* Email List Table */}
      <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
        {!isConnected ? (
          <div className="p-12 text-center text-gray-400">
            <Mail className="w-10 h-10 mx-auto mb-3 text-gray-300" />
            <p className="text-sm font-medium text-gray-700">Google Account Not Connected</p>
            <p className="text-xs text-gray-500 mt-1 max-w-sm mx-auto mb-4">
              Connect your Google workspace account in Settings to sync and search your Gmail inbox safely.
            </p>
            <a
              href={getGoogleOAuthUrl()}
              className="inline-flex items-center gap-1.5 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-xs font-medium transition-colors"
            >
              <span>Connect Google</span>
              <ArrowUpRight className="w-3.5 h-3.5" />
            </a>
          </div>
        ) : requiresConsent ? (
          <div className="p-12 text-center text-gray-400 bg-amber-50/40">
            <AlertCircle className="w-10 h-10 mx-auto mb-3 text-amber-500" />
            <p className="text-sm font-medium text-gray-800">Gmail Permissions Required</p>
            <p className="text-xs text-gray-600 mt-1 max-w-sm mx-auto mb-4">
              Your Google account is connected, but Gmail read-only permissions have not been granted yet.
            </p>
            <a
              href={getGoogleOAuthUrl(true)}
              className="inline-flex items-center gap-1.5 px-4 py-2 bg-amber-600 hover:bg-amber-700 text-white rounded-lg text-xs font-semibold transition-colors shadow-xs"
            >
              <span>Grant Gmail Permissions</span>
              <ArrowUpRight className="w-3.5 h-3.5" />
            </a>
          </div>
        ) : loading && messages.length === 0 ? (
          <div className="p-8 space-y-3">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-14 bg-gray-50 rounded-lg animate-pulse" />
            ))}
          </div>
        ) : filteredMessages.length === 0 ? (
          <div className="p-12 text-center text-gray-400">
            <Mail className="w-10 h-10 mx-auto mb-3 text-gray-300" />
            <p className="text-sm font-medium text-gray-700">No emails found</p>
            <p className="text-xs text-gray-500 mt-1">
              Try adjusting your search query or filter settings.
            </p>
          </div>
        ) : (
          <div className="divide-y divide-[#E5E7EB]">
            {filteredMessages.map((msg) => {
              const isStarred = starredIds.has(msg.id);
              const senderInitial = msg.sender ? msg.sender.charAt(0).toUpperCase() : 'E';

              return (
                <div
                  key={msg.id}
                  onClick={() => handleOpenDetail(msg.id)}
                  className={`px-3.5 py-2.5 flex items-center gap-3 hover:bg-[#F8FAFC] transition-colors cursor-pointer ${
                    msg.is_unread ? 'bg-[#EEF2FF]/30' : ''
                  }`}
                >
                  {/* Star Toggle */}
                  <button
                    onClick={(e) => toggleStar(msg.id, e)}
                    className="text-slate-300 hover:text-amber-400 transition-colors flex-shrink-0"
                  >
                    <Star
                      className={`w-3.5 h-3.5 ${isStarred ? 'fill-amber-400 text-amber-400' : ''}`}
                    />
                  </button>

                  {/* Sender Avatar */}
                  <div className="w-6 h-6 rounded-full bg-blue-50 text-blue-600 flex items-center justify-center font-bold text-[10px] flex-shrink-0">
                    {senderInitial}
                  </div>

                  {/* Sender Name */}
                  <div className="w-32 sm:w-40 truncate flex-shrink-0">
                    <span
                      className={`text-xs ${
                        msg.is_unread ? 'font-bold text-[#111827]' : 'font-medium text-[#334155]'
                      }`}
                    >
                      {msg.sender || 'Sender'}
                    </span>
                  </div>

                  {/* Subject & Snippet */}
                  <div className="flex-1 min-w-0 flex items-baseline gap-1.5">
                    <span
                      className={`text-xs truncate ${
                        msg.is_unread ? 'font-semibold text-[#111827]' : 'text-[#334155]'
                      }`}
                    >
                      {msg.subject || '(No Subject)'}
                    </span>
                    <span className="text-xs text-[#94A3B8] truncate hidden md:inline">
                      — {msg.snippet}
                    </span>
                  </div>

                  {/* Attachment Icon */}
                  {msg.has_attachments && (
                    <Paperclip className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />
                  )}

                  {/* On-Demand Generate Reply Button on Email Row */}
                  <div className="flex items-center gap-1.5 flex-shrink-0">
                    {draftsState[msg.id]?.generated ? (
                      <span className="hidden md:inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-indigo-50 text-indigo-700 border border-indigo-200">
                        <Edit3 className="w-2.5 h-2.5" />
                        <span>Drafted</span>
                      </span>
                    ) : null}
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleOpenDetail(msg.id);
                      }}
                      title="Open Smart Reply Draft"
                      className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium text-indigo-700 hover:text-white bg-indigo-50 hover:bg-indigo-600 border border-indigo-200 hover:border-indigo-600 transition-colors shadow-2xs"
                    >
                      <Sparkles className="w-3 h-3" />
                      <span className="hidden sm:inline">Generate Reply</span>
                    </button>
                  </div>

                  {/* Date/Time */}
                  <div className="text-[11px] text-[#64748B] flex-shrink-0 text-right w-14 sm:w-16">
                    {formatMessageDate(msg.timestamp)}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Email Detail Modal with Integrated Smart Reply Composer */}
      {selectedMessageId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 md:p-6 bg-black/50 backdrop-blur-xs animate-fade-in overflow-y-auto">
          <div className="bg-white border border-gray-200 rounded-2xl w-full max-w-2xl sm:max-w-3xl max-h-[85vh] flex flex-col shadow-2xl relative text-gray-900 overflow-hidden my-auto">
            {/* Modal Header - Fixed & Compact */}
            <div className="p-4 sm:p-5 border-b border-gray-100 flex items-start justify-between gap-3 flex-shrink-0 bg-white sticky top-0 z-10">
              <div className="min-w-0 flex-1 space-y-1.5">
                {/* Badges & Date */}
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-blue-50 text-blue-700 border border-blue-200">
                    Gmail
                  </span>
                  <span className="text-[11px] text-gray-500 font-medium">
                    {messageDetail?.timestamp
                      ? new Date(messageDetail.timestamp).toLocaleString(undefined, {
                          dateStyle: 'medium',
                          timeStyle: 'short',
                        })
                      : ''}
                  </span>
                </div>

                {/* Subject Heading */}
                <h3 className="text-base sm:text-lg font-bold text-gray-900 leading-snug break-words">
                  {messageDetail?.subject || 'Loading Subject...'}
                </h3>

                {/* Compact Sender & Recipient Metadata */}
                {messageDetail && (
                  <div className="flex items-center gap-2 flex-wrap text-xs text-gray-600 pt-0.5">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <div className="w-5 h-5 rounded-full bg-indigo-100 text-indigo-700 font-bold flex items-center justify-center text-[10px] flex-shrink-0">
                        {(messageDetail.sender || 'S').slice(0, 1).toUpperCase()}
                      </div>
                      <span className="font-semibold text-gray-900">From:</span>
                      <span className="text-gray-800 break-all">{messageDetail.sender}</span>
                    </div>
                    {messageDetail.recipients && messageDetail.recipients.length > 0 && (
                      <div className="flex items-center gap-1 text-gray-500 text-[11px] truncate">
                        <span>•</span>
                        <span className="font-medium text-gray-700">To:</span>
                        <span className="truncate">{messageDetail.recipients.join(', ')}</span>
                      </div>
                    )}
                  </div>
                )}
              </div>

              <button
                onClick={() => {
                  setSelectedMessageId(null);
                  setMessageDetail(null);
                }}
                aria-label="Close modal"
                className="p-1.5 text-gray-400 hover:text-gray-700 rounded-lg hover:bg-gray-100 transition-colors flex-shrink-0 cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Modal Body with Vertical-Only Scrolling */}
            <div className="p-4 sm:p-5 overflow-y-auto overflow-x-hidden flex-1 space-y-4 min-h-0">
              {detailLoading ? (
                <div className="py-16 text-center text-xs text-gray-400 flex flex-col items-center justify-center gap-2">
                  <RefreshCw className="w-5 h-5 animate-spin text-indigo-500" />
                  <span>Loading full message...</span>
                </div>
              ) : detailError ? (
                <div className="p-3.5 bg-red-50 text-red-700 text-xs rounded-xl border border-red-200 flex items-center gap-2">
                  <AlertCircle className="w-4 h-4 flex-shrink-0" />
                  <span>{detailError}</span>
                </div>
              ) : messageDetail ? (
                <>
                  {/* Clean & Formatted Email Body with URL Shortening */}
                  <div className="text-gray-800 text-xs sm:text-sm">
                    <EmailBodyViewer
                      content={messageDetail.body_plain || messageDetail.body_html_text || messageDetail.snippet}
                    />
                  </div>

                  {/* Attachments Section */}
                  {messageDetail.attachments && messageDetail.attachments.length > 0 && (
                    <div className="pt-3 border-t border-gray-100">
                      <h4 className="text-xs font-semibold text-gray-700 mb-2 flex items-center gap-1.5">
                        <Paperclip className="w-3.5 h-3.5 text-gray-500" />
                        <span>Attachments ({messageDetail.attachments.length})</span>
                      </h4>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        {messageDetail.attachments.map((att, idx) => (
                          <div
                            key={idx}
                            className="p-2.5 bg-gray-50 border border-gray-200 rounded-lg flex items-center justify-between text-xs overflow-hidden"
                          >
                            <div className="flex items-center gap-2 truncate min-w-0">
                              <FileText className="w-4 h-4 text-indigo-600 flex-shrink-0" />
                              <span className="font-medium text-gray-800 truncate">
                                {att.filename}
                              </span>
                              <span className="text-[10px] text-gray-400 flex-shrink-0">
                                ({(att.size / 1024).toFixed(1)} KB)
                              </span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Visual Divider & On-Demand Smart Reply Composer Section */}
                  <div className="pt-4 border-t border-indigo-100/80">
                    <div className="mb-2 flex items-center justify-between">
                      <span className="text-[11px] font-bold uppercase tracking-wider text-indigo-600 flex items-center gap-1">
                        <Sparkles className="w-3.5 h-3.5" />
                        <span>AI Smart Reply Assistant</span>
                      </span>
                      <span className="text-[10px] text-gray-400">On-demand only</span>
                    </div>
                    <SmartReplyComposer
                      messageId={messageDetail.id}
                      threadId={messageDetail.thread_id}
                      subject={messageDetail.subject}
                      recipient={messageDetail.sender}
                      state={getDraftState(messageDetail.id)}
                      onUpdateState={(updater) => updateDraftState(messageDetail.id, updater)}
                      onDiscard={() => discardDraft(messageDetail.id)}
                      compact={true}
                    />
                  </div>
                </>
              ) : null}
            </div>

            {/* Modal Footer - Fixed & Accessible */}
            <div className="p-3 sm:p-3.5 border-t border-gray-100 flex items-center justify-between bg-gray-50/80 rounded-b-2xl flex-shrink-0 sticky bottom-0 z-10">
              <div className="flex items-center gap-1.5 text-[11px] text-gray-500 font-medium">
                <ShieldCheck className="w-3.5 h-3.5 text-emerald-600 flex-shrink-0" />
                <span>Drafts Only • Never Sends Automatically (Mailbox Protected)</span>
              </div>
              <button
                onClick={() => {
                  setSelectedMessageId(null);
                  setMessageDetail(null);
                }}
                className="px-4 py-1.5 bg-white border border-gray-200 hover:bg-gray-50 text-gray-700 text-xs font-medium rounded-lg transition-colors shadow-2xs cursor-pointer"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
