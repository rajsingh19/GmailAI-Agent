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
  Layers,
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
} from '../../services/api';

interface RemindersPageProps {
  isAuthenticated: boolean;
}

export const RemindersPage: React.FC<RemindersPageProps> = ({ isAuthenticated }) => {
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

  useEffect(() => {
    loadData();

    const handleAssistantUpdate = () => {
      loadData();
    };
    window.addEventListener('assistant-data-updated', handleAssistantUpdate);

    if (!isAuthenticated) {
      return () => {
        window.removeEventListener('assistant-data-updated', handleAssistantUpdate);
      };
    }
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
        // background silent poll
      }
    }, 10000);
    return () => clearInterval(interval);
  }, [loadData, isAuthenticated]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (isCreateOpen) setIsCreateOpen(false);
        if (snoozeModalReminderId) setSnoozeModalReminderId(null);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isCreateOpen, snoozeModalReminderId]);

  const handleOpenCreate = () => {
    setTitle('');
    setMessage('');
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
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-blue-50 text-blue-700 border border-blue-200">
            Scheduled
          </span>
        );
      case 'processing':
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-amber-50 text-amber-700 border border-amber-200 animate-pulse">
            Processing
          </span>
        );
      case 'snoozed':
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-purple-50 text-purple-700 border border-purple-200">
            Snoozed
          </span>
        );
      case 'triggered':
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
            Triggered
          </span>
        );
      case 'cancelled':
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-gray-50 text-gray-600 border border-gray-200">
            Cancelled
          </span>
        );
      case 'failed':
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-red-50 text-red-700 border border-red-200">
            Failed
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-gray-50 text-gray-600 border border-gray-200">
            {status}
          </span>
        );
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
    <div className="space-y-6">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight">Reminders & Alerts</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Time-based alerts and recurring smart notifications
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            onClick={loadData}
            disabled={loading || !isAuthenticated}
            title="Refresh"
            className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg border border-gray-200 bg-white transition-colors"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin text-indigo-600' : ''}`} />
          </button>
          <button
            onClick={handleOpenCreate}
            disabled={!isAuthenticated}
            id="create-reminder-btn"
            className="flex items-center gap-1.5 px-3.5 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-medium shadow-sm transition-colors"
          >
            <Plus className="w-4 h-4" />
            <span>New Reminder</span>
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-2 border-b border-gray-200">
        <button
          onClick={() => setActiveTab('reminders')}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
            activeTab === 'reminders'
              ? 'border-indigo-600 text-indigo-600'
              : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
          }`}
        >
          <Clock className="w-4 h-4" />
          <span>Reminders</span>
          <span className="ml-1 px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded-full text-xs font-semibold">
            {reminders.length}
          </span>
        </button>

        <button
          onClick={() => setActiveTab('notifications')}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
            activeTab === 'notifications'
              ? 'border-indigo-600 text-indigo-600'
              : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
          }`}
        >
          <Bell className="w-4 h-4" />
          <span>In-App Alerts</span>
          {unreadCount > 0 ? (
            <span className="ml-1 px-1.5 py-0.5 bg-red-50 text-red-600 border border-red-200 rounded-full text-xs font-semibold">
              {unreadCount} new
            </span>
          ) : (
            <span className="ml-1 px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded-full text-xs font-semibold">
              {notifications.length}
            </span>
          )}
        </button>

        {activeTab === 'notifications' && unreadCount > 0 && (
          <button
            onClick={handleMarkAllRead}
            className="ml-auto text-xs text-indigo-600 hover:text-indigo-700 font-medium flex items-center gap-1.5 transition-colors px-2 py-1 hover:bg-indigo-50 rounded"
          >
            <CheckCheck className="w-3.5 h-3.5" />
            <span>Mark all read</span>
          </button>
        )}
      </div>

      {/* Error Alert */}
      {error && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-xl flex items-center gap-3 text-red-700 text-sm">
          <AlertCircle className="w-5 h-5 flex-shrink-0 text-red-500" />
          <span>{error}</span>
          <button
            onClick={loadData}
            className="ml-auto text-xs font-medium text-red-700 underline hover:no-underline"
          >
            Retry
          </button>
        </div>
      )}

      {/* Main List Area */}
      <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
        {!isAuthenticated ? (
          <div className="p-12 text-center text-gray-400">
            <Bell className="w-10 h-10 mx-auto mb-3 text-gray-300" />
            <p className="text-sm font-medium text-gray-700">Sign in to view reminders</p>
            <p className="text-xs text-gray-500 mt-1">
              Your scheduled reminders and alerts will appear once connected.
            </p>
          </div>
        ) : loading && reminders.length === 0 && notifications.length === 0 ? (
          <div className="p-8 space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-16 bg-gray-50 rounded-lg animate-pulse" />
            ))}
          </div>
        ) : activeTab === 'reminders' ? (
          reminders.length === 0 ? (
            <div className="p-12 text-center text-gray-400">
              <Clock className="w-10 h-10 mx-auto mb-3 text-gray-300" />
              <p className="text-sm font-medium text-gray-700">No active reminders</p>
              <p className="text-xs text-gray-500 mt-1 mb-4">
                Click &quot;New Reminder&quot; to schedule your first alert.
              </p>
              <button
                onClick={handleOpenCreate}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-indigo-600 bg-indigo-50 hover:bg-indigo-100 rounded-lg transition-colors"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>Create Reminder</span>
              </button>
            </div>
          ) : (
            <div className="divide-y divide-gray-100">
              {reminders.map((rem) => {
                const isActionable = rem.status === 'scheduled' || rem.status === 'snoozed';
                return (
                  <div
                    key={rem.id}
                    className="p-4 hover:bg-gray-50/80 transition-colors flex items-start justify-between gap-4"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2.5 flex-wrap">
                        <span className="text-sm font-medium text-gray-900">{rem.title}</span>
                        {getStatusBadge(rem.status)}
                        {rem.recurrence_rule && (
                          <span className="inline-flex items-center gap-1 text-[11px] font-medium text-amber-700 bg-amber-50 px-2 py-0.5 rounded border border-amber-200">
                            <Repeat className="w-3 h-3" />
                            <span>{rem.recurrence_rule}</span>
                          </span>
                        )}
                        {rem.task_id && (
                          <span className="inline-flex items-center gap-1 text-[11px] font-medium text-gray-600 bg-gray-100 px-2 py-0.5 rounded">
                            <Layers className="w-3 h-3" />
                            <span>Linked to Task</span>
                          </span>
                        )}
                      </div>

                      {rem.message && (
                        <p className="text-xs text-gray-600 mt-1 line-clamp-2">{rem.message}</p>
                      )}

                      <div className="flex items-center gap-4 text-xs text-gray-500 mt-2 flex-wrap">
                        {rem.next_trigger_at && (
                          <div className="flex items-center gap-1 text-gray-600 font-medium">
                            <Clock className="w-3.5 h-3.5 text-indigo-600" />
                            <span>Next: {formatTimestamp(rem.next_trigger_at)}</span>
                          </div>
                        )}
                        {rem.snoozed_until && (
                          <div className="flex items-center gap-1 text-purple-600 font-medium">
                            <span>Snoozed until: {formatTimestamp(rem.snoozed_until)}</span>
                          </div>
                        )}
                        {rem.last_triggered_at && (
                          <span className="text-gray-400">
                            Triggered: {formatTimestamp(rem.last_triggered_at)}
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Actions */}
                    <div className="flex items-center gap-1.5 flex-shrink-0">
                      {isActionable && (
                        <>
                          <button
                            onClick={() => setSnoozeModalReminderId(rem.id)}
                            title="Snooze reminder"
                            className="px-2.5 py-1 text-xs font-medium text-purple-700 bg-purple-50 hover:bg-purple-100 border border-purple-200 rounded-md transition-colors"
                          >
                            Snooze
                          </button>
                          <button
                            onClick={() => handleCancel(rem.id)}
                            title="Cancel reminder"
                            className="p-1.5 text-gray-400 hover:text-amber-600 hover:bg-amber-50 rounded-md transition-colors"
                          >
                            <Ban className="w-4 h-4" />
                          </button>
                        </>
                      )}
                      <button
                        onClick={() => handleDelete(rem.id)}
                        title="Delete reminder"
                        className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-md transition-colors"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )
        ) : (
          /* Notifications Tab */
          notifications.length === 0 ? (
            <div className="p-12 text-center text-gray-400">
              <BellRing className="w-10 h-10 mx-auto mb-3 text-gray-300" />
              <p className="text-sm font-medium text-gray-700">No alerts yet</p>
              <p className="text-xs text-gray-500 mt-1">
                When scheduled reminders trigger or assistant notes arrive, they will appear here.
              </p>
            </div>
          ) : (
            <div className="divide-y divide-gray-100">
              {notifications.map((notif) => {
                const isUnread = notif.status === 'unread';
                return (
                  <div
                    key={notif.id}
                    className={`p-4 transition-colors flex items-start justify-between gap-3 ${
                      isUnread ? 'bg-amber-50/40' : 'hover:bg-gray-50/80 opacity-80'
                    }`}
                  >
                    <div className="flex items-start gap-3 min-w-0">
                      <div
                        className={`p-2 rounded-lg mt-0.5 flex-shrink-0 ${
                          isUnread ? 'bg-amber-100 text-amber-700' : 'bg-gray-100 text-gray-500'
                        }`}
                      >
                        <Bell className="w-4 h-4" />
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span
                            className={`text-sm font-medium ${
                              isUnread ? 'text-gray-900 font-semibold' : 'text-gray-700'
                            }`}
                          >
                            {notif.title}
                          </span>
                          {isUnread && (
                            <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse"></span>
                          )}
                        </div>
                        {notif.message && (
                          <p className="text-xs text-gray-600 mt-1">{notif.message}</p>
                        )}
                        <span className="text-[11px] text-gray-400 mt-1.5 block">
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
                        className="p-1.5 text-gray-400 hover:text-emerald-600 hover:bg-emerald-50 rounded-md transition-colors flex-shrink-0"
                      >
                        <Check className="w-4 h-4" />
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          )
        )}
      </div>

      {/* Create Reminder Modal */}
      {isCreateOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm">
          <div className="bg-white border border-gray-200 rounded-2xl w-full max-w-md p-6 shadow-xl relative text-gray-900">
            <div className="flex items-center justify-between pb-3 border-b border-gray-100 mb-4">
              <h3 className="text-base font-semibold text-gray-900">Schedule Reminder</h3>
              <button
                onClick={() => setIsCreateOpen(false)}
                className="p-1 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleCreateReminder} className="space-y-4">
              {formError && (
                <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-xs flex items-center gap-2">
                  <AlertCircle className="w-4 h-4 flex-shrink-0 text-red-500" />
                  <span>{formError}</span>
                </div>
              )}

              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">
                  Reminder Title <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="e.g. Prepare client presentation"
                  required
                  className="w-full px-3 py-2 bg-white border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">
                  Description (Optional)
                </label>
                <textarea
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  placeholder="Include any notes or checklist details..."
                  rows={2}
                  className="w-full px-3 py-2 bg-white border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">
                  Trigger Date & Time <span className="text-red-500">*</span>
                </label>
                <input
                  type="datetime-local"
                  value={remindAt}
                  onChange={(e) => setRemindAt(e.target.value)}
                  required
                  className="w-full px-3 py-2 bg-white border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">
                  Recurrence (Optional)
                </label>
                <select
                  value={recurrenceRule}
                  onChange={(e) => setRecurrenceRule(e.target.value)}
                  className="w-full px-3 py-2 bg-white border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500"
                >
                  <option value="">One-time reminder</option>
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                  <option value="monthly">Monthly</option>
                  <option value="weekdays">Every Weekday (Mon-Fri)</option>
                </select>
              </div>

              {tasks.length > 0 && (
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">
                    Link to Task (Optional)
                  </label>
                  <select
                    value={selectedTaskId}
                    onChange={(e) => setSelectedTaskId(e.target.value)}
                    className="w-full px-3 py-2 bg-white border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500"
                  >
                    <option value="">No task link</option>
                    {tasks.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.title}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <div className="flex items-center justify-end gap-2.5 pt-3 border-t border-gray-100">
                <button
                  type="button"
                  onClick={() => setIsCreateOpen(false)}
                  className="px-3.5 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg font-medium transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={saving}
                  className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-medium shadow-sm transition-colors disabled:opacity-50"
                >
                  {saving ? 'Scheduling...' : 'Schedule Reminder'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Snooze Modal */}
      {snoozeModalReminderId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm">
          <div className="bg-white border border-gray-200 rounded-2xl w-full max-w-xs p-5 shadow-xl relative text-gray-900">
            <h3 className="text-base font-semibold text-gray-900 mb-1">Snooze Reminder</h3>
            <p className="text-xs text-gray-500 mb-4">Choose how long to delay this alert:</p>

            <div className="grid grid-cols-2 gap-2 mb-4">
              {(['5m', '15m', '30m', '1h', '1d'] as const).map((preset) => (
                <button
                  key={preset}
                  type="button"
                  onClick={() => setSnoozePreset(preset)}
                  className={`py-2 px-3 text-xs font-medium rounded-lg border text-center transition-all ${
                    snoozePreset === preset
                      ? 'bg-indigo-50 border-indigo-600 text-indigo-700'
                      : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                  }`}
                >
                  {preset === '5m' && '5 Minutes'}
                  {preset === '15m' && '15 Minutes'}
                  {preset === '30m' && '30 Minutes'}
                  {preset === '1h' && '1 Hour'}
                  {preset === '1d' && '1 Day'}
                </button>
              ))}
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-gray-100">
              <button
                type="button"
                onClick={() => setSnoozeModalReminderId(null)}
                className="px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-100 rounded-lg font-medium transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSnooze}
                disabled={snoozing}
                className="px-3.5 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-xs font-medium transition-colors disabled:opacity-50"
              >
                {snoozing ? 'Snoozing...' : 'Confirm Snooze'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
