import React, { useState, useEffect, useCallback } from 'react';
import {
  Calendar as CalendarIcon,
  Clock,
  MapPin,
  Users,
  Video,
  ExternalLink,
  Search,
  RefreshCw,
  AlertCircle,
  Lock,
  ChevronDown,
  X,
  CalendarDays,
  ShieldCheck,
} from 'lucide-react';
import {
  AuthStatusResponse,
  CalendarSummary,
  CalendarEventSummary,
  CalendarEventDetail,
  fetchCalendars,
  fetchCalendarEvents,
  fetchCalendarEventDetail,
  getGoogleOAuthUrl,
} from '../services/api';

interface CalendarCardProps {
  authStatus: AuthStatusResponse | null;
}

type DateRangeFilter = 'today' | 'week' | 'upcoming';

export const CalendarCard: React.FC<CalendarCardProps> = ({ authStatus }) => {
  const [calendars, setCalendars] = useState<CalendarSummary[]>([]);
  const [selectedCalendarId, setSelectedCalendarId] = useState<string>('primary');
  const [events, setEvents] = useState<CalendarEventSummary[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Filters & Search
  const [activeFilter, setActiveFilter] = useState<DateRangeFilter>('upcoming');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [appliedSearch, setAppliedSearch] = useState<string>('');

  // Event Detail Modal
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [eventDetail, setEventDetail] = useState<CalendarEventDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState<boolean>(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const isGoogleConnected = authStatus?.google_account?.connected ?? false;
  const grantedScopes = authStatus?.google_account?.scopes ?? [];
  const hasCalendarScope = grantedScopes.some(
    (s) =>
      s === 'https://www.googleapis.com/auth/calendar.readonly' ||
      s === 'https://www.googleapis.com/auth/calendar'
  );

  // Compute time range for selected filter
  const getTimeBounds = useCallback((filter: DateRangeFilter): { timeMin: string; timeMax: string } => {
    const now = new Date();
    if (filter === 'today') {
      const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0);
      const endOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59);
      return { timeMin: startOfDay.toISOString(), timeMax: endOfDay.toISOString() };
    } else if (filter === 'week') {
      const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0);
      const endOfWeek = new Date(startOfDay.getTime() + 7 * 24 * 60 * 60 * 1000);
      return { timeMin: startOfDay.toISOString(), timeMax: endOfWeek.toISOString() };
    } else {
      // Upcoming (30 days)
      const endOf30Days = new Date(now.getTime() + 30 * 24 * 60 * 60 * 1000);
      return { timeMin: now.toISOString(), timeMax: endOf30Days.toISOString() };
    }
  }, []);

  // Load Calendars List
  const loadCalendars = useCallback(async () => {
    if (!isGoogleConnected || !hasCalendarScope) return;
    try {
      const res = await fetchCalendars();
      setCalendars(res.calendars);
      if (res.calendars.length > 0 && selectedCalendarId === 'primary') {
        const primary = res.calendars.find((c) => c.primary);
        if (primary) setSelectedCalendarId(primary.id);
      }
    } catch (err: any) {
      console.error('Failed to load calendars', err);
    }
  }, [isGoogleConnected, hasCalendarScope, selectedCalendarId]);

  // Load Events
  const loadEvents = useCallback(async () => {
    if (!isGoogleConnected || !hasCalendarScope) return;
    setLoading(true);
    setError(null);
    try {
      const bounds = getTimeBounds(activeFilter);
      const res = await fetchCalendarEvents({
        calendar_id: selectedCalendarId,
        time_min: bounds.timeMin,
        time_max: bounds.timeMax,
        query: appliedSearch || undefined,
        max_results: 30,
        single_events: true,
      });
      setEvents(res.events);
    } catch (err: any) {
      setError(err.message || 'Failed to load calendar events');
    } finally {
      setLoading(false);
    }
  }, [isGoogleConnected, hasCalendarScope, selectedCalendarId, activeFilter, appliedSearch, getTimeBounds]);

  // Load Single Event Detail
  const handleOpenEventDetail = async (eventId: string) => {
    setSelectedEventId(eventId);
    setDetailLoading(true);
    setDetailError(null);
    try {
      const detail = await fetchCalendarEventDetail(selectedCalendarId, eventId);
      setEventDetail(detail);
    } catch (err: any) {
      setDetailError(err.message || 'Failed to load event details');
    } finally {
      setDetailLoading(false);
    }
  };

  const handleCloseDetail = () => {
    setSelectedEventId(null);
    setEventDetail(null);
  };

  useEffect(() => {
    if (isGoogleConnected && hasCalendarScope) {
      loadCalendars();
      loadEvents();
    }
  }, [isGoogleConnected, hasCalendarScope, selectedCalendarId, activeFilter, appliedSearch, loadCalendars, loadEvents]);

  // Handle Search Submission
  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setAppliedSearch(searchQuery.trim());
  };

  const handleClearSearch = () => {
    setSearchQuery('');
    setAppliedSearch('');
  };

  // Helper formatting for dates
  const formatEventTime = (event: CalendarEventSummary) => {
    if (event.is_all_day) {
      return `All Day • ${event.start}`;
    }
    try {
      const startD = new Date(event.start);
      const endD = new Date(event.end);
      const dateStr = startD.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
      const startTimeStr = startD.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
      const endTimeStr = endD.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
      return `${dateStr}, ${startTimeStr} – ${endTimeStr}`;
    } catch {
      return `${event.start} – ${event.end}`;
    }
  };

  if (!isGoogleConnected) {
    return (
      <div className="glass-panel rounded-2xl p-6 sm:p-8 border border-slate-800/80 bg-slate-900/40 relative overflow-hidden">
        <div className="flex items-center justify-between pb-4 border-b border-slate-800">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
              <CalendarIcon className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white tracking-tight">Google Calendar</h2>
              <p className="text-xs text-slate-400">View upcoming events, schedule metadata & meeting links</p>
            </div>
          </div>
          <span className="text-[11px] font-medium px-2.5 py-1 rounded-full bg-slate-800 text-slate-400 border border-slate-700">
            Disconnected
          </span>
        </div>
        <div className="py-12 text-center space-y-4">
          <div className="w-12 h-12 rounded-2xl bg-slate-800/80 text-slate-500 mx-auto flex items-center justify-center">
            <Lock className="w-6 h-6" />
          </div>
          <div className="max-w-md mx-auto space-y-1.5">
            <p className="text-sm font-semibold text-slate-300">Google Account Connection Required</p>
            <p className="text-xs text-slate-500">
              Connect your Google Account above to authorize the AI assistant to read your calendars and events.
            </p>
          </div>
        </div>
      </div>
    );
  }

  if (!hasCalendarScope) {
    return (
      <div className="glass-panel rounded-2xl p-6 sm:p-8 border border-amber-500/30 bg-amber-950/10 relative overflow-hidden">
        <div className="flex items-center justify-between pb-4 border-b border-amber-500/20">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-amber-500/20 text-amber-300 border border-amber-500/30">
              <CalendarIcon className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white tracking-tight">Google Calendar Access Required</h2>
              <p className="text-xs text-amber-300/80">Incremental authorization required for Calendar read-only access</p>
            </div>
          </div>
          <span className="text-[11px] font-medium px-2.5 py-1 rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/30">
            Authorization Pending
          </span>
        </div>
        <div className="py-8 text-center space-y-4">
          <div className="w-12 h-12 rounded-2xl bg-amber-500/10 text-amber-400 border border-amber-500/20 mx-auto flex items-center justify-center">
            <AlertCircle className="w-6 h-6" />
          </div>
          <div className="max-w-md mx-auto space-y-2">
            <p className="text-sm font-semibold text-slate-200">
              Authorize Calendar Read-Only Access
            </p>
            <p className="text-xs text-slate-400 leading-relaxed">
              Your Google Account is connected with Gmail permissions. Grant read-only access to Google Calendar to view upcoming schedules, meeting invitations, and Google Meet details.
            </p>
            <div className="pt-2">
              <a
                href={getGoogleOAuthUrl()}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-amber-500 hover:bg-amber-400 text-slate-950 font-semibold text-xs shadow-lg shadow-amber-500/20 transition-all cursor-pointer"
              >
                <ShieldCheck className="w-4 h-4" />
                <span>Authorize Google Calendar</span>
              </a>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="glass-panel rounded-2xl p-6 sm:p-8 border border-slate-800/80 bg-slate-900/40 relative overflow-hidden space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-5 border-b border-slate-800">
        <div className="flex items-center gap-3.5">
          <div className="p-2.5 rounded-xl bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
            <CalendarIcon className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-bold text-white tracking-tight">Calendar — Read Only</h2>
              <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-cyan-500/15 text-cyan-300 border border-cyan-500/30">
                Connected
              </span>
            </div>
            <p className="text-xs text-slate-400">
              Synced with {authStatus?.google_account?.email || 'Google Account'}
            </p>
          </div>
        </div>

        {/* Controls: Calendar Dropdown & Refresh */}
        <div className="flex items-center gap-2.5">
          {calendars.length > 1 && (
            <div className="relative">
              <select
                value={selectedCalendarId}
                onChange={(e) => setSelectedCalendarId(e.target.value)}
                className="appearance-none bg-slate-950 border border-slate-800 text-slate-300 text-xs rounded-xl px-3 py-1.5 pr-8 focus:outline-none focus:border-cyan-500 cursor-pointer"
              >
                {calendars.map((cal) => (
                  <option key={cal.id} value={cal.id}>
                    {cal.summary} {cal.primary ? '(Primary)' : ''}
                  </option>
                ))}
              </select>
              <ChevronDown className="w-3.5 h-3.5 text-slate-500 absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
            </div>
          )}

          <button
            onClick={() => loadEvents()}
            disabled={loading}
            className="p-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors border border-slate-700 cursor-pointer disabled:opacity-50"
            title="Refresh events"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin text-cyan-400' : ''}`} />
          </button>
        </div>
      </div>

      {/* Filter Tabs & Search Bar */}
      <div className="flex flex-col md:flex-row items-stretch md:items-center justify-between gap-3">
        {/* Date Range Tabs */}
        <div className="flex items-center gap-1.5 p-1 rounded-xl bg-slate-950/80 border border-slate-800/80 text-xs">
          <button
            onClick={() => setActiveFilter('today')}
            className={`px-3 py-1.5 rounded-lg font-medium transition-all cursor-pointer ${
              activeFilter === 'today'
                ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 shadow-sm'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            Today
          </button>
          <button
            onClick={() => setActiveFilter('week')}
            className={`px-3 py-1.5 rounded-lg font-medium transition-all cursor-pointer ${
              activeFilter === 'week'
                ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 shadow-sm'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            This Week
          </button>
          <button
            onClick={() => setActiveFilter('upcoming')}
            className={`px-3 py-1.5 rounded-lg font-medium transition-all cursor-pointer ${
              activeFilter === 'upcoming'
                ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 shadow-sm'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            Upcoming (30d)
          </button>
        </div>

        {/* Search Input */}
        <form onSubmit={handleSearchSubmit} className="relative flex-1 max-w-sm">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search events (e.g. planning, sync)..."
            className="w-full bg-slate-950/80 border border-slate-800 text-xs rounded-xl pl-9 pr-8 py-2 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-cyan-500 transition-colors"
          />
          <Search className="w-3.5 h-3.5 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
          {searchQuery && (
            <button
              type="button"
              onClick={handleClearSearch}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 p-1 text-slate-500 hover:text-slate-300 rounded cursor-pointer"
            >
              <X className="w-3 h-3" />
            </button>
          )}
        </form>
      </div>

      {/* Error state */}
      {error && (
        <div className="p-3.5 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs flex items-center gap-2.5">
          <AlertCircle className="w-4 h-4 flex-shrink-0 text-rose-400" />
          <span>{error}</span>
        </div>
      )}

      {/* Events List */}
      <div className="space-y-2.5 min-h-[160px]">
        {loading ? (
          <div className="py-12 text-center text-slate-500 text-xs flex items-center justify-center gap-2">
            <RefreshCw className="w-4 h-4 animate-spin text-cyan-400" />
            <span>Retrieving Google Calendar events...</span>
          </div>
        ) : events.length === 0 ? (
          <div className="py-12 text-center space-y-2">
            <div className="w-10 h-10 rounded-xl bg-slate-800/80 text-slate-500 mx-auto flex items-center justify-center">
              <CalendarDays className="w-5 h-5" />
            </div>
            <p className="text-xs text-slate-400">No events found for the selected time range.</p>
          </div>
        ) : (
          events.map((evt) => (
            <div
              key={evt.id}
              onClick={() => handleOpenEventDetail(evt.id)}
              className="p-3.5 rounded-xl bg-slate-950/60 hover:bg-slate-900 border border-slate-800/80 hover:border-slate-700/80 transition-all cursor-pointer group flex flex-col sm:flex-row sm:items-center justify-between gap-3"
            >
              <div className="space-y-1.5 min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <h3 className="text-xs sm:text-sm font-semibold text-slate-200 group-hover:text-cyan-300 transition-colors truncate">
                    {evt.summary}
                  </h3>
                  {evt.is_all_day && (
                    <span className="text-[10px] font-medium px-2 py-0.5 rounded-md bg-indigo-500/15 text-indigo-300 border border-indigo-500/30">
                      All Day
                    </span>
                  )}
                  {evt.has_conference && (
                    <span className="text-[10px] font-medium px-2 py-0.5 rounded-md bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 flex items-center gap-1">
                      <Video className="w-2.5 h-2.5" />
                      <span>Meet</span>
                    </span>
                  )}
                </div>

                <div className="flex items-center gap-3 text-[11px] text-slate-400 flex-wrap">
                  <span className="flex items-center gap-1">
                    <Clock className="w-3 h-3 text-cyan-400" />
                    <span>{formatEventTime(evt)}</span>
                  </span>
                  {evt.location && (
                    <span className="flex items-center gap-1 truncate max-w-xs">
                      <MapPin className="w-3 h-3 text-slate-500" />
                      <span className="truncate">{evt.location}</span>
                    </span>
                  )}
                  {evt.attendees_count > 0 && (
                    <span className="flex items-center gap-1">
                      <Users className="w-3 h-3 text-slate-500" />
                      <span>{evt.attendees_count} attendee{evt.attendees_count !== 1 ? 's' : ''}</span>
                    </span>
                  )}
                </div>
              </div>

              {evt.time_zone && (
                <div className="text-[10px] text-slate-500 self-start sm:self-center font-mono">
                  {evt.time_zone}
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {/* Event Detail Modal (Read-Only) */}
      {selectedEventId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fade-in">
          <div className="glass-panel w-full max-w-lg rounded-2xl border border-slate-800 bg-slate-900/95 shadow-2xl p-6 relative max-h-[85vh] flex flex-col">
            {/* Modal Header */}
            <div className="flex items-start justify-between gap-3 pb-4 border-b border-slate-800">
              <div className="space-y-1 min-w-0">
                <h3 className="text-base font-bold text-white tracking-tight break-words">
                  {eventDetail?.summary || 'Event Details'}
                </h3>
                <div className="flex items-center gap-2 text-xs text-slate-400">
                  <span className="text-cyan-400 font-medium">
                    {eventDetail ? (eventDetail.is_all_day ? `All Day (${eventDetail.start})` : `${eventDetail.start} - ${eventDetail.end}`) : ''}
                  </span>
                </div>
              </div>
              <button
                onClick={handleCloseDetail}
                className="p-1 text-slate-400 hover:text-slate-200 rounded-lg hover:bg-slate-800 transition-colors cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Modal Content Body */}
            <div className="flex-1 overflow-y-auto py-4 space-y-4 text-xs">
              {detailLoading ? (
                <div className="py-12 text-center text-slate-500 flex items-center justify-center gap-2">
                  <RefreshCw className="w-4 h-4 animate-spin text-cyan-400" />
                  <span>Loading event details...</span>
                </div>
              ) : detailError ? (
                <div className="p-3.5 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300">
                  {detailError}
                </div>
              ) : eventDetail ? (
                <>
                  {/* Google Meet Link if available */}
                  {eventDetail.conference?.uri && (
                    <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/25 flex items-center justify-between gap-3">
                      <div className="flex items-center gap-2 text-emerald-300">
                        <Video className="w-4 h-4" />
                        <span className="font-semibold">{eventDetail.conference.solution_name || 'Google Meet'}</span>
                      </div>
                      <a
                        href={eventDetail.conference.uri}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg bg-emerald-500 text-slate-950 font-semibold hover:bg-emerald-400 transition-colors cursor-pointer"
                      >
                        <span>Join</span>
                        <ExternalLink className="w-3 h-3" />
                      </a>
                    </div>
                  )}

                  {/* Metadata fields */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-slate-300">
                    {eventDetail.location && (
                      <div className="space-y-1">
                        <span className="text-slate-500 text-[11px] font-medium">Location</span>
                        <p className="break-words">{eventDetail.location}</p>
                      </div>
                    )}
                    {eventDetail.organizer && (
                      <div className="space-y-1">
                        <span className="text-slate-500 text-[11px] font-medium">Organizer</span>
                        <p className="break-words">{eventDetail.organizer}</p>
                      </div>
                    )}
                    {eventDetail.time_zone && (
                      <div className="space-y-1">
                        <span className="text-slate-500 text-[11px] font-medium">Time Zone</span>
                        <p className="font-mono">{eventDetail.time_zone}</p>
                      </div>
                    )}
                    {eventDetail.status && (
                      <div className="space-y-1">
                        <span className="text-slate-500 text-[11px] font-medium">Status</span>
                        <p className="capitalize text-emerald-400">{eventDetail.status}</p>
                      </div>
                    )}
                  </div>

                  {/* Plain Text Description */}
                  {eventDetail.description && (
                    <div className="space-y-1.5 pt-2 border-t border-slate-800">
                      <span className="text-slate-500 text-[11px] font-medium">Description</span>
                      <div className="p-3 rounded-xl bg-slate-950/80 border border-slate-800/80 text-slate-300 whitespace-pre-wrap font-sans leading-relaxed break-words">
                        {eventDetail.description}
                      </div>
                    </div>
                  )}

                  {/* Attendees */}
                  {eventDetail.attendees.length > 0 && (
                    <div className="space-y-2 pt-2 border-t border-slate-800">
                      <span className="text-slate-500 text-[11px] font-medium">
                        Attendees ({eventDetail.attendees.length})
                      </span>
                      <div className="max-h-36 overflow-y-auto space-y-1.5 pr-1">
                        {eventDetail.attendees.map((att, idx) => (
                          <div
                            key={idx}
                            className="p-2 rounded-lg bg-slate-950/60 border border-slate-800/60 flex items-center justify-between text-xs"
                          >
                            <div className="truncate mr-2">
                              <span className="text-slate-200">{att.display_name || att.email}</span>
                              {att.display_name && att.email && (
                                <span className="text-slate-500 text-[10px] ml-1.5 truncate">({att.email})</span>
                              )}
                            </div>
                            <div className="flex items-center gap-1.5 flex-shrink-0">
                              {att.organizer && (
                                <span className="text-[9px] font-semibold px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30">
                                  Organizer
                                </span>
                              )}
                              {att.self && (
                                <span className="text-[9px] font-semibold px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-300 border border-blue-500/30">
                                  You
                                </span>
                              )}
                              <span className="text-[10px] text-slate-400 capitalize">
                                {att.response_status || 'needsAction'}
                              </span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              ) : null}
            </div>

            {/* Read-Only Notice Footer */}
            <div className="pt-3 border-t border-slate-800 flex items-center justify-between text-[11px] text-slate-500">
              <span className="flex items-center gap-1">
                <ShieldCheck className="w-3.5 h-3.5 text-cyan-400" />
                <span>Read-Only Integration</span>
              </span>
              <button
                onClick={handleCloseDetail}
                className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors cursor-pointer"
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
