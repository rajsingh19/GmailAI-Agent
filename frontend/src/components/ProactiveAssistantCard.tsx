import React, { useState, useEffect } from 'react';
import {
  Bell,
  Zap,
  Shield,
  ShieldAlert,
  Clock,
  Settings,
  RefreshCw,
  CheckCircle2,
  Mail,
  Calendar,
  CheckSquare,
  Sparkles,
  ChevronDown,
  ChevronUp,
  X,
  Moon,
  Sliders,
  Check,
  Play,
} from 'lucide-react';
import {
  ProactiveStatusResponse,
  UserPreferences,
  ProactiveNotification,
  fetchProactiveStatus,
  fetchProactivePreferences,
  updateProactivePreferences,
  fetchProactiveNotifications,
  dismissProactiveNotification,
  snoozeProactiveNotification,
  executeProactiveAction,
  triggerProactiveCheck,
  ActionExecuteResponse,
} from '../services/api';


interface ProactiveAssistantCardProps {
  onNotify?: (message: string, type: 'success' | 'error' | 'info') => void;
  onAskAgent?: (prompt: string) => void;
}

export const ProactiveAssistantCard: React.FC<ProactiveAssistantCardProps> = ({
  onNotify,
  onAskAgent,
}) => {
  const [status, setStatus] = useState<ProactiveStatusResponse | null>(null);
  const [preferences, setPreferences] = useState<UserPreferences | null>(null);
  const [notifications, setNotifications] = useState<ProactiveNotification[]>([]);
  const [loading, setLoading] = useState(false);
  const [checking, setChecking] = useState(false);
  const [savingPrefs, setSavingPrefs] = useState(false);
  const [showPreferences, setShowPreferences] = useState(false);
  const [expandedCitationId, setExpandedCitationId] = useState<string | null>(null);
  const [executingActionId, setExecutingActionId] = useState<string | null>(null);

  // Confirmation challenge state for high risk actions
  const [pendingChallenge, setPendingChallenge] = useState<{
    notificationId: string;
    actionType: string;
    targetId: string;
    challenge: any;
  } | null>(null);

  useEffect(() => {
    loadAll();
  }, []);

  const loadAll = async () => {
    setLoading(true);
    try {
      const [sData, pData, nData] = await Promise.all([
        fetchProactiveStatus().catch(() => null),
        fetchProactivePreferences().catch(() => null),
        fetchProactiveNotifications({ active_only: true }).catch(() => []),
      ]);
      if (sData) setStatus(sData);
      if (pData) setPreferences(pData);
      if (nData) setNotifications(nData);
    } catch (err: any) {
      console.error('Failed to load proactive state:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleToggleProactive = async (enabled: boolean) => {
    setSavingPrefs(true);
    try {
      const updated = await updateProactivePreferences({ proactive_enabled: enabled });
      setPreferences(updated);
      await loadAll();
      onNotify?.(
        enabled
          ? 'Proactive AI monitoring is now active'
          : 'Proactive AI monitoring disabled',
        'success'
      );
    } catch (err: any) {
      onNotify?.(err.message || 'Failed to update proactive monitoring status', 'error');
    } finally {
      setSavingPrefs(false);
    }
  };

  const handleTriggerCheck = async () => {
    setChecking(true);
    try {
      const res = await triggerProactiveCheck();
      await loadAll();
      onNotify?.(
        `Proactive check completed: ${res.candidates_detected} situations detected, ${res.notifications_created} alert(s) generated.`,
        'success'
      );
    } catch (err: any) {
      onNotify?.(err.message || 'Proactive check trigger failed', 'error');
    } finally {
      setChecking(false);
    }
  };

  const handleDismiss = async (notificationId: string) => {
    try {
      await dismissProactiveNotification(notificationId);
      setNotifications((prev) => prev.filter((n) => n.id !== notificationId));
      onNotify?.('Alert dismissed', 'info');
    } catch (err: any) {
      onNotify?.(err.message || 'Failed to dismiss notification', 'error');
    }
  };

  const handleSnooze = async (notificationId: string, minutes: number) => {
    try {
      await snoozeProactiveNotification(notificationId, minutes);
      setNotifications((prev) => prev.filter((n) => n.id !== notificationId));
      const hours = minutes >= 60 ? `${minutes / 60}h` : `${minutes}m`;
      onNotify?.(`Alert snoozed for ${hours}`, 'info');
    } catch (err: any) {
      onNotify?.(err.message || 'Failed to snooze notification', 'error');
    }
  };

  const handleExecuteAction = async (
    notification: ProactiveNotification,
    confirmedToken?: string
  ) => {
    if (!notification.suggested_action) return;
    const action = notification.suggested_action;
    setExecutingActionId(notification.id);

    try {
      const response: ActionExecuteResponse = await executeProactiveAction({
        notification_id: notification.id,
        action_type: action.action_type,
        target_id: action.target_id,
        confirmation_token: confirmedToken,
      });

      if (response.status === 'confirmation_required' && response.confirmation_challenge) {
        setPendingChallenge({
          notificationId: notification.id,
          actionType: action.action_type,
          targetId: action.target_id,
          challenge: response.confirmation_challenge,
        });
      } else if (response.status === 'completed' || response.status === 'success') {
        setPendingChallenge(null);
        setNotifications((prev) => prev.filter((n) => n.id !== notification.id));
        onNotify?.(response.message || 'Action executed successfully!', 'success');
        window.dispatchEvent(new CustomEvent('assistant-data-updated'));
      } else {
        onNotify?.(response.message || 'Action execution failed', 'error');
      }
    } catch (err: any) {
      onNotify?.(err.message || 'Failed to execute suggested action', 'error');
    } finally {
      setExecutingActionId(null);
    }
  };

  const handleUpdatePreferences = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!preferences) return;
    setSavingPrefs(true);
    try {
      const updated = await updateProactivePreferences(preferences);
      setPreferences(updated);
      setShowPreferences(false);
      onNotify?.('Proactive preferences saved successfully', 'success');
    } catch (err: any) {
      onNotify?.(err.message || 'Failed to save preferences', 'error');
    } finally {
      setSavingPrefs(false);
    }
  };

  const getSourceIcon = (sourceType: string | null) => {
    switch (sourceType) {
      case 'calendar':
        return <Calendar className="w-4 h-4 text-blue-400" />;
      case 'task':
        return <CheckSquare className="w-4 h-4 text-emerald-400" />;
      case 'reminder':
        return <Clock className="w-4 h-4 text-amber-400" />;
      case 'gmail':
        return <Mail className="w-4 h-4 text-purple-400" />;
      default:
        return <Sparkles className="w-4 h-4 text-indigo-400" />;
    }
  };

  const getPriorityBadge = (priority: string) => {
    switch (priority) {
      case 'urgent':
        return (
          <span className="px-2 py-0.5 text-xs font-semibold uppercase tracking-wider rounded-full bg-red-500/20 text-red-300 border border-red-500/40 animate-pulse">
            Urgent
          </span>
        );
      case 'high':
        return (
          <span className="px-2 py-0.5 text-xs font-semibold uppercase tracking-wider rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/40">
            High
          </span>
        );
      case 'medium':
        return (
          <span className="px-2 py-0.5 text-xs font-semibold uppercase tracking-wider rounded-full bg-blue-500/20 text-blue-300 border border-blue-500/40">
            Medium
          </span>
        );
      default:
        return (
          <span className="px-2 py-0.5 text-xs font-semibold uppercase tracking-wider rounded-full bg-gray-500/20 text-gray-300 border border-gray-500/40">
            Low
          </span>
        );
    }
  };

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden shadow-xl transition-all duration-300">
      {/* Header */}
      <div className="p-5 border-b border-gray-800 bg-gray-900/60 flex items-center justify-between flex-wrap gap-4">
        <div className="flex items-center space-x-3">
          <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-indigo-500/20 to-purple-500/20 border border-indigo-500/30 flex items-center justify-center text-indigo-400">
            <Zap className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <h2 className="text-lg font-bold text-white tracking-tight">
                Proactive AI Assistant
              </h2>
              {status?.proactive_enabled ? (
                <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 mr-1.5 animate-ping" />
                  Active Monitoring
                </span>
              ) : (
                <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-800 text-gray-400 border border-gray-700">
                  Disabled (Opt-In)
                </span>
              )}
              {status?.quiet_hours_active && (
                <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                  <Moon className="w-3 h-3 mr-1" /> Quiet Hours
                </span>
              )}
            </div>
            <p className="text-xs text-gray-400 mt-0.5">
              Intelligent multi-source monitoring across Calendar, Tasks, Reminders, and Gmail
            </p>
          </div>
        </div>

        {/* Top Controls */}
        <div className="flex items-center space-x-2">
          {/* Main Opt-In Switch */}
          <button
            id="proactive-optin-toggle"
            onClick={() => handleToggleProactive(!preferences?.proactive_enabled)}
            disabled={savingPrefs}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all flex items-center space-x-1.5 ${
              preferences?.proactive_enabled
                ? 'bg-emerald-600 hover:bg-emerald-500 text-white'
                : 'bg-gray-800 hover:bg-gray-700 text-gray-300 border border-gray-700'
            }`}
          >
            <Shield className="w-3.5 h-3.5" />
            <span>{preferences?.proactive_enabled ? 'Monitoring ON' : 'Enable Monitoring'}</span>
          </button>

          {/* Trigger Check Button */}
          <button
            id="trigger-proactive-check-btn"
            onClick={handleTriggerCheck}
            disabled={checking || !preferences?.proactive_enabled}
            title="Scan detectors immediately"
            className="px-2.5 py-1.5 bg-gray-800 hover:bg-gray-700 text-gray-300 border border-gray-700 rounded-lg text-xs font-medium transition flex items-center space-x-1 disabled:opacity-40"
          >
            <Play className={`w-3.5 h-3.5 text-indigo-400 ${checking ? 'animate-spin' : ''}`} />
            <span className="hidden sm:inline">Scan Now</span>
          </button>

          {/* Settings Drawer Button */}
          <button
            id="proactive-settings-btn"
            onClick={() => setShowPreferences(!showPreferences)}
            className="p-2 bg-gray-800 hover:bg-gray-700 text-gray-300 border border-gray-700 rounded-lg transition"
            title="Preferences"
          >
            <Sliders className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Preferences Drawer */}
      {showPreferences && preferences && (
        <form onSubmit={handleUpdatePreferences} className="p-5 bg-gray-950/80 border-b border-gray-800 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-white flex items-center space-x-2">
              <Settings className="w-4 h-4 text-indigo-400" />
              <span>Proactive Preferences & Quiet Hours</span>
            </h3>
            <button
              type="button"
              onClick={() => setShowPreferences(false)}
              className="text-gray-400 hover:text-white"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 text-xs">
            {/* Category Toggles */}
            <div className="bg-gray-900/60 p-3 rounded-lg border border-gray-800 space-y-2">
              <span className="font-semibold text-gray-300 block">Active Monitors</span>
              <label className="flex items-center space-x-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={preferences.calendar_alerts_enabled}
                  onChange={(e) =>
                    setPreferences({ ...preferences, calendar_alerts_enabled: e.target.checked })
                  }
                  className="rounded border-gray-700 bg-gray-800 text-indigo-600 focus:ring-0"
                />
                <span className="text-gray-300">Calendar Conflicts & Prep</span>
              </label>
              <label className="flex items-center space-x-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={preferences.task_alerts_enabled}
                  onChange={(e) =>
                    setPreferences({ ...preferences, task_alerts_enabled: e.target.checked })
                  }
                  className="rounded border-gray-700 bg-gray-800 text-indigo-600 focus:ring-0"
                />
                <span className="text-gray-300">Overdue & Urgent Tasks</span>
              </label>
              <label className="flex items-center space-x-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={preferences.reminder_alerts_enabled}
                  onChange={(e) =>
                    setPreferences({ ...preferences, reminder_alerts_enabled: e.target.checked })
                  }
                  className="rounded border-gray-700 bg-gray-800 text-indigo-600 focus:ring-0"
                />
                <span className="text-gray-300">Repeated Snoozing & Missed</span>
              </label>
              <label className="flex items-center space-x-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={preferences.email_alerts_enabled}
                  onChange={(e) =>
                    setPreferences({ ...preferences, email_alerts_enabled: e.target.checked })
                  }
                  className="rounded border-gray-700 bg-gray-800 text-indigo-600 focus:ring-0"
                />
                <span className="text-gray-300">Actionable Gmail Insights</span>
              </label>
            </div>

            {/* Quiet Hours */}
            <div className="bg-gray-900/60 p-3 rounded-lg border border-gray-800 space-y-2">
              <span className="font-semibold text-gray-300 block">Quiet Hours</span>
              <label className="flex items-center space-x-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={preferences.quiet_hours_enabled}
                  onChange={(e) =>
                    setPreferences({ ...preferences, quiet_hours_enabled: e.target.checked })
                  }
                  className="rounded border-gray-700 bg-gray-800 text-indigo-600 focus:ring-0"
                />
                <span className="text-gray-300">Enable Quiet Hours</span>
              </label>
              <div className="flex items-center space-x-2 pt-1">
                <input
                  type="text"
                  value={preferences.quiet_hours_start}
                  onChange={(e) =>
                    setPreferences({ ...preferences, quiet_hours_start: e.target.value })
                  }
                  placeholder="22:00"
                  className="w-16 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-center text-white"
                />
                <span className="text-gray-500">to</span>
                <input
                  type="text"
                  value={preferences.quiet_hours_end}
                  onChange={(e) =>
                    setPreferences({ ...preferences, quiet_hours_end: e.target.value })
                  }
                  placeholder="08:00"
                  className="w-16 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-center text-white"
                />
              </div>
              <label className="flex items-center space-x-2 cursor-pointer pt-1">
                <input
                  type="checkbox"
                  checked={preferences.defer_high_priority_in_quiet_hours}
                  onChange={(e) =>
                    setPreferences({
                      ...preferences,
                      defer_high_priority_in_quiet_hours: e.target.checked,
                    })
                  }
                  className="rounded border-gray-700 bg-gray-800 text-indigo-600 focus:ring-0"
                />
                <span className="text-gray-300">Defer High Priority in Quiet</span>
              </label>
            </div>

            {/* Timezone & Min Priority */}
            <div className="bg-gray-900/60 p-3 rounded-lg border border-gray-800 space-y-2">
              <span className="font-semibold text-gray-300 block">Timezone & Filter</span>
              <div>
                <label className="text-gray-400 block mb-1">User Timezone</label>
                <input
                  type="text"
                  value={preferences.user_timezone}
                  onChange={(e) =>
                    setPreferences({ ...preferences, user_timezone: e.target.value })
                  }
                  placeholder="UTC / America/New_York"
                  className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-white text-xs"
                />
              </div>
              <div className="pt-1">
                <label className="text-gray-400 block mb-1">Minimum Priority</label>
                <select
                  value={preferences.min_priority}
                  onChange={(e) =>
                    setPreferences({ ...preferences, min_priority: e.target.value as any })
                  }
                  className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-white text-xs"
                >
                  <option value="low">Low & Above</option>
                  <option value="medium">Medium & Above</option>
                  <option value="high">High & Above</option>
                  <option value="urgent">Urgent Only</option>
                </select>
              </div>
            </div>

            {/* Cost & Quota Controls */}
            <div className="bg-gray-900/60 p-3 rounded-lg border border-gray-800 space-y-2">
              <span className="font-semibold text-gray-300 block">Budget & Rate Limits</span>
              <div>
                <label className="text-gray-400 block mb-1">Max Alerts / Day ({preferences.max_proactive_per_day})</label>
                <input
                  type="number"
                  min="1"
                  max="50"
                  value={preferences.max_proactive_per_day}
                  onChange={(e) =>
                    setPreferences({
                      ...preferences,
                      max_proactive_per_day: parseInt(e.target.value) || 15,
                    })
                  }
                  className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-white text-xs"
                />
              </div>
              <div className="pt-1">
                <label className="text-gray-400 block mb-1">Cooldown (Minutes)</label>
                <input
                  type="number"
                  min="5"
                  max="1440"
                  value={preferences.cooldown_minutes}
                  onChange={(e) =>
                    setPreferences({
                      ...preferences,
                      cooldown_minutes: parseInt(e.target.value) || 30,
                    })
                  }
                  className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-white text-xs"
                />
              </div>
            </div>
          </div>

          <div className="flex justify-end space-x-2 pt-2">
            <button
              type="button"
              onClick={() => setShowPreferences(false)}
              className="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 text-gray-300 text-xs rounded-lg"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={savingPrefs}
              className="px-4 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold rounded-lg flex items-center space-x-1"
            >
              <Check className="w-3.5 h-3.5" />
              <span>Save Preferences</span>
            </button>
          </div>
        </form>
      )}

      {/* Confirmation Challenge Modal for High Risk Actions */}
      {pendingChallenge && (
        <div className="p-4 bg-amber-950/40 border-b border-amber-800/60 flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center space-x-3">
            <div className="w-9 h-9 rounded-lg bg-amber-500/20 border border-amber-500/40 flex items-center justify-center text-amber-400">
              <ShieldAlert className="w-5 h-5" />
            </div>
            <div>
              <h4 className="text-sm font-bold text-amber-200">
                Action Requires Authorization
              </h4>
              <p className="text-xs text-amber-300/80">
                {pendingChallenge.challenge.action}: {JSON.stringify(pendingChallenge.challenge.details)}
              </p>
            </div>
          </div>
          <div className="flex items-center space-x-2">
            <button
              onClick={() => setPendingChallenge(null)}
              className="px-3 py-1 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded text-xs"
            >
              Cancel
            </button>
            <button
              onClick={() => {
                const notif = notifications.find((n) => n.id === pendingChallenge.notificationId);
                if (notif) {
                  handleExecuteAction(notif, pendingChallenge.challenge.confirmation_token);
                }
              }}
              className="px-3 py-1 bg-amber-600 hover:bg-amber-500 text-white font-semibold rounded text-xs flex items-center space-x-1"
            >
              <CheckCircle2 className="w-3.5 h-3.5" />
              <span>Confirm & Execute</span>
            </button>
          </div>
        </div>
      )}

      {/* Proactive Alerts Feed */}
      <div className="p-5">
        {loading ? (
          <div className="flex items-center justify-center py-10 text-gray-500 space-x-2 text-sm">
            <RefreshCw className="w-4 h-4 animate-spin" />
            <span>Scanning proactive situations...</span>
          </div>
        ) : notifications.length === 0 ? (
          <div className="text-center py-10 border border-dashed border-gray-800 rounded-xl bg-gray-900/30">
            <Bell className="w-8 h-8 text-gray-600 mx-auto mb-2" />
            <p className="text-sm text-gray-400 font-medium">No proactive alerts</p>
            <p className="text-xs text-gray-500 mt-1 max-w-sm mx-auto">
              {preferences?.proactive_enabled
                ? 'Everything looks clear! The background monitor will notify you when deadlines, conflicts, or important emails require attention.'
                : 'Proactive monitoring is currently paused. Toggle on above to receive intelligent alerts.'}
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {notifications.map((notif) => (
              <div
                key={notif.id}
                className="bg-gray-900/80 border border-gray-800 hover:border-gray-700 rounded-xl p-4 transition-all duration-200 shadow-md"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-start space-x-3 flex-1 min-w-0">
                    <div className="mt-0.5 p-2 rounded-lg bg-gray-800/80 border border-gray-700">
                      {getSourceIcon(notif.source_type)}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center space-x-2 flex-wrap gap-1">
                        <h4 className="text-sm font-semibold text-white truncate">
                          {notif.title}
                        </h4>
                        {getPriorityBadge(notif.priority)}
                        <span className="text-[11px] text-gray-500">
                          {new Date(notif.created_at).toLocaleTimeString([], {
                            hour: '2-digit',
                            minute: '2-digit',
                          })}
                        </span>
                      </div>
                      {notif.message && (
                        <p className="text-xs text-gray-300 mt-1 leading-relaxed">
                          {notif.message}
                        </p>
                      )}

                      {/* Backend-Controlled Citations */}
                      {notif.citations && notif.citations.length > 0 && (
                        <div className="mt-2 pt-2 border-t border-gray-800/60">
                          <button
                            onClick={() =>
                              setExpandedCitationId(
                                expandedCitationId === notif.id ? null : notif.id
                              )
                            }
                            className="text-[11px] text-indigo-400 hover:text-indigo-300 flex items-center space-x-1"
                          >
                            <span>
                              {notif.citations.length} Verified Source Citation(s)
                            </span>
                            {expandedCitationId === notif.id ? (
                              <ChevronUp className="w-3 h-3" />
                            ) : (
                              <ChevronDown className="w-3 h-3" />
                            )}
                          </button>
                          {expandedCitationId === notif.id && (
                            <div className="mt-1.5 space-y-1.5 pl-2 border-l-2 border-indigo-500/40">
                              {notif.citations.map((cite, idx) => (
                                <div key={idx} className="text-[11px] text-gray-400">
                                  <span className="font-semibold text-gray-300">
                                    [{cite.source_type.toUpperCase()}] {cite.title}
                                  </span>
                                  {cite.snippet && (
                                    <p className="italic text-gray-500 mt-0.5 line-clamp-2">
                                      "{cite.snippet}"
                                    </p>
                                  )}
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Actions & Dismiss Buttons */}
                  <div className="flex items-center space-x-1.5 flex-shrink-0">
                    {/* Suggested Action Button */}
                    {notif.suggested_action && (
                      <button
                        onClick={() => handleExecuteAction(notif)}
                        disabled={executingActionId === notif.id}
                        className={`px-2.5 py-1 rounded text-xs font-semibold flex items-center space-x-1 transition ${
                          notif.suggested_action.risk_level === 'HIGH_RISK_WRITE'
                            ? 'bg-amber-600/90 hover:bg-amber-500 text-white'
                            : 'bg-indigo-600 hover:bg-indigo-500 text-white'
                        }`}
                      >
                        <Zap className="w-3 h-3" />
                        <span>{notif.suggested_action.display_label}</span>
                      </button>
                    )}

                    {/* Ask Agent */}
                    {onAskAgent && (
                      <button
                        onClick={() =>
                          onAskAgent(
                            `Can you explain this alert: "${notif.title}" (type: ${notif.notification_type}, source: ${notif.source_type})?`
                          )
                        }
                        title="Discuss with AI Assistant"
                        className="p-1 text-gray-400 hover:text-indigo-400 rounded hover:bg-gray-800 transition"
                      >
                        <Sparkles className="w-3.5 h-3.5" />
                      </button>
                    )}

                    {/* Snooze Dropdown / Quick Snooze */}
                    <button
                      onClick={() => handleSnooze(notif.id, 60)}
                      title="Snooze 1 hour"
                      className="p-1 text-gray-400 hover:text-amber-400 rounded hover:bg-gray-800 transition"
                    >
                      <Clock className="w-3.5 h-3.5" />
                    </button>

                    {/* Dismiss */}
                    <button
                      onClick={() => handleDismiss(notif.id)}
                      title="Dismiss alert"
                      className="p-1 text-gray-400 hover:text-red-400 rounded hover:bg-gray-800 transition"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
