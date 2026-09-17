import React, { useState, useEffect, useCallback } from 'react';
import {
  Calendar as CalendarIcon,
  Clock,
  MapPin,
  ExternalLink,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  AlertCircle,
  X,
} from 'lucide-react';
import {
  AuthStatusResponse,
  CalendarEventSummary,
  CalendarEventDetail,
  fetchCalendarEvents,
  fetchCalendarEventDetail,
} from '../../services/api';

interface CalendarPageProps {
  authStatus: AuthStatusResponse | null;
}

export const CalendarPage: React.FC<CalendarPageProps> = ({ authStatus }) => {
  const isConnected = authStatus?.authenticated && authStatus?.google_account?.connected;

  const [selectedCalendarId] = useState<string>('primary');
  const [events, setEvents] = useState<CalendarEventSummary[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Current view date
  const [currentDate, setCurrentDate] = useState<Date>(new Date());
  const [viewMode, setViewMode] = useState<'day' | 'week' | 'month'>('week');

  // Mini calendar state
  const [miniDate, setMiniDate] = useState<Date>(new Date());

  // Event Detail Modal
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [eventDetail, setEventDetail] = useState<CalendarEventDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState<boolean>(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  // Calendar categories toggle
  const [activeCategories, setActiveCategories] = useState({
    personal: true,
    college: true,
    tasks: true,
    reminders: true,
  });

  const loadEvents = useCallback(async () => {
    if (!isConnected) return;
    setLoading(true);
    setError(null);

    // Compute range for current week
    const curr = new Date(currentDate);
    const firstDay = new Date(curr.setDate(curr.getDate() - curr.getDay()));
    const startOfWeek = new Date(firstDay.getFullYear(), firstDay.getMonth(), firstDay.getDate(), 0, 0, 0).toISOString();
    const endOfWeek = new Date(firstDay.getFullYear(), firstDay.getMonth(), firstDay.getDate() + 7, 23, 59, 59).toISOString();

    try {
      const res = await fetchCalendarEvents({
        calendar_id: selectedCalendarId,
        time_min: startOfWeek,
        time_max: endOfWeek,
        max_results: 30,
        single_events: true,
      });
      setEvents(res.events || []);
    } catch (err: any) {
      setError(err.message || 'Failed to load calendar events');
    } finally {
      setLoading(false);
    }
  }, [isConnected, selectedCalendarId, currentDate]);

  useEffect(() => {
    if (isConnected) {
      loadEvents();
    }
  }, [isConnected, loadEvents]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && selectedEventId) {
        setSelectedEventId(null);
        setEventDetail(null);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [selectedEventId]);

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

  const handlePrevWeek = () => {
    const d = new Date(currentDate);
    d.setDate(d.getDate() - 7);
    setCurrentDate(d);
  };

  const handleNextWeek = () => {
    const d = new Date(currentDate);
    d.setDate(d.getDate() + 7);
    setCurrentDate(d);
  };

  const handleToday = () => {
    const now = new Date();
    setCurrentDate(now);
    setMiniDate(now);
  };

  // Helper for 7 days of the week starting from Sunday
  const getDaysOfWeek = (date: Date) => {
    const curr = new Date(date);
    const first = curr.getDate() - curr.getDay();
    const days: Date[] = [];
    for (let i = 0; i < 7; i++) {
      const nextDay = new Date(curr.getFullYear(), curr.getMonth(), first + i);
      days.push(nextDay);
    }
    return days;
  };

  const daysOfWeek = getDaysOfWeek(currentDate);
  const startDayStr = daysOfWeek[0].toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  const endDayStr = daysOfWeek[6].toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });

  // 9 AM to 5 PM hours
  const hours = [9, 10, 11, 12, 13, 14, 15, 16, 17];

  // Helper to get events for a specific day and hour
  const getEventsForSlot = (day: Date, hour: number) => {
    return events.filter((evt) => {
      if (!evt.start) return false;
      const eventStart = new Date(evt.start);
      return (
        eventStart.getFullYear() === day.getFullYear() &&
        eventStart.getMonth() === day.getMonth() &&
        eventStart.getDate() === day.getDate() &&
        eventStart.getHours() === hour
      );
    });
  };

  // Helper to generate days of the month for mini calendar
  const getMiniCalendarDays = (date: Date) => {
    const year = date.getFullYear();
    const month = date.getMonth();
    const firstDay = new Date(year, month, 1).getDay();
    const daysInMonth = new Date(year, month + 1, 0).getDate();

    const matrix: (number | null)[] = [];
    for (let i = 0; i < firstDay; i++) {
      matrix.push(null);
    }
    for (let d = 1; d <= daysInMonth; d++) {
      matrix.push(d);
    }
    return matrix;
  };

  if (!isConnected) {
    return (
      <div className="saas-card p-12 text-center max-w-lg mx-auto my-12 space-y-4">
        <div className="w-12 h-12 rounded-2xl bg-emerald-50 text-emerald-600 border border-emerald-100 flex items-center justify-center mx-auto shadow-xs">
          <CalendarIcon className="w-6 h-6" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-slate-900">Google Calendar Not Connected</h2>
          <p className="text-xs text-slate-500 mt-1 leading-relaxed">
            Connect your Google account to view upcoming events, meetings, and personal schedule.
          </p>
        </div>
        <div className="pt-2">
          <a
            href="/auth/google"
            className="inline-flex items-center gap-2 px-5 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white text-xs sm:text-sm font-semibold rounded-xl shadow-xs transition-colors cursor-pointer"
          >
            <CalendarIcon className="w-4 h-4" />
            <span>Connect Google Calendar</span>
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-emerald-50 text-emerald-600 border border-emerald-100 flex items-center justify-center flex-shrink-0 shadow-xs">
            <CalendarIcon className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2.5">
              <h1 className="text-xl sm:text-2xl font-bold text-slate-900 tracking-tight">
                Google Calendar
              </h1>
              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
                Connected
              </span>
            </div>
            <p className="text-xs sm:text-sm text-slate-500">
              {authStatus?.google_account?.email || 'Connected Account'} &bull; Read-Only Access
            </p>
          </div>
        </div>

        {/* View and Date Controls */}
        <div className="flex flex-wrap items-center gap-2.5">
          <button
            onClick={handleToday}
            className="px-3 py-1.5 bg-white hover:bg-slate-50 text-slate-700 font-semibold text-xs rounded-xl border border-slate-200 shadow-2xs transition-colors cursor-pointer"
          >
            Today
          </button>

          <div className="flex items-center border border-slate-200 rounded-xl bg-white shadow-2xs">
            <button
              onClick={handlePrevWeek}
              className="p-1.5 text-slate-600 hover:bg-slate-50 rounded-l-xl transition-colors cursor-pointer"
              title="Previous Week"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <span className="px-3 text-xs font-semibold text-slate-800">
              {startDayStr} – {endDayStr}
            </span>
            <button
              onClick={handleNextWeek}
              className="p-1.5 text-slate-600 hover:bg-slate-50 rounded-r-xl transition-colors cursor-pointer"
              title="Next Week"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>

          <div className="flex items-center border border-slate-200 rounded-xl bg-white shadow-2xs p-0.5">
            <button
              onClick={() => setViewMode('day')}
              className={`px-2.5 py-1 text-xs font-medium rounded-lg transition-colors cursor-pointer ${
                viewMode === 'day' ? 'bg-indigo-50 text-indigo-600 font-semibold' : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              Day
            </button>
            <button
              onClick={() => setViewMode('week')}
              className={`px-2.5 py-1 text-xs font-medium rounded-lg transition-colors cursor-pointer ${
                viewMode === 'week' ? 'bg-indigo-50 text-indigo-600 font-semibold' : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              Week
            </button>
            <button
              onClick={() => setViewMode('month')}
              className={`px-2.5 py-1 text-xs font-medium rounded-lg transition-colors cursor-pointer ${
                viewMode === 'month' ? 'bg-indigo-50 text-indigo-600 font-semibold' : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              Month
            </button>
          </div>

          <button
            onClick={() => loadEvents()}
            disabled={loading}
            title="Refresh events"
            className="p-2 text-slate-500 hover:text-slate-700 bg-white hover:bg-slate-50 border border-slate-200 rounded-xl shadow-2xs transition-colors cursor-pointer disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin text-indigo-600' : ''}`} />
          </button>
        </div>
      </div>

      {/* Error Alert */}
      {error && (
        <div className="p-4 bg-rose-50 border border-rose-200 rounded-xl flex items-center gap-3 text-rose-700 text-sm">
          <AlertCircle className="w-5 h-5 flex-shrink-0 text-rose-500" />
          <span>{error}</span>
          <button
            onClick={() => loadEvents()}
            className="ml-auto text-xs font-semibold text-rose-700 underline hover:no-underline"
          >
            Retry
          </button>
        </div>
      )}

      {/* Main Calendar Layout: Left Sidebar + Weekly Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Left Sidebar: Mini Calendar + Calendars Filter */}
        <div className="space-y-5">
          {/* Mini Monthly Calendar Card */}
          <div className="saas-card p-4">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100 mb-3">
              <span className="text-xs font-bold text-slate-900">
                {miniDate.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })}
              </span>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => {
                    const d = new Date(miniDate);
                    d.setMonth(d.getMonth() - 1);
                    setMiniDate(d);
                  }}
                  className="p-1 hover:bg-slate-100 rounded text-slate-400 hover:text-slate-600"
                >
                  <ChevronLeft className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={() => {
                    const d = new Date(miniDate);
                    d.setMonth(d.getMonth() + 1);
                    setMiniDate(d);
                  }}
                  className="p-1 hover:bg-slate-100 rounded text-slate-400 hover:text-slate-600"
                >
                  <ChevronRight className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>

            {/* Mini Weekday Headers */}
            <div className="grid grid-cols-7 text-center text-[10px] font-semibold text-slate-400 mb-2">
              <span>S</span>
              <span>M</span>
              <span>T</span>
              <span>W</span>
              <span>T</span>
              <span>F</span>
              <span>S</span>
            </div>

            {/* Mini Days Grid */}
            <div className="grid grid-cols-7 text-center text-xs gap-y-1">
              {getMiniCalendarDays(miniDate).map((dayNum, idx) => {
                if (!dayNum) return <div key={idx} />;
                const isSelected =
                  currentDate.getDate() === dayNum &&
                  currentDate.getMonth() === miniDate.getMonth() &&
                  currentDate.getFullYear() === miniDate.getFullYear();
                const isToday =
                  new Date().getDate() === dayNum &&
                  new Date().getMonth() === miniDate.getMonth() &&
                  new Date().getFullYear() === miniDate.getFullYear();

                return (
                  <button
                    key={idx}
                    onClick={() => {
                      const newD = new Date(miniDate.getFullYear(), miniDate.getMonth(), dayNum);
                      setCurrentDate(newD);
                    }}
                    className={`w-7 h-7 mx-auto rounded-full flex items-center justify-center text-xs font-medium transition-colors ${
                      isSelected
                        ? 'bg-indigo-600 text-white font-bold'
                        : isToday
                        ? 'border border-indigo-600 text-indigo-600 font-bold'
                        : 'text-slate-700 hover:bg-slate-100'
                    }`}
                  >
                    {dayNum}
                  </button>
                );
              })}
            </div>
          </div>

          {/* My Calendars Filter Card */}
          <div className="saas-card p-4">
            <h3 className="text-xs font-bold text-slate-900 uppercase tracking-wider mb-3">
              My Calendars
            </h3>
            <div className="space-y-2.5 text-xs">
              <label className="flex items-center gap-2 text-slate-700 cursor-pointer">
                <input
                  type="checkbox"
                  checked={activeCategories.personal}
                  onChange={(e) => setActiveCategories({ ...activeCategories, personal: e.target.checked })}
                  className="rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                />
                <span className="w-2 h-2 rounded-full bg-blue-500" />
                <span>Personal</span>
              </label>

              <label className="flex items-center gap-2 text-slate-700 cursor-pointer">
                <input
                  type="checkbox"
                  checked={activeCategories.college}
                  onChange={(e) => setActiveCategories({ ...activeCategories, college: e.target.checked })}
                  className="rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
                />
                <span className="w-2 h-2 rounded-full bg-emerald-500" />
                <span>College / Work</span>
              </label>

              <label className="flex items-center gap-2 text-slate-700 cursor-pointer">
                <input
                  type="checkbox"
                  checked={activeCategories.tasks}
                  onChange={(e) => setActiveCategories({ ...activeCategories, tasks: e.target.checked })}
                  className="rounded border-slate-300 text-amber-600 focus:ring-amber-500"
                />
                <span className="w-2 h-2 rounded-full bg-amber-500" />
                <span>Tasks</span>
              </label>

              <label className="flex items-center gap-2 text-slate-700 cursor-pointer">
                <input
                  type="checkbox"
                  checked={activeCategories.reminders}
                  onChange={(e) => setActiveCategories({ ...activeCategories, reminders: e.target.checked })}
                  className="rounded border-slate-300 text-purple-600 focus:ring-purple-500"
                />
                <span className="w-2 h-2 rounded-full bg-purple-500" />
                <span>Reminders</span>
              </label>
            </div>
          </div>
        </div>

        {/* Right Main Grid: Weekly Schedule */}
        <div className="lg:col-span-3 saas-card overflow-x-auto">
          {/* Days Header */}
          <div className="grid grid-cols-8 border-b border-slate-200 bg-slate-50/70 min-w-[640px]">
            <div className="p-3 text-center border-r border-slate-200 text-xs font-semibold text-slate-400">
              Time
            </div>
            {daysOfWeek.map((day, idx) => {
              const dayName = day.toLocaleDateString(undefined, { weekday: 'short' });
              const dayNum = day.getDate();
              const isToday =
                new Date().getDate() === dayNum &&
                new Date().getMonth() === day.getMonth() &&
                new Date().getFullYear() === day.getFullYear();

              return (
                <div
                  key={idx}
                  className={`p-2.5 text-center border-r border-slate-200 last:border-r-0 ${
                    isToday ? 'bg-indigo-50/50' : ''
                  }`}
                >
                  <div className="text-[11px] font-semibold uppercase text-slate-500">{dayName}</div>
                  <div
                    className={`inline-flex items-center justify-center w-7 h-7 rounded-full text-xs font-bold mt-1 ${
                      isToday ? 'bg-indigo-600 text-white' : 'text-slate-800'
                    }`}
                  >
                    {dayNum}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Time Rows */}
          <div className="divide-y divide-slate-100 min-w-[640px]">
            {hours.map((hour) => (
              <div key={hour} className="grid grid-cols-8 min-h-[64px]">
                {/* Hour Label */}
                <div className="p-2 border-r border-slate-200 text-[11px] font-semibold text-slate-400 text-center flex items-start justify-center">
                  {hour > 12 ? `${hour - 12} PM` : hour === 12 ? '12 PM' : `${hour} AM`}
                </div>

                {/* Day Slots */}
                {daysOfWeek.map((day, dIdx) => {
                  const slotEvents = getEventsForSlot(day, hour);
                  return (
                    <div
                      key={dIdx}
                      className="p-1 border-r border-slate-200 last:border-r-0 hover:bg-slate-50/50 transition-colors space-y-1 relative"
                    >
                      {slotEvents.map((evt) => {
                        const eventColors = [
                          'bg-indigo-100 text-indigo-800 border-indigo-200',
                          'bg-blue-100 text-blue-800 border-blue-200',
                          'bg-emerald-100 text-emerald-800 border-emerald-200',
                          'bg-amber-100 text-amber-800 border-amber-200',
                          'bg-purple-100 text-purple-800 border-purple-200',
                          'bg-rose-100 text-rose-800 border-rose-200',
                        ];
                        const colorClass = eventColors[evt.summary.length % eventColors.length];

                        return (
                          <div
                            key={evt.id}
                            onClick={() => handleOpenEventDetail(evt.id)}
                            className={`p-1.5 rounded-lg border text-[11px] leading-tight cursor-pointer shadow-2xs font-semibold truncate ${colorClass}`}
                            title={evt.summary}
                          >
                            <div className="truncate">{evt.summary}</div>
                            <div className="text-[10px] font-normal opacity-80 mt-0.5">
                              {new Date(evt.start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Event Detail Modal */}
      {selectedEventId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs">
          <div className="bg-white border border-slate-200 rounded-2xl w-full max-w-md p-6 shadow-2xl relative text-slate-900">
            <div className="flex items-center justify-between pb-4 border-b border-slate-100 mb-4">
              <h3 className="text-base font-bold text-slate-900">Event Details</h3>
              <button
                onClick={() => setSelectedEventId(null)}
                className="p-1 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-100 transition-colors cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {detailLoading ? (
              <div className="py-12 text-center text-xs text-slate-400 flex items-center justify-center gap-2">
                <RefreshCw className="w-4 h-4 animate-spin text-indigo-500" />
                <span>Loading details...</span>
              </div>
            ) : detailError ? (
              <div className="p-3 bg-rose-50 border border-rose-200 rounded-xl text-rose-700 text-xs">
                {detailError}
              </div>
            ) : eventDetail ? (
              <div className="space-y-4 text-xs sm:text-sm">
                <div>
                  <h4 className="text-base font-bold text-slate-900">{eventDetail.summary}</h4>
                  {eventDetail.description && (
                    <p className="text-xs text-slate-600 mt-1 leading-relaxed">{eventDetail.description}</p>
                  )}
                </div>

                <div className="space-y-2 pt-2 border-t border-slate-100 text-xs text-slate-600">
                  <div className="flex items-center gap-2">
                    <Clock className="w-4 h-4 text-slate-400" />
                    <span>
                      {new Date(eventDetail.start).toLocaleString([], {
                        weekday: 'short',
                        month: 'short',
                        day: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </span>
                  </div>

                  {eventDetail.location && (
                    <div className="flex items-center gap-2">
                      <MapPin className="w-4 h-4 text-slate-400" />
                      <span>{eventDetail.location}</span>
                    </div>
                  )}

                  {eventDetail.html_link && (
                    <div className="flex items-center gap-2 pt-1">
                      <a
                        href={eventDetail.html_link}
                        target="_blank"
                        rel="noreferrer"
                        className="text-indigo-600 hover:text-indigo-700 flex items-center gap-1 font-semibold"
                      >
                        <ExternalLink className="w-3.5 h-3.5" />
                        <span>Open in Google Calendar</span>
                      </a>
                    </div>
                  )}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
};
