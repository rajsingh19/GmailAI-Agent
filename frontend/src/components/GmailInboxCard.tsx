import React, { useState, useEffect, useCallback } from 'react';
import {
  Mail,
  RefreshCw,
  Search,
  Paperclip,
  Clock,
  Inbox,
  AlertCircle,
  X,
  ChevronRight,
  Filter,
  FileText,
} from 'lucide-react';
import {
  fetchGmailProfile,
  fetchGmailMessages,
  fetchGmailMessageDetail,
  GmailProfile,
  GmailMessageSummary,
  GmailMessageDetail,
  AuthStatusResponse,
} from '../services/api';

interface GmailInboxCardProps {
  authStatus: AuthStatusResponse | null;
}

export const GmailInboxCard: React.FC<GmailInboxCardProps> = ({ authStatus }) => {
  const isConnected = authStatus?.authenticated && authStatus?.google_account?.connected;

  const [profile, setProfile] = useState<GmailProfile | null>(null);
  const [messages, setMessages] = useState<GmailMessageSummary[]>([]);
  const [nextPageToken, setNextPageToken] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Search & Filters
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [activeFilter, setActiveFilter] = useState<string>('all');

  // Detail Modal
  const [selectedMessageId, setSelectedMessageId] = useState<string | null>(null);
  const [messageDetail, setMessageDetail] = useState<GmailMessageDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState<boolean>(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const loadGmailData = useCallback(async (queryOverride?: string, pageToken?: string) => {
    if (!isConnected) return;
    setLoading(true);
    setError(null);

    const queryToUse = queryOverride !== undefined ? queryOverride : searchQuery;

    try {
      const [profData, msgData] = await Promise.all([
        fetchGmailProfile().catch(() => null),
        fetchGmailMessages({
          max_results: 15,
          query: queryToUse || undefined,
          page_token: pageToken,
        }),
      ]);

      if (profData) setProfile(profData);
      setMessages(msgData.messages || []);
      setNextPageToken(msgData.next_page_token || null);
    } catch (err: any) {
      setError(err.message || 'Failed to load Gmail messages');
    } finally {
      setLoading(false);
    }
  }, [isConnected, searchQuery]);

  useEffect(() => {
    if (isConnected) {
      loadGmailData();
    } else {
      setProfile(null);
      setMessages([]);
      setNextPageToken(null);
      setError(null);
    }
  }, [isConnected, loadGmailData]);

  // Handle Search Submission
  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setActiveFilter('custom');
    loadGmailData(searchQuery);
  };

  // Quick Filter Clicks
  const handleFilterClick = (filterKey: string, queryStr: string) => {
    setActiveFilter(filterKey);
    setSearchQuery(queryStr);
    loadGmailData(queryStr);
  };

  // Open Message Detail
  const handleOpenMessage = async (msgId: string) => {
    setSelectedMessageId(msgId);
    setDetailLoading(true);
    setDetailError(null);
    setMessageDetail(null);

    try {
      const detail = await fetchGmailMessageDetail(msgId);
      setMessageDetail(detail);
    } catch (err: any) {
      setDetailError(err.message || 'Failed to fetch message details');
    } finally {
      setDetailLoading(false);
    }
  };

  const closeDetail = () => {
    setSelectedMessageId(null);
    setMessageDetail(null);
    setDetailError(null);
  };

  const formatFileSize = (bytes: number): string => {
    if (!bytes) return '0 B';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const formatDate = (isoString?: string | null): string => {
    if (!isoString) return '';
    try {
      const date = new Date(isoString);
      return date.toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return isoString;
    }
  };

  if (!isConnected) {
    return (
      <div className="glass-panel rounded-2xl p-6 sm:p-8 border border-slate-800/80 bg-slate-900/30 text-slate-400">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-slate-800/80 border border-slate-700/50 flex items-center justify-center text-slate-400">
            <Mail className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-white">Gmail Integration</h3>
            <p className="text-xs text-slate-400">
              Connect your Google Account above to safely view and triage your Gmail messages.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="glass-panel rounded-2xl p-6 sm:p-8 border border-slate-800/80 bg-slate-900/40 space-y-6">
      {/* Header Section */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-rose-500/20 to-red-500/20 border border-rose-500/30 flex items-center justify-center text-rose-400">
            <Mail className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-base sm:text-lg font-bold text-white">Gmail Inbox (Read-Only)</h3>
              <span className="text-[10px] uppercase tracking-wider font-semibold px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                Live API
              </span>
            </div>
            <p className="text-xs text-slate-400">
              {profile?.email || authStatus?.google_account?.email || 'Connected Account'} &bull;{' '}
              {profile ? `${profile.messages_total.toLocaleString()} total messages` : 'Inbox synchronized'}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => loadGmailData()}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-slate-800/80 hover:bg-slate-700 border border-slate-700 text-slate-300 transition-colors disabled:opacity-50 cursor-pointer"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-blue-400' : ''}`} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* Search & Quick Filters */}
      <div className="space-y-3">
        <form onSubmit={handleSearchSubmit} className="flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search emails using Gmail query syntax (e.g. is:unread, from:google.com)..."
              className="w-full pl-9 pr-8 py-2 text-xs sm:text-sm bg-slate-950/60 border border-slate-800 rounded-xl text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-blue-500/50 focus:border-blue-500/50"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => {
                  setSearchQuery('');
                  loadGmailData('');
                }}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
          <button
            type="submit"
            disabled={loading}
            className="px-4 py-2 text-xs font-medium rounded-xl bg-blue-600 hover:bg-blue-500 text-white transition-colors cursor-pointer disabled:opacity-50"
          >
            Search
          </button>
        </form>

        {/* Filter Chips */}
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-slate-500 flex items-center gap-1 mr-1">
            <Filter className="w-3 h-3" /> Quick filters:
          </span>
          <button
            type="button"
            onClick={() => handleFilterClick('all', '')}
            className={`px-2.5 py-1 rounded-lg border transition-colors cursor-pointer ${
              activeFilter === 'all'
                ? 'bg-blue-500/20 border-blue-500/40 text-blue-300'
                : 'bg-slate-800/40 border-slate-700/50 text-slate-400 hover:bg-slate-800'
            }`}
          >
            All Messages
          </button>
          <button
            type="button"
            onClick={() => handleFilterClick('unread', 'is:unread')}
            className={`px-2.5 py-1 rounded-lg border transition-colors cursor-pointer ${
              activeFilter === 'unread'
                ? 'bg-amber-500/20 border-amber-500/40 text-amber-300'
                : 'bg-slate-800/40 border-slate-700/50 text-slate-400 hover:bg-slate-800'
            }`}
          >
            Unread
          </button>
          <button
            type="button"
            onClick={() => handleFilterClick('important', 'is:important')}
            className={`px-2.5 py-1 rounded-lg border transition-colors cursor-pointer ${
              activeFilter === 'important'
                ? 'bg-purple-500/20 border-purple-500/40 text-purple-300'
                : 'bg-slate-800/40 border-slate-700/50 text-slate-400 hover:bg-slate-800'
            }`}
          >
            Important
          </button>
          <button
            type="button"
            onClick={() => handleFilterClick('attachments', 'has:attachment')}
            className={`px-2.5 py-1 rounded-lg border transition-colors cursor-pointer ${
              activeFilter === 'attachments'
                ? 'bg-indigo-500/20 border-indigo-500/40 text-indigo-300'
                : 'bg-slate-800/40 border-slate-700/50 text-slate-400 hover:bg-slate-800'
            }`}
          >
            Has Attachments
          </button>
        </div>
      </div>

      {/* Error Alert */}
      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs flex items-start gap-2.5">
          <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5 text-rose-400" />
          <div>
            <p className="font-medium">Error loading messages</p>
            <p className="mt-0.5 text-rose-400/90">{error}</p>
          </div>
        </div>
      )}

      {/* Message List */}
      <div className="divide-y divide-slate-800/60 border border-slate-800/80 rounded-xl overflow-hidden bg-slate-950/40">
        {loading && messages.length === 0 ? (
          <div className="py-12 text-center text-slate-500 space-y-2">
            <RefreshCw className="w-6 h-6 animate-spin mx-auto text-blue-400" />
            <p className="text-xs">Fetching messages from Gmail API...</p>
          </div>
        ) : messages.length === 0 ? (
          <div className="py-12 text-center text-slate-500 space-y-2">
            <Inbox className="w-8 h-8 mx-auto text-slate-600" />
            <p className="text-sm font-medium text-slate-400">No emails found</p>
            <p className="text-xs text-slate-500">
              {searchQuery ? 'Try adjusting your search query' : 'Your Gmail inbox is empty'}
            </p>
          </div>
        ) : (
          messages.map((msg) => (
            <div
              key={msg.id}
              onClick={() => handleOpenMessage(msg.id)}
              className="p-3.5 sm:p-4 hover:bg-slate-800/40 transition-colors cursor-pointer flex items-center justify-between gap-4 group"
            >
              <div className="min-w-0 flex-1 space-y-1">
                <div className="flex items-center gap-2">
                  {msg.is_unread && (
                    <span className="w-2 h-2 rounded-full bg-blue-500 flex-shrink-0" />
                  )}
                  <p className={`text-xs sm:text-sm truncate ${msg.is_unread ? 'font-semibold text-white' : 'font-medium text-slate-300'}`}>
                    {msg.sender}
                  </p>
                  <span className="text-[10px] text-slate-500 flex items-center gap-1 ml-auto flex-shrink-0">
                    <Clock className="w-3 h-3" />
                    {formatDate(msg.timestamp)}
                  </span>
                </div>

                <div className="flex items-center gap-2">
                  <p className={`text-xs sm:text-sm truncate ${msg.is_unread ? 'font-semibold text-slate-100' : 'text-slate-300'}`}>
                    {msg.subject}
                  </p>
                  {msg.has_attachments && (
                    <Paperclip className="w-3 h-3 text-slate-400 flex-shrink-0" />
                  )}
                </div>

                <p className="text-xs text-slate-500 truncate group-hover:text-slate-400 transition-colors">
                  {msg.snippet}
                </p>

                {msg.labels && msg.labels.length > 0 && (
                  <div className="flex flex-wrap gap-1 pt-1">
                    {msg.labels
                      .filter((l) => !['UNREAD', 'INBOX'].includes(l))
                      .slice(0, 3)
                      .map((label) => (
                        <span
                          key={label}
                          className="text-[9px] px-1.5 py-0.2 rounded bg-slate-800/80 text-slate-400 border border-slate-700/50"
                        >
                          {label}
                        </span>
                      ))}
                  </div>
                )}
              </div>

              <ChevronRight className="w-4 h-4 text-slate-600 group-hover:text-slate-300 flex-shrink-0 transition-colors" />
            </div>
          ))
        )}
      </div>

      {/* Pagination Footer */}
      {nextPageToken && (
        <div className="flex justify-center pt-2">
          <button
            onClick={() => loadGmailData(undefined, nextPageToken)}
            disabled={loading}
            className="px-4 py-2 text-xs font-medium rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 transition-colors cursor-pointer disabled:opacity-50"
          >
            {loading ? 'Loading...' : 'Load More Emails'}
          </button>
        </div>
      )}

      {/* Message Detail Modal */}
      {selectedMessageId && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-3xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            {/* Modal Header */}
            <div className="p-4 sm:p-5 border-b border-slate-800 flex items-start justify-between gap-4 bg-slate-950/40">
              <div className="space-y-1 min-w-0">
                <h4 className="text-base sm:text-lg font-bold text-white truncate">
                  {messageDetail?.subject || 'Loading Message...'}
                </h4>
                {messageDetail && (
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-400">
                    <span>From: <strong className="text-slate-300">{messageDetail.sender}</strong></span>
                    {messageDetail.timestamp && (
                      <span>&bull; {formatDate(messageDetail.timestamp)}</span>
                    )}
                  </div>
                )}
              </div>
              <button
                onClick={closeDetail}
                className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Modal Content */}
            <div className="p-4 sm:p-6 overflow-y-auto flex-1 space-y-4 text-xs sm:text-sm">
              {detailLoading ? (
                <div className="py-16 text-center text-slate-500 space-y-2">
                  <RefreshCw className="w-6 h-6 animate-spin mx-auto text-blue-400" />
                  <p>Retrieving message contents...</p>
                </div>
              ) : detailError ? (
                <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300">
                  <p className="font-semibold">Failed to load email</p>
                  <p className="mt-1 text-xs text-rose-400">{detailError}</p>
                </div>
              ) : messageDetail ? (
                <>
                  {/* Recipient Details */}
                  <div className="p-3 rounded-xl bg-slate-950/50 border border-slate-800/80 space-y-1 text-xs text-slate-400">
                    <div>
                      <strong className="text-slate-300">To:</strong>{' '}
                      {messageDetail.recipients.length > 0 ? messageDetail.recipients.join(', ') : '(None)'}
                    </div>
                    {messageDetail.cc && messageDetail.cc.length > 0 && (
                      <div>
                        <strong className="text-slate-300">CC:</strong> {messageDetail.cc.join(', ')}
                      </div>
                    )}
                    {messageDetail.bcc && messageDetail.bcc.length > 0 && (
                      <div>
                        <strong className="text-slate-300">BCC:</strong> {messageDetail.bcc.join(', ')}
                      </div>
                    )}
                  </div>

                  {/* Attachment Metadata Badge List */}
                  {messageDetail.attachments && messageDetail.attachments.length > 0 && (
                    <div className="space-y-1.5">
                      <p className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
                        <Paperclip className="w-3.5 h-3.5 text-blue-400" />
                        Attachments ({messageDetail.attachments.length})
                        <span className="text-[10px] text-slate-500 font-normal">
                          (Metadata only; contents not downloaded)
                        </span>
                      </p>
                      <div className="flex flex-wrap gap-2">
                        {messageDetail.attachments.map((att, idx) => (
                          <div
                            key={att.attachment_id || idx}
                            className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-xs text-slate-300"
                          >
                            <FileText className="w-3.5 h-3.5 text-indigo-400" />
                            <span className="font-medium">{att.filename}</span>
                            <span className="text-[10px] text-slate-500">
                              {formatFileSize(att.size)}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Email Body: Strictly Displayed As Safe Text */}
                  <div className="space-y-1">
                    <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                      Message Body
                    </p>
                    <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800 text-slate-200 whitespace-pre-wrap font-sans text-xs sm:text-sm leading-relaxed max-h-96 overflow-y-auto select-text">
                      {messageDetail.body_plain ||
                        messageDetail.body_html_text ||
                        messageDetail.snippet ||
                        '(No text content)'}
                    </div>
                  </div>
                </>
              ) : null}
            </div>

            {/* Modal Footer */}
            <div className="p-3 sm:p-4 border-t border-slate-800 bg-slate-950/40 flex justify-end">
              <button
                onClick={closeDetail}
                className="px-4 py-1.5 text-xs font-medium rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors cursor-pointer"
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
