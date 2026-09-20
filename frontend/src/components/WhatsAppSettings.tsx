import React, { useState, useEffect, useCallback } from 'react';
import {
  MessageSquare,
  Smartphone,
  CheckCircle2,
  AlertTriangle,
  Send,
  RefreshCw,
  ShieldCheck,
  Power,
  Info,
  Edit2,
  X,
} from 'lucide-react';
import {
  fetchWhatsAppStatus,
  updateWhatsAppDestination,
  enableWhatsApp,
  disableWhatsApp,
  sendTestWhatsAppNotification,
  WhatsAppStatusResponse,
} from '../services/api';

// Guard: reject any value that contains masking characters — these are display-only, never real input
function isMaskedNumber(value: string): boolean {
  return value.includes('*');
}

export const WhatsAppSettings: React.FC = () => {
  const [status, setStatus] = useState<WhatsAppStatusResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [actionLoading, setActionLoading] = useState<boolean>(false);
  const [testLoading, setTestLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // Change-number UI state — separate from the display/status state
  const [changeNumberMode, setChangeNumberMode] = useState<boolean>(false);
  const [newPhoneInput, setNewPhoneInput] = useState<string>('');

  const loadStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchWhatsAppStatus();
      setStatus(res);
      // NEVER populate a phone input with the masked value.
      // The masked value is display-only and must not be submitted to the backend.
    } catch (err: any) {
      console.warn('Failed to load WhatsApp status:', err);
      setError('Unable to load WhatsApp settings at this moment.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  const handleSavePhone = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = newPhoneInput.trim();

    if (!trimmed) {
      setError('Please enter your WhatsApp phone number with country code (e.g. +919876543210).');
      return;
    }

    // Hard guard: never allow masked numbers to be submitted as real phone numbers
    if (isMaskedNumber(trimmed)) {
      setError('The displayed number is masked for security. Please enter your actual phone number in E.164 format (e.g. +919876543210).');
      return;
    }

    setActionLoading(true);
    setError(null);
    setSuccessMessage(null);

    try {
      const updated = await updateWhatsAppDestination(trimmed, true);
      setStatus(updated);
      setSuccessMessage('WhatsApp phone number saved and notifications enabled.');
      setChangeNumberMode(false);
      setNewPhoneInput('');
    } catch (err: any) {
      setError(err.message || 'Failed to save phone number. Ensure it includes the country code (e.g. +919876543210).');
    } finally {
      setActionLoading(false);
    }
  };

  const handleCancelChange = () => {
    setChangeNumberMode(false);
    setNewPhoneInput('');
    setError(null);
  };

  const handleToggleEnable = async () => {
    if (!status) return;
    setActionLoading(true);
    setError(null);
    setSuccessMessage(null);

    try {
      if (status.enabled) {
        const updated = await disableWhatsApp();
        setStatus(updated);
        setSuccessMessage('WhatsApp notifications disabled.');
      } else {
        const updated = await enableWhatsApp();
        setStatus(updated);
        setSuccessMessage('WhatsApp notifications enabled.');
      }
    } catch (err: any) {
      setError(err.message || 'Unable to update WhatsApp state.');
    } finally {
      setActionLoading(false);
    }
  };

  // The test notification endpoint identifies the user from the session token.
  // The frontend sends NO phone number — the backend retrieves and decrypts it server-side.
  const handleSendTest = async () => {
    setTestLoading(true);
    setError(null);
    setSuccessMessage(null);

    try {
      const res = await sendTestWhatsAppNotification();
      if (res.success) {
        setSuccessMessage('Test notification sent to your WhatsApp number. Check your device.');
      } else {
        // Provide actionable guidance for known error cases
        const code = res.error_code || '';
        if (code === '21654') {
          setError(
            'Twilio requires a Content Template for business-initiated messages (outside the 24-hour window). ' +
            'Add TWILIO_WHATSAPP_TEST_TEMPLATE=HXxxxxxxxx to your .env file with your Twilio Content Template SID, then restart the backend.'
          );
        } else if (code === '63007') {
          setError('You have not joined the WhatsApp Sandbox yet. Send "join <sandbox-code>" to +14155238886 from your WhatsApp device first.');
        } else {
          setError(res.message || "Couldn't send the test message. Please try again.");
        }
      }
      // Refresh status to capture delivery SID
      const refreshed = await fetchWhatsAppStatus();
      setStatus(refreshed);
    } catch (err: any) {
      setError(err.message || "Couldn't send the test message. Please try again.");
    } finally {
      setTestLoading(false);
    }
  };


  const getStatusBadge = () => {
    if (!status) return null;
    const s = status.status;
    if (s === 'enabled') {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
          <CheckCircle2 className="w-3.5 h-3.5" />
          Enabled
        </span>
      );
    }
    if (s === 'configured') {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-50 text-blue-700 border border-blue-200">
          <Smartphone className="w-3.5 h-3.5" />
          Configured
        </span>
      );
    }
    if (s === 'disabled') {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-700 border border-gray-200">
          <Power className="w-3.5 h-3.5" />
          Disabled
        </span>
      );
    }
    if (s === 'delivery_issue') {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-50 text-amber-700 border border-amber-200">
          <AlertTriangle className="w-3.5 h-3.5" />
          Delivery issue
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600 border border-gray-200">
        Not configured
      </span>
    );
  };

  if (loading) {
    return (
      <div className="py-6 flex items-center justify-center text-xs text-gray-500 gap-2">
        <RefreshCw className="w-4 h-4 animate-spin text-emerald-600" />
        Loading WhatsApp settings...
      </div>
    );
  }

  const isConfigured = Boolean(status?.configured && status?.phone_number_masked);

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-gray-100">
        <div className="flex items-start gap-3">
          <div className="p-2 bg-emerald-50 text-emerald-600 rounded-lg">
            <MessageSquare className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold text-gray-900">WhatsApp Notifications</h3>
              {status?.environment === 'sandbox' && (
                <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-100 text-amber-800 uppercase tracking-wide">
                  Sandbox
                </span>
              )}
            </div>
            <p className="text-xs text-gray-500 mt-0.5">
              Receive important reminders and assistant alerts on WhatsApp.
            </p>
          </div>
        </div>
        <div>{getStatusBadge()}</div>
      </div>

      {/* Sandbox helper banner */}
      {status?.environment === 'sandbox' && (
        <div className="p-3 bg-amber-50/70 border border-amber-200/80 rounded-lg flex items-start gap-2.5 text-xs text-amber-900">
          <Info className="w-4 h-4 text-amber-600 flex-shrink-0 mt-0.5" />
          <div>
            <span className="font-medium">Sandbox Mode:</span> To receive messages from this sandbox, send{' '}
            <code className="px-1.5 py-0.5 bg-white border border-amber-200 rounded font-mono font-bold text-amber-800">
              join &lt;sandbox-code&gt;
            </code>{' '}
            to the Twilio WhatsApp number (
            <span className="font-semibold">{status?.sender_number_masked || '+*******8886'}</span>) from your
            WhatsApp account.
          </div>
        </div>
      )}

      {/* Messages */}
      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-lg flex items-start gap-2 text-xs text-red-700">
          <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {successMessage && (
        <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-lg flex items-start gap-2 text-xs text-emerald-800">
          <CheckCircle2 className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span>{successMessage}</span>
        </div>
      )}

      {/* Phone Number Section */}
      <div className="space-y-3">
        {isConfigured && !changeNumberMode ? (
          /* ── Configured state: display masked number as READ-ONLY ── */
          <div>
            <div className="text-xs font-medium text-gray-700 mb-1">Current WhatsApp Number</div>
            <div className="flex items-center justify-between gap-3 px-3 py-2.5 bg-gray-50 border border-gray-200 rounded-lg">
              <div className="flex items-center gap-2">
                <Smartphone className="w-4 h-4 text-gray-400 flex-shrink-0" />
                {/* Masked value is display-only — never an editable or submittable value */}
                <span className="text-sm font-mono text-gray-900 select-all">
                  {status?.phone_number_masked}
                </span>
                <span className="text-[10px] text-gray-400 ml-1">(encrypted at rest)</span>
              </div>
              <button
                type="button"
                onClick={() => {
                  setChangeNumberMode(true);
                  setNewPhoneInput('');
                  setError(null);
                  setSuccessMessage(null);
                }}
                className="flex items-center gap-1 text-xs text-indigo-600 hover:text-indigo-700 font-medium whitespace-nowrap"
              >
                <Edit2 className="w-3.5 h-3.5" />
                Change Number
              </button>
            </div>
          </div>
        ) : (
          /* ── Unconfigured or Change-Number mode: show real input ── */
          <form onSubmit={handleSavePhone} className="space-y-3">
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">
                {changeNumberMode ? 'New WhatsApp Phone Number' : 'WhatsApp Phone Number'}
              </label>
              <div className="flex gap-2">
                <input
                  id="whatsapp-phone-input"
                  type="tel"
                  value={newPhoneInput}
                  onChange={(e) => setNewPhoneInput(e.target.value)}
                  placeholder="+919876543210"
                  autoFocus={changeNumberMode}
                  autoComplete="tel"
                  className="flex-1 px-3 py-2 text-xs border border-gray-300 rounded-lg shadow-sm focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 bg-white"
                />
                <button
                  type="submit"
                  disabled={actionLoading}
                  className="px-4 py-2 text-xs font-medium text-white bg-emerald-600 hover:bg-emerald-700 rounded-lg shadow-sm disabled:opacity-50 transition-colors flex items-center gap-1.5"
                >
                  {actionLoading ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : null}
                  Save
                </button>
                {changeNumberMode && (
                  <button
                    type="button"
                    onClick={handleCancelChange}
                    disabled={actionLoading}
                    className="px-3 py-2 text-xs font-medium text-gray-600 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors flex items-center gap-1"
                  >
                    <X className="w-3.5 h-3.5" />
                    Cancel
                  </button>
                )}
              </div>
              <p className="text-[11px] text-gray-500 mt-1">
                Use international E.164 format with country code (e.g. +919876543210). Numbers are encrypted at rest.
              </p>
            </div>
          </form>
        )}
      </div>

      {/* Opt-In & Delivery Actions */}
      <div className="pt-3 border-t border-gray-100 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={Boolean(status?.enabled)}
            onChange={handleToggleEnable}
            disabled={actionLoading || !isConfigured}
            className="w-4 h-4 text-emerald-600 rounded border-gray-300 focus:ring-emerald-500"
          />
          <span className="text-xs font-medium text-gray-800">
            Enable WhatsApp notifications
          </span>
        </label>

        <div className="flex items-center gap-2">
          {status?.enabled && (
            <button
              type="button"
              onClick={handleToggleEnable}
              disabled={actionLoading}
              className="px-3 py-1.5 text-xs font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
            >
              Disable WhatsApp
            </button>
          )}

          {/* Test notification: sends NO phone number. Backend uses authenticated user's encrypted DB record. */}
          <button
            type="button"
            id="whatsapp-send-test-btn"
            onClick={handleSendTest}
            disabled={testLoading || !status?.enabled}
            className="px-3 py-1.5 text-xs font-medium text-emerald-700 bg-emerald-50 hover:bg-emerald-100 border border-emerald-200 rounded-lg shadow-sm transition-colors flex items-center gap-1.5 disabled:opacity-50"
          >
            {testLoading ? (
              <RefreshCw className="w-3.5 h-3.5 animate-spin text-emerald-600" />
            ) : (
              <Send className="w-3.5 h-3.5" />
            )}
            Send Test Notification
          </button>
        </div>
      </div>

      {/* Security & Privacy note */}
      <div className="p-3 bg-gray-50 rounded-lg flex items-start gap-2 text-[11px] text-gray-500">
        <ShieldCheck className="w-4 h-4 text-emerald-600 flex-shrink-0 mt-0.5" />
        <span>
          WhatsApp alerts are best-effort and asynchronous. Your phone number is encrypted at rest using AES Fernet,
          and messages follow backend-approved templates.
        </span>
      </div>
    </div>
  );
};
