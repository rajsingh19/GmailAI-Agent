import React, { useState, useEffect, useCallback } from 'react';
import {
  CheckSquare,
  Mail,
  Calendar,
  Bell,
  ArrowUpRight,
  ChevronRight,
  Clock,
} from 'lucide-react';
import {
  AuthStatusResponse,
  Task,
  GmailMessageSummary,
  CalendarEventSummary,
  Reminder,
  fetchTasks,
  fetchGmailMessages,
  fetchCalendarEvents,
  fetchReminders,
} from '../../services/api';
import { NavTab } from '../layout/AppShell';

interface DashboardPageProps {
  authStatus: AuthStatusResponse | null;
  onNavigate: (tab: NavTab) => void;
}

export const DashboardPage: React.FC<DashboardPageProps> = ({
  authStatus,
  onNavigate,
}) => {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [emails, setEmails] = useState<GmailMessageSummary[]>([]);
  const [events, setEvents] = useState<CalendarEventSummary[]>([]);
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const [loading, setLoading] = useState<boolean>(true);

  const isAuthenticated = authStatus?.authenticated ?? false;
  const isGoogleConnected = authStatus?.google_account?.connected ?? false;
  const rawName = authStatus?.user?.full_name || 'Raj Singh';
  const firstName = rawName.split(' ')[0] || 'Raj';

  const loadDashboardData = useCallback(async () => {
    if (!isAuthenticated) {
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const promises: Promise<any>[] = [
        fetchTasks({ status: 'pending' }).catch(() => ({ items: [] })),
        fetchReminders().catch(() => ({ items: [] })),
      ];

      if (isGoogleConnected) {
        promises.push(
          fetchGmailMessages({ max_results: 5, query: '' }).catch(() => ({ messages: [] }))
        );
        promises.push(
          fetchCalendarEvents({ calendar_id: 'primary', max_results: 5 }).catch(() => ({ events: [] }))
        );
      }

      const results = await Promise.all(promises);
      setTasks(results[0]?.items || []);
      setReminders(results[1]?.items || []);

      if (isGoogleConnected && results.length >= 4) {
        setEmails(results[2]?.messages || []);
        setEvents(results[3]?.events || []);
      }
    } catch {
      // Graceful fallback
    } finally {
      setLoading(false);
    }
  }, [isAuthenticated, isGoogleConnected]);

  useEffect(() => {
    loadDashboardData();
  }, [loadDashboardData]);

  // Real-time formatted date
  const now = new Date();
  const dateFormatted = now.toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });

  // Dynamic counts
  const tasksDueCount = tasks.filter((t) => t.status === 'pending').length;
  const unreadEmailsCount = emails.filter((m) => m.is_unread).length;
  const upcomingEventsCount = events.length;
  const activeRemindersCount = reminders.filter(
    (r) => r.status === 'scheduled' || r.status === 'snoozed'
  ).length;

  return (
    <div className="space-y-6">
      {/* 1. Header & Greeting */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-semibold text-[#111827] tracking-tight">
            Good Morning, {firstName}! ☀️
          </h1>
          <p className="text-xs sm:text-sm text-[#64748B] mt-0.5">
            Stay organized. Get things done. I&apos;m here to help.
          </p>
        </div>

        <div className="text-left sm:text-right">
          <div className="text-xs font-semibold text-[#111827]">{dateFormatted}</div>
          <div className="text-[11px] text-[#64748B] italic mt-0.5">
            Small steps today lead to big results tomorrow.
          </div>
        </div>
      </div>

      {/* 2. Stat Cards (4 Visually Identical Cards) */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
        {/* Card 1: Tasks Due */}
        <div
          onClick={() => onNavigate('tasks')}
          className="bg-white border border-[#E5E7EB] rounded-xl p-4 hover:border-[#D1D5DB] transition-all cursor-pointer shadow-2xs group"
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-[#64748B]">Tasks Due</span>
            <div className="w-7 h-7 rounded-lg bg-[#EEF2FF] text-[#4F46E5] flex items-center justify-center">
              <CheckSquare className="w-3.5 h-3.5" />
            </div>
          </div>
          <div className="mt-2.5 flex items-baseline gap-1.5">
            <span className="text-2xl font-bold text-[#111827] tracking-tight">
              {loading ? '—' : tasksDueCount}
            </span>
            <span className="text-[11px] text-[#94A3B8]">pending</span>
          </div>
        </div>

        {/* Card 2: Unread Emails */}
        <div
          onClick={() => onNavigate('gmail')}
          className="bg-white border border-[#E5E7EB] rounded-xl p-4 hover:border-[#D1D5DB] transition-all cursor-pointer shadow-2xs group"
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-[#64748B]">Unread Emails</span>
            <div className="w-7 h-7 rounded-lg bg-blue-50 text-blue-600 flex items-center justify-center">
              <Mail className="w-3.5 h-3.5" />
            </div>
          </div>
          <div className="mt-2.5 flex items-baseline gap-1.5">
            <span className="text-2xl font-bold text-[#111827] tracking-tight">
              {loading ? '—' : isGoogleConnected ? unreadEmailsCount : '—'}
            </span>
            <span className="text-[11px] text-[#94A3B8]">
              {isGoogleConnected ? 'inbox' : 'disconnected'}
            </span>
          </div>
        </div>

        {/* Card 3: Upcoming Events */}
        <div
          onClick={() => onNavigate('calendar')}
          className="bg-white border border-[#E5E7EB] rounded-xl p-4 hover:border-[#D1D5DB] transition-all cursor-pointer shadow-2xs group"
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-[#64748B]">Upcoming Events</span>
            <div className="w-7 h-7 rounded-lg bg-emerald-50 text-emerald-600 flex items-center justify-center">
              <Calendar className="w-3.5 h-3.5" />
            </div>
          </div>
          <div className="mt-2.5 flex items-baseline gap-1.5">
            <span className="text-2xl font-bold text-[#111827] tracking-tight">
              {loading ? '—' : isGoogleConnected ? upcomingEventsCount : '—'}
            </span>
            <span className="text-[11px] text-[#94A3B8]">
              {isGoogleConnected ? 'this week' : 'disconnected'}
            </span>
          </div>
        </div>

        {/* Card 4: Active Reminders */}
        <div
          onClick={() => onNavigate('reminders')}
          className="bg-white border border-[#E5E7EB] rounded-xl p-4 hover:border-[#D1D5DB] transition-all cursor-pointer shadow-2xs group"
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-[#64748B]">Active Reminders</span>
            <div className="w-7 h-7 rounded-lg bg-amber-50 text-amber-600 flex items-center justify-center">
              <Bell className="w-3.5 h-3.5" />
            </div>
          </div>
          <div className="mt-2.5 flex items-baseline gap-1.5">
            <span className="text-2xl font-bold text-[#111827] tracking-tight">
              {loading ? '—' : activeRemindersCount}
            </span>
            <span className="text-[11px] text-[#94A3B8]">active</span>
          </div>
        </div>
      </div>

      {/* 3. Two Equal-Width Columns: Today's Agenda + Recent Emails */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 sm:gap-6">
        {/* Left Column: Today's Agenda */}
        <div className="bg-white border border-[#E5E7EB] rounded-xl p-4 sm:p-5 shadow-2xs flex flex-col justify-between min-h-[320px]">
          <div>
            <div className="flex items-center justify-between pb-3.5 border-b border-[#E5E7EB]">
              <div className="flex items-center gap-2">
                <Calendar className="w-4 h-4 text-[#4F46E5]" />
                <h2 className="text-sm font-semibold text-[#111827]">Today&apos;s Agenda</h2>
              </div>
              <button
                onClick={() => onNavigate('calendar')}
                className="text-xs text-[#4F46E5] hover:text-[#4338CA] font-medium flex items-center gap-1 group"
              >
                <span>View Calendar</span>
                <ChevronRight className="w-3.5 h-3.5 group-hover:translate-x-0.5 transition-transform" />
              </button>
            </div>

            {/* Events List */}
            <div className="divide-y divide-slate-100 mt-1">
              {loading ? (
                <div className="py-8 text-center text-xs text-[#94A3B8]">Loading agenda...</div>
              ) : !isGoogleConnected ? (
                <div className="py-8 text-center text-xs text-[#64748B] space-y-2">
                  <p>Google Calendar is not connected.</p>
                  <button
                    onClick={() => onNavigate('settings')}
                    className="text-[#4F46E5] font-medium hover:underline inline-flex items-center gap-1"
                  >
                    <span>Connect in Settings</span>
                    <ArrowUpRight className="w-3 h-3" />
                  </button>
                </div>
              ) : events.length === 0 ? (
                <div className="py-8 text-center text-xs text-[#94A3B8]">
                  No upcoming events scheduled for today.
                </div>
              ) : (
                events.slice(0, 4).map((evt) => {
                  const startTime = evt.start
                    ? new Date(evt.start).toLocaleTimeString([], {
                        hour: '2-digit',
                        minute: '2-digit',
                      })
                    : 'All Day';
                  const endTime = evt.end
                    ? new Date(evt.end).toLocaleTimeString([], {
                        hour: '2-digit',
                        minute: '2-digit',
                      })
                    : '';

                  return (
                    <div
                      key={evt.id}
                      onClick={() => onNavigate('calendar')}
                      className="py-2.5 flex items-start gap-3 hover:bg-[#F8FAFC] rounded-lg px-2 transition-colors cursor-pointer"
                    >
                      <div className="flex items-center gap-1 text-[11px] font-semibold text-[#4F46E5] bg-[#EEF2FF] px-2 py-0.5 rounded flex-shrink-0 mt-0.5">
                        <Clock className="w-3 h-3" />
                        <span>{startTime}</span>
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="text-xs font-semibold text-[#111827] truncate">
                          {evt.summary || '(No title)'}
                        </div>
                        <div className="text-[11px] text-[#64748B] truncate mt-0.5">
                          {endTime ? `Until ${endTime}` : ''}
                          {evt.location && ` • ${evt.location}`}
                        </div>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>

        {/* Right Column: Recent Emails */}
        <div className="bg-white border border-[#E5E7EB] rounded-xl p-4 sm:p-5 shadow-2xs flex flex-col justify-between min-h-[320px]">
          <div>
            <div className="flex items-center justify-between pb-3.5 border-b border-[#E5E7EB]">
              <div className="flex items-center gap-2">
                <Mail className="w-4 h-4 text-[#4F46E5]" />
                <h2 className="text-sm font-semibold text-[#111827]">Recent Emails</h2>
              </div>
              <button
                onClick={() => onNavigate('gmail')}
                className="text-xs text-[#4F46E5] hover:text-[#4338CA] font-medium flex items-center gap-1 group"
              >
                <span>View All</span>
                <ChevronRight className="w-3.5 h-3.5 group-hover:translate-x-0.5 transition-transform" />
              </button>
            </div>

            {/* Email List Preview */}
            <div className="divide-y divide-slate-100 mt-1">
              {loading ? (
                <div className="py-8 text-center text-xs text-[#94A3B8]">Loading emails...</div>
              ) : !isGoogleConnected ? (
                <div className="py-8 text-center text-xs text-[#64748B] space-y-2">
                  <p>Gmail is not connected.</p>
                  <button
                    onClick={() => onNavigate('settings')}
                    className="text-[#4F46E5] font-medium hover:underline inline-flex items-center gap-1"
                  >
                    <span>Connect in Settings</span>
                    <ArrowUpRight className="w-3 h-3" />
                  </button>
                </div>
              ) : emails.length === 0 ? (
                <div className="py-8 text-center text-xs text-[#94A3B8]">No recent emails found.</div>
              ) : (
                emails.slice(0, 4).map((msg) => {
                  const senderInitial = msg.sender ? msg.sender.charAt(0).toUpperCase() : 'E';
                  const dateStr = msg.timestamp
                    ? new Date(msg.timestamp).toLocaleTimeString([], {
                        hour: '2-digit',
                        minute: '2-digit',
                      })
                    : '';

                  return (
                    <div
                      key={msg.id}
                      onClick={() => onNavigate('gmail')}
                      className="py-2.5 flex items-start gap-2.5 hover:bg-[#F8FAFC] rounded-lg px-2 transition-colors cursor-pointer"
                    >
                      <div className="w-6 h-6 rounded-full bg-blue-50 text-blue-600 flex items-center justify-center font-bold text-[11px] flex-shrink-0 mt-0.5">
                        {senderInitial}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center justify-between gap-2">
                          <span className={`text-xs truncate ${msg.is_unread ? 'font-bold text-[#111827]' : 'font-medium text-[#111827]'}`}>
                            {msg.sender || 'Sender'}
                          </span>
                          <span className="text-[10px] text-[#94A3B8] flex-shrink-0">{dateStr}</span>
                        </div>
                        <div className="text-xs text-[#334155] truncate">
                          {msg.subject || '(No Subject)'}
                        </div>
                        <p className="text-[11px] text-[#94A3B8] truncate mt-0.5">{msg.snippet}</p>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
