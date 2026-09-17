import React, { useState, useEffect, useCallback } from 'react';
import {
  Bell,
  BellOff,
  Send,
  Smartphone,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  ShieldCheck,
  RotateCw,
} from 'lucide-react';
import {
  fetchPushStatus,
  fetchVapidPublicKey,
  subscribePushDevice,
  unsubscribePushDevice,
  sendTestPushNotification,
  PushStatusResponse,
} from '../services/api';
import {
  isPushSupported,
  isIOS,
  isStandalone,
  getNotificationPermission,
  registerServiceWorker,
  subscribeToPush,
  getExistingSubscription,
  unsubscribeFromPush,
} from '../utils/pushManager';

interface NotificationSettingsProps {
  onClose?: () => void;
}

export const NotificationSettings: React.FC<NotificationSettingsProps> = () => {
  const [loading, setLoading] = useState<boolean>(true);
  const [actionLoading, setActionLoading] = useState<boolean>(false);
  const [pushStatus, setPushStatus] = useState<PushStatusResponse | null>(null);
  const [isSubscribedLocally, setIsSubscribedLocally] = useState<boolean>(false);
  const [permission, setPermission] = useState<NotificationPermission | 'unsupported'>('default');
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [testPushRunning, setTestPushRunning] = useState<boolean>(false);

  const supported = isPushSupported();
  const iosDevice = isIOS();
  const standaloneMode = isStandalone();

  const loadStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setPermission(getNotificationPermission());

      if (supported) {
        await registerServiceWorker();
        const existingSub = await getExistingSubscription();
        setIsSubscribedLocally(!!existingSub);
      }

      const status = await fetchPushStatus();
      setPushStatus(status);
    } catch (err: any) {
      console.warn('[PushManager] Status fetch warning:', err);
      setError('Unable to fetch push notification status at this moment.');
    } finally {
      setLoading(false);
    }
  }, [supported]);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  const handleEnablePush = async () => {
    setActionLoading(true);
    setError(null);
    setSuccessMessage(null);

    try {
      if (!supported) {
        throw new Error('Push notifications are not supported by this browser.');
      }

      if (iosDevice && !standaloneMode) {
        throw new Error(
          'On iOS, push notifications require adding this app to your Home Screen first (Share > Add to Home Screen).'
        );
      }

      // Fetch public VAPID application key from backend
      const { vapid_public_key } = await fetchVapidPublicKey();
      if (!vapid_public_key) {
        throw new Error('Push notification service is temporarily unavailable.');
      }

      // Subscribe in browser PushManager
      const subscription = await subscribeToPush(vapid_public_key);

      // Register device subscription with backend
      await subscribePushDevice(subscription);

      setIsSubscribedLocally(true);
      setPermission(getNotificationPermission());
      setSuccessMessage('Notifications enabled on this device.');
      await loadStatus();
    } catch (err: any) {
      console.warn('[PushManager] Registration error details for diagnosis:', err);
      setPermission(getNotificationPermission());

      const errMsg = err?.message || '';
      const errName = err?.name || '';

      if (errMsg.includes('Home Screen')) {
        setError(errMsg);
      } else if (errMsg.includes('denied') || permission === 'denied') {
        setError('Notification permission was blocked in browser settings. Please allow notifications to receive alerts.');
      } else if (
        errName === 'AbortError' ||
        errMsg.includes('push service') ||
        errMsg.includes('Registration failed') ||
        errMsg.includes('service worker') ||
        errName === 'NotSupportedError'
      ) {
        setError(
          "Push notifications aren't available in this browser environment. Try opening the assistant in a regular Chrome, Edge, Firefox, Android browser, or installed PWA."
        );
      } else {
        setError(
          "Push notifications aren't available in this browser environment. Try opening the assistant in a regular Chrome, Edge, Firefox, Android browser, or installed PWA."
        );
      }
    } finally {
      setActionLoading(false);
    }
  };

  const handleDisablePush = async () => {
    setActionLoading(true);
    setError(null);
    setSuccessMessage(null);

    try {
      const existingSub = await getExistingSubscription();
      if (existingSub) {
        try {
          await unsubscribePushDevice(existingSub.endpoint);
        } catch (e) {
          console.warn('[PushManager] Backend unsubscribe note:', e);
        }
        await unsubscribeFromPush();
      }

      setIsSubscribedLocally(false);
      setSuccessMessage('Push notifications disabled on this device.');
      await loadStatus();
    } catch (err: any) {
      console.warn('[PushManager] Disable notification note:', err);
      setError('Failed to disable push notifications on this device.');
    } finally {
      setActionLoading(false);
    }
  };

  const handleSendTestPush = async () => {
    setTestPushRunning(true);
    setError(null);
    setSuccessMessage(null);

    try {
      const result = await sendTestPushNotification(
        '🔔 Assistant Push Test',
        'Your Web Push setup is active and ready for reminder alerts!'
      );
      if (result.status === 'ok') {
        setSuccessMessage(
          `Test notification sent! Delivered: ${result.delivered_count}`
        );
      } else {
        setError(result.message || 'Test notification delivery could not be completed.');
      }
      await loadStatus();
    } catch (err: any) {
      console.warn('[PushManager] Test push note:', err);
      setError('Unable to send test notification. Check that a device is active.');
    } finally {
      setTestPushRunning(false);
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl relative overflow-hidden backdrop-blur-md">
      {/* Decorative top gradient accent */}
      <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-blue-500 via-indigo-500 to-purple-500" />

      {/* Header */}
      <div className="flex items-center justify-between pb-5 border-b border-slate-800/80">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-blue-500/10 border border-blue-500/20 text-blue-400">
            <Bell className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-slate-100 flex items-center gap-2">
              Web Push Notifications
              <span className="text-xs font-normal px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-300 border border-indigo-500/20">
                PWA Ready
              </span>
            </h2>
            <p className="text-xs text-slate-400">
              Receive reminder alerts and task updates directly on your phone and desktop.
            </p>
          </div>
        </div>

        <button
          onClick={loadStatus}
          disabled={loading}
          className="p-2 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors cursor-pointer"
          title="Refresh Status"
          aria-label="Refresh notification status"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Alerts */}
      {error && (
        <div className="mt-4 p-3.5 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-sm flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
          <div className="flex items-start gap-2.5">
            <AlertTriangle className="w-4 h-4 mt-0.5 flex-shrink-0 text-rose-400" />
            <div className="flex-1 leading-relaxed text-xs sm:text-sm">{error}</div>
          </div>
          <button
            onClick={handleEnablePush}
            disabled={actionLoading}
            className="self-end sm:self-center px-3 py-1.5 rounded-lg bg-rose-500/20 hover:bg-rose-500/30 text-rose-200 border border-rose-500/40 text-xs font-medium flex items-center gap-1.5 transition-colors cursor-pointer"
          >
            <RotateCw className="w-3.5 h-3.5" />
            <span>Retry</span>
          </button>
        </div>
      )}

      {successMessage && (
        <div className="mt-4 p-3.5 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-sm flex items-start gap-2.5">
          <CheckCircle2 className="w-4 h-4 mt-0.5 flex-shrink-0 text-emerald-400" />
          <div className="flex-1">{successMessage}</div>
        </div>
      )}

      {/* iOS Special Instructions Banner */}
      {iosDevice && !standaloneMode && (
        <div className="mt-4 p-4 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-200 text-xs leading-relaxed flex items-start gap-3">
          <Smartphone className="w-5 h-5 mt-0.5 text-amber-400 flex-shrink-0" />
          <div>
            <span className="font-semibold text-amber-100">iOS Setup:</span> On iPhone and iPad, Safari requires adding this app to your Home Screen to receive notifications:
            <ol className="list-decimal list-inside mt-1.5 space-y-0.5 text-amber-200/90">
              <li>Tap the <span className="font-semibold text-amber-100">Share</span> icon in Safari at the bottom bar.</li>
              <li>Select <span className="font-semibold text-amber-100">"Add to Home Screen"</span>.</li>
              <li>Open the app from your Home Screen and return here to enable notifications.</li>
            </ol>
          </div>
        </div>
      )}

      {/* Main Status & Controls */}
      <div className="mt-5 grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Device State Card */}
        <div className="bg-slate-950/60 border border-slate-800 rounded-xl p-4 flex flex-col justify-between">
          <div>
            <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold mb-2">
              Device Notification Status
            </div>
            <div className="flex items-center gap-2.5 mb-2">
              <span
                className={`w-2.5 h-2.5 rounded-full ${
                  isSubscribedLocally
                    ? 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.6)]'
                    : permission === 'denied'
                    ? 'bg-rose-400'
                    : 'bg-amber-400'
                }`}
              />
              <span className="text-sm font-medium text-slate-200">
                {isSubscribedLocally
                  ? 'Notifications Active'
                  : permission === 'denied'
                  ? 'Notifications Blocked'
                  : 'Not Subscribed'}
              </span>
            </div>

            <div className="text-xs text-slate-400 space-y-1">
              <div>
                Browser Permission:{' '}
                <span
                  className={`font-medium ${
                    permission === 'granted'
                      ? 'text-emerald-400'
                      : permission === 'denied'
                      ? 'text-rose-400'
                      : 'text-slate-300'
                  }`}
                >
                  {permission.toUpperCase()}
                </span>
              </div>
              <div>
                App Mode:{' '}
                <span className="text-slate-300">
                  {standaloneMode ? 'Installed PWA' : 'Browser Tab'}
                </span>
              </div>
            </div>
          </div>

          <div className="mt-4 pt-3 border-t border-slate-800/80 flex flex-wrap gap-2">
            {!isSubscribedLocally ? (
              <button
                onClick={handleEnablePush}
                disabled={actionLoading || permission === 'denied' || !supported}
                className="flex-1 py-2 px-3.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-medium text-xs flex items-center justify-center gap-2 transition disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-blue-600/20 cursor-pointer"
              >
                <Bell className="w-3.5 h-3.5" />
                {actionLoading ? 'Enabling...' : 'Enable Notifications'}
              </button>
            ) : (
              <button
                onClick={handleDisablePush}
                disabled={actionLoading}
                className="flex-1 py-2 px-3.5 rounded-lg bg-slate-800 hover:bg-rose-500/20 hover:text-rose-300 text-slate-300 font-medium text-xs flex items-center justify-center gap-2 transition border border-slate-700 disabled:opacity-50 cursor-pointer"
              >
                <BellOff className="w-3.5 h-3.5" />
                {actionLoading ? 'Disabling...' : 'Disable Notifications'}
              </button>
            )}

            {isSubscribedLocally && (
              <button
                onClick={handleSendTestPush}
                disabled={testPushRunning}
                className="py-2 px-3.5 rounded-lg bg-indigo-600/20 hover:bg-indigo-600/30 text-indigo-300 border border-indigo-500/30 font-medium text-xs flex items-center justify-center gap-1.5 transition disabled:opacity-50 cursor-pointer"
                title="Send test notification to all registered devices"
              >
                <Send className="w-3.5 h-3.5" />
                {testPushRunning ? 'Sending...' : 'Test'}
              </button>
            )}
          </div>
        </div>

        {/* Global Push State & Service Info */}
        <div className="bg-slate-950/60 border border-slate-800 rounded-xl p-4 flex flex-col justify-between">
          <div>
            <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold mb-2">
              Notification Service
            </div>

            <div className="space-y-2 text-xs">
              <div className="flex justify-between items-center text-slate-300">
                <span>Push Service:</span>
                <span className="font-medium text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
                  {pushStatus?.enabled ? 'Ready' : 'Disabled'}
                </span>
              </div>

              <div className="flex justify-between items-center text-slate-300">
                <span>Active Registered Devices:</span>
                <span className="font-semibold text-slate-100 bg-slate-800 px-2 py-0.5 rounded">
                  {pushStatus?.active_subscriptions ?? 0}
                </span>
              </div>

              <div className="flex justify-between items-center text-slate-300">
                <span>Alerts:</span>
                <span className="text-slate-400">Automatic</span>
              </div>
            </div>
          </div>

          <div className="mt-4 pt-3 border-t border-slate-800/80 text-[11px] text-slate-400 flex items-center gap-1.5">
            <ShieldCheck className="w-3.5 h-3.5 text-blue-400 flex-shrink-0" />
            <span>Scheduled reminders and tasks will always trigger in-app, with push notifications delivered when enabled.</span>
          </div>
        </div>
      </div>

      {/* Subscribed Devices List */}
      {pushStatus && pushStatus.devices && pushStatus.devices.length > 0 && (
        <div className="mt-5">
          <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold mb-2 flex items-center justify-between">
            <span>Registered Devices ({pushStatus.devices.length})</span>
          </div>
          <div className="space-y-2 max-h-36 overflow-y-auto pr-1">
            {pushStatus.devices.map((device, idx) => (
              <div
                key={device.id || idx}
                className="bg-slate-950/40 border border-slate-800/60 rounded-lg p-2.5 text-xs flex items-center justify-between text-slate-300"
              >
                <div className="flex items-center gap-2 overflow-hidden">
                  <Smartphone className="w-3.5 h-3.5 text-indigo-400 flex-shrink-0" />
                  <span className="truncate max-w-[280px] sm:max-w-md text-[11px] text-slate-300">
                    {device.user_agent || 'Browser Device'}
                  </span>
                </div>
                <span className="text-[10px] text-slate-500 flex-shrink-0 ml-2">
                  {new Date(device.created_at).toLocaleDateString()}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
