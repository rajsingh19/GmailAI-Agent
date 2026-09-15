import React, { useState, useEffect, useCallback } from 'react';
import {
  Bell,
  Plus,
  Trash2,
  Clock,
  AlertCircle,
  RefreshCw,
  X,
  Repeat,
  Check,
  Ban,
  BellRing,
  CheckCheck,
} from 'lucide-react';
import {
  Reminder,
  Notification,
  Task,
  ReminderCreateInput,
  ReminderSnoozeInput,
  fetchReminders,
  createReminder,
  snoozeReminder,
  cancelReminder,
  deleteReminder,
  fetchNotifications,
  markNotificationsRead,
  fetchTasks,
} from '../services/api';

interface ReminderCardProps {
  isAuthenticated: boolean;
}

export const ReminderCard: React.FC<ReminderCardProps> = ({ isAuthenticated }) => {
  const [activeTab, setActiveTab] = useState<'reminders' | 'notifications'>('reminders');
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [unreadCount, setUnreadCount] = useState<number>(0);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // New Reminder Modal
  const [isCreateOpen, setIsCreateOpen] = useState<boolean>(false);
  const [title, setTitle] = useState<string>('');
  const [message, setMessage] = useState<string>('');
  const [remindAt, setRemindAt] = useState<string>('');
  const [recurrenceRule, setRecurrenceRule] = useState<string>('');
  const [selectedTaskId, setSelectedTaskId] = useState<string>('');
  const [saving, setSaving] = useState<boolean>(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Snooze Modal
  const [snoozeModalReminderId, setSnoozeModalReminderId] = useState<string | null>(null);
  const [snoozePreset, setSnoozePreset] = useState<'5m' | '15m' | '30m' | '1h' | '1d'>('15m');
  const [snoozing, setSnoozing] = useState<boolean>(false);

  const loadData = useCallback(async () => {
    if (!isAuthenticated) return;
    setLoading(true);
    setError(null);
    try {
      const [remRes, notifRes, tasksRes] = await Promise.all([
        fetchReminders(),
        fetchNotifications(),
        fetchTasks({ status: 'pending' }),
      ]);
      setReminders(remRes.items);
      setNotifications(notifRes.items);
      setUnreadCount(notifRes.unread_count);
      setTasks(tasksRes.items);
    } catch (err: any) {
      setError(err.message || 'Failed to load reminders & notifications');
    } finally {
      setLoading(false);
    }
  }, [isAuthenticated]);

  // Polling notifications periodically
  useEffect(() => {
    loadData();
    if (!isAuthenticated) return;
    const interval = setInterval(async () => {
      try {
        const [notifRes, remRes] = await Promise.all([
          fetchNotifications(),
          fetchReminders(),
        ]);
        setNotifications(notifRes.items);
        setUnreadCount(notifRes.unread_count);
        setReminders(remRes.items);
      } catch {
        // silent background poll
      }
    }, 10000);
    return () => clearInterval(interval);
  }, [loadData, isAuthenticated]);

  const handleOpenCreate = () => {
    setTitle('');
    setMessage('');
    // Default to 10 minutes in the future
    const defaultTime = new Date(Date.now() + 10 * 60 * 1000);
    setRemindAt(defaultTime.toISOString().slice(0, 16));
    setRecurrenceRule('');
    setSelectedTaskId('');
    setFormError(null);
    setIsCreateOpen(true);
  };

  const handleCreateReminder = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) {
      setFormError('Reminder title is required');
      return;
    }
    if (!remindAt) {
      setFormError('Trigger date/time is required');
      return;
    }

    setSaving(true);
    setFormError(null);

    const userTz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    const remindAtIso = new Date(remindAt).toISOString();

    const payload: ReminderCreateInput = {
      title: title.trim(),
      message: message.trim() || undefined,
      remind_at: remindAtIso,
      timezone: userTz,
      recurrence_rule: recurrenceRule || undefined,
      task_id: selectedTaskId || undefined,
    };

    try {
      await createReminder(payload);
      setIsCreateOpen(false);
      await loadData();
    } catch (err: any) {
      setFormError(err.message || 'Failed to schedule reminder');
    } finally {
      setSaving(false);
    }
  };

  const handleSnooze = async () => {
    if (!snoozeModalReminderId) return;
    setSnoozing(true);
    try {
      const payload: ReminderSnoozeInput = { duration: snoozePreset };
      await snoozeReminder(snoozeModalReminderId, payload);
      setSnoozeModalReminderId(null);
      await loadData();
    } catch (err: any) {
      setError(err.message || 'Failed to snooze reminder');
    } finally {
      setSnoozing(false);
    }
  };

  const handleCancel = async (reminderId: string) => {
    try {
      await cancelReminder(reminderId);
      await loadData();
    } catch (err: any) {
      setError(err.message || 'Failed to cancel reminder');
    }
  };

  const handleDelete = async (reminderId: string) => {
    if (!confirm('Are you sure you want to delete this reminder?')) return;
    try {
      await deleteReminder(reminderId);
      await loadData();
    } catch (err: any) {
      setError(err.message || 'Failed to delete reminder');
    }
  };

  const handleMarkAllRead = async () => {
    try {
      await markNotificationsRead();
      await loadData();
    } catch (err: any) {
      setError(err.message || 'Failed to mark notifications read');
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'scheduled':
        return <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-blue-500/10 text-blue-400 border border-blue-500/20">Scheduled</span>;
      case 'processing':
        return <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-amber-500/10 text-amber-400 border border-amber-500/20 animate-pulse">Processing</span>;
      case 'snoozed':
        return <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-purple-500/10 text-purple-400 border border-purple-500/20">Snoozed</span>;
      case 'triggered':
        return <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">Triggered</span>;
      case 'cancelled':
        return <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-zinc-500/10 text-zinc-400 border border-zinc-500/20">Cancelled</span>;
      case 'failed':
        return <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-red-500/10 text-red-400 border border-red-500/20">Failed</span>;
      default:
        return <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-zinc-500/10 text-zinc-400 border border-zinc-500/20">{status}</span>;
    }
  };

  const formatTimestamp = (tsStr: string | null | undefined) => {
    if (!tsStr) return 'N/A';
    const d = new Date(tsStr);
    return d.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6 shadow-xl flex flex-col h-full text-zinc-100">
      {/* Card Header */}
      <div className="flex items-center justify-between pb-4 border-b border-zinc-800/80 mb-4">
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-amber-500/10 border border-amber-500/20 rounded-xl text-amber-400 relative">
            <Bell className="w-5 h-5" />
            {unreadCount > 0 && (
              <span className="absolute -top-1 -right-1 w-4 h-4 bg-red-500 text-white rounded-full text-[10px] font-bold flex items-center justify-center">
                {unreadCount > 9 ? '9+' : unreadCount}
              </span>
            )}
          </div>
          <div>
            <h2 className="text-lg font-semibold text-zinc-100">Reminders & Alerts</h2>
            <p className="text-xs text-zinc-400">Time-based alerts and recurring notifications</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleOpenCreate}
            disabled={!isAuthenticated}
            id="create-reminder-button"
            className="flex items-center gap-1.5 px-3 py-1.5 bg-amber-600 hover:bg-amber-500 text-white rounded-lg text-xs font-medium transition-colors disabled:opacity-50"
          >
            <Plus className="w-3.5 h-3.5" />
            New Reminder
          </button>
          <button
            onClick={loadData}
            disabled={loading || !isAuthenticated}
            title="Refresh reminders"
            className="p-1.5 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 rounded-lg transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-2 mb-4 border-b border-zinc-800 pb-2">
        <button
          onClick={() => setActiveTab('reminders')}
          className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
            activeTab === 'reminders'
              ? 'bg-zinc-800 text-zinc-100'
              : 'text-zinc-400 hover:text-zinc-200'
          }`}
        >
          Reminders ({reminders.length})
        </button>
        <button
          onClick={() => setActiveTab('notifications')}
          className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors flex items-center gap-1.5 ${
            activeTab === 'notifications'
              ? 'bg-zinc-800 text-zinc-100'
              : 'text-zinc-400 hover:text-zinc-200'
          }`}
        >
          In-App Alerts ({notifications.length})
          {unreadCount > 0 && (
            <span className="px-1.5 py-0.2 bg-amber-500/20 text-amber-300 rounded text-[10px] font-bold">
              {unreadCount} new
            </span>
          )}
        </button>

        {activeTab === 'notifications' && unreadCount > 0 && (
          <button
            onClick={handleMarkAllRead}
            className="ml-auto text-[11px] text-amber-400 hover:text-amber-300 flex items-center gap-1 transition-colors"
          >
            <CheckCheck className="w-3.5 h-3.5" />
            Mark all read
          </button>
        )}
      </div>

      {/* Error Display */}
      {error && (
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-xl flex items-center gap-2.5 text-red-400 text-xs">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Content Area */}
      <div className="flex-1 overflow-y-auto space-y-2.5 min-h-[220px] max-h-[360px] pr-1">
        {!isAuthenticated ? (
          <div className="flex flex-col items-center justify-center h-full text-center py-8 text-zinc-500">
            <Bell className="w-8 h-8 mb-2 opacity-40" />
            <p className="text-sm">Sign in to view reminders and notifications</p>
          </div>
        ) : activeTab === 'reminders' ? (
          reminders.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center py-8 text-zinc-500 border border-dashed border-zinc-800 rounded-xl">
              <Clock className="w-8 h-8 mb-2 opacity-40 text-zinc-600" />
              <p className="text-sm font-medium text-zinc-400">No active reminders</p>
              <p className="text-xs text-zinc-500 mt-0.5">Click &quot;New Reminder&quot; to schedule one.</p>
            </div>
          ) : (
            reminders.map((rem) => {
              const isActionable = rem.status === 'scheduled' || rem.status === 'snoozed';
              return (
                <div
                  key={rem.id}
                  className="group flex items-start justify-between gap-3 p-3.5 rounded-xl border bg-zinc-800/40 hover:bg-zinc-800/70 border-zinc-800/80 hover:border-zinc-700/80 transition-all"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-xs font-semibold text-zinc-200">{rem.title}</span>
                      {getStatusBadge(rem.status)}
                      {rem.recurrence_rule && (
                        <span className="flex items-center gap-1 text-[10px] text-amber-400/80 bg-amber-500/10 px-1.5 py-0.5 rounded border border-amber-500/20">
                          <Repeat className="w-2.5 h-2.5" />
                          Recurring
                        </span>
                      )}
                    </div>

                    {rem.message && (
                      <p className="text-[11px] text-zinc-400 mt-1 line-clamp-2">{rem.message}</p>
                    )}

                    <div className="flex items-center gap-3 text-[11px] text-zinc-500 mt-2 flex-wrap">
                      {rem.next_trigger_at && (
                        <div className="flex items-center gap-1 text-zinc-400">
                          <Clock className="w-3 h-3 text-amber-400" />
                          <span>Next: {formatTimestamp(rem.next_trigger_at)}</span>
                        </div>
                      )}
                      {rem.snoozed_until && (
                        <div className="flex items-center gap-1 text-purple-400">
                          <span>Snoozed until: {formatTimestamp(rem.snoozed_until)}</span>
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-1 flex-shrink-0">
                    {isActionable && (
                      <>
                        <button
                          onClick={() => setSnoozeModalReminderId(rem.id)}
                          title="Snooze reminder"
                          className="px-2 py-1 text-[11px] bg-purple-500/10 text-purple-300 border border-purple-500/20 hover:bg-purple-500/20 rounded-lg transition-colors"
                        >
                          Snooze
                        </button>
                        <button
                          onClick={() => handleCancel(rem.id)}
                          title="Cancel reminder"
                          className="p-1 text-zinc-400 hover:text-amber-400 hover:bg-amber-500/10 rounded transition-colors"
                        >
                          <Ban className="w-3.5 h-3.5" />
                        </button>
                      </>
                    )}
                    <button
                      onClick={() => handleDelete(rem.id)}
                      title="Delete reminder"
                      className="p-1 text-zinc-400 hover:text-red-400 hover:bg-red-500/10 rounded transition-colors"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              );
            })
          )
        ) : (
          /* Notifications Tab */
          notifications.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center py-8 text-zinc-500 border border-dashed border-zinc-800 rounded-xl">
              <BellRing className="w-8 h-8 mb-2 opacity-40 text-zinc-600" />
              <p className="text-sm font-medium text-zinc-400">No notifications yet</p>
              <p className="text-xs text-zinc-500 mt-0.5">When scheduled reminders trigger, they will appear here.</p>
            </div>
          ) : (
            notifications.map((notif) => {
              const isUnread = notif.status === 'unread';
              return (
                <div
                  key={notif.id}
                  className={`flex items-start justify-between gap-3 p-3.5 rounded-xl border transition-all ${
                    isUnread
                      ? 'bg-amber-500/5 border-amber-500/30'
                      : 'bg-zinc-800/30 border-zinc-800/60 opacity-75'
                  }`}
                >
                  <div className="flex items-start gap-2.5 min-w-0">
                    <div
                      className={`mt-0.5 p-1.5 rounded-lg ${
                        isUnread ? 'bg-amber-500/20 text-amber-300' : 'bg-zinc-800 text-zinc-500'
                      }`}
                    >
                      <Bell className="w-3.5 h-3.5" />
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span
                          className={`text-xs font-semibold ${
                            isUnread ? 'text-zinc-100' : 'text-zinc-400'
                          }`}
                        >
                          {notif.title}
                        </span>
                        {isUnread && (
                          <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse"></span>
                        )}
                      </div>
                      {notif.message && (
                        <p className="text-[11px] text-zinc-400 mt-0.5">{notif.message}</p>
                      )}
                      <span className="text-[10px] text-zinc-500 mt-1.5 block">
                        {formatTimestamp(notif.created_at)}
                      </span>
                    </div>
                  </div>

                  {isUnread && (
                    <button
                      onClick={async () => {
                        await markNotificationsRead([notif.id]);
                        await loadData();
                      }}
                      title="Mark as read"
                      className="p-1 text-zinc-400 hover:text-emerald-400 hover:bg-emerald-500/10 rounded transition-colors flex-shrink-0"
                    >
                      <Check className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              );
            })
          )
        )}
      </div>

      {/* Create Reminder Modal */}
      {isCreateOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl w-full max-w-md p-6 shadow-2xl relative text-zinc-100">
            <div className="flex items-center justify-between pb-4 border-b border-zinc-800 mb-4">
              <h3 className="text-base font-semibold">Schedule Reminder</h3>
              <button
                onClick={() => setIsCreateOpen(false)}
                className="p-1 text-zinc-400 hover:text-zinc-200 rounded-lg hover:bg-zinc-800 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleCreateReminder} className="space-y-4">
              {formError && (
                <div className="p-2.5 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-xs flex items-center gap-2">
                  <AlertCircle className="w-4 h-4 flex-shrink-0" />
                  <span>{formError}</span>
                </div>
              )}

              <div>
                <label className="block text-xs font-medium text-zinc-400 mb-1">
                  Reminder Title <span className="text-red-400">*</span>
                </label>
                <input
                  type="text"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="e.g., Follow up with client regarding proposal"
                  required
                  className="w-full bg-zinc-800/80 border border-zinc-700/80 rounded-xl px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:border-amber-500"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-zinc-400 mb-1">Details (Optional)</label>
                <textarea
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  placeholder="Notes or extra context for this alert..."
                  rows={2}
                  className="w-full bg-zinc-800/80 border border-zinc-700/80 rounded-xl px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:border-amber-500"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-zinc-400 mb-1">
                    Trigger Time <span className="text-red-400">*</span>
                  </label>
                  <input
                    type="datetime-local"
                    value={remindAt}
                    onChange={(e) => setRemindAt(e.target.value)}
                    required
                    className="w-full bg-zinc-800/80 border border-zinc-700/80 rounded-xl px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:border-amber-500"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-zinc-400 mb-1">Recurrence</label>
                  <select
                    value={recurrenceRule}
                    onChange={(e) => setRecurrenceRule(e.target.value)}
                    className="w-full bg-zinc-800/80 border border-zinc-700/80 rounded-xl px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:border-amber-500"
                  >
                    <option value="">One-time (No repeat)</option>
                    <option value="FREQ=DAILY">Every Day</option>
                    <option value="FREQ=WEEKLY">Every Week</option>
                    <option value="FREQ=MONTHLY">Every Month</option>
                  </select>
                </div>
              </div>

              {tasks.length > 0 && (
                <div>
                  <label className="block text-xs font-medium text-zinc-400 mb-1">Link to Task (Optional)</label>
                  <select
                    value={selectedTaskId}
                    onChange={(e) => setSelectedTaskId(e.target.value)}
                    className="w-full bg-zinc-800/80 border border-zinc-700/80 rounded-xl px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:border-amber-500"
                  >
                    <option value="">-- None --</option>
                    {tasks.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.title}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <div className="flex items-center justify-end gap-2.5 pt-4 border-t border-zinc-800">
                <button
                  type="button"
                  onClick={() => setIsCreateOpen(false)}
                  className="px-4 py-2 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded-xl text-xs font-medium transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={saving}
                  className="px-4 py-2 bg-amber-600 hover:bg-amber-500 text-white rounded-xl text-xs font-medium transition-colors disabled:opacity-50 flex items-center gap-1.5"
                >
                  {saving && <RefreshCw className="w-3.5 h-3.5 animate-spin" />}
                  Schedule Reminder
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Snooze Modal */}
      {snoozeModalReminderId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl w-full max-w-sm p-5 shadow-2xl relative text-zinc-100">
            <h3 className="text-sm font-semibold mb-3">Snooze Reminder</h3>
            <p className="text-xs text-zinc-400 mb-4">Choose how long to delay this reminder:</p>

            <div className="grid grid-cols-3 gap-2 mb-4">
              {(['5m', '15m', '30m', '1h', '1d'] as const).map((preset) => (
                <button
                  key={preset}
                  type="button"
                  onClick={() => setSnoozePreset(preset)}
                  className={`py-2 text-xs font-medium rounded-xl border transition-colors ${
                    snoozePreset === preset
                      ? 'bg-purple-600 text-white border-purple-500'
                      : 'bg-zinc-800 text-zinc-300 border-zinc-700 hover:bg-zinc-750'
                  }`}
                >
                  {preset}
                </button>
              ))}
            </div>

            <div className="flex items-center justify-end gap-2 pt-3 border-t border-zinc-800">
              <button
                type="button"
                onClick={() => setSnoozeModalReminderId(null)}
                className="px-3 py-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded-lg text-xs font-medium"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSnooze}
                disabled={snoozing}
                className="px-3 py-1.5 bg-purple-600 hover:bg-purple-500 text-white rounded-lg text-xs font-medium transition-colors"
              >
                {snoozing ? 'Snoozing...' : `Snooze (${snoozePreset})`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
