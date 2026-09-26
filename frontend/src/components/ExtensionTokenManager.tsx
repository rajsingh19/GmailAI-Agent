import React, { useEffect, useState } from 'react';
import {
  Key,
  Copy,
  Check,
  RefreshCw,
  Trash2,
  AlertTriangle,
  ShieldCheck,
  Clock,
  Layers,
  Loader2,
  Download,
} from 'lucide-react';
import {
  fetchExtensionTokenStatus,
  generateExtensionToken,
  revokeExtensionToken,
  ExtensionTokenStatus,
  ExtensionTokenCreated,
} from '../services/api';

interface ExtensionTokenManagerProps {
  onNotify?: (message: string, type: 'success' | 'error' | 'info') => void;
}

export const ExtensionTokenManager: React.FC<ExtensionTokenManagerProps> = ({ onNotify }) => {
  const [status, setStatus] = useState<ExtensionTokenStatus | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [actionLoading, setActionLoading] = useState<boolean>(false);
  const [newTokenData, setNewTokenData] = useState<ExtensionTokenCreated | null>(null);
  const [copied, setCopied] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const loadStatus = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchExtensionTokenStatus();
      setStatus(data);
    } catch (err: any) {
      setError(err.message || 'Failed to load extension token status');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStatus();
  }, []);

  const handleGenerate = async () => {
    setActionLoading(true);
    setError(null);
    try {
      const res = await generateExtensionToken('LinkedIn Browser Extension');
      setNewTokenData(res);
      await loadStatus();
      onNotify?.('New extension token generated successfully', 'success');
    } catch (err: any) {
      setError(err.message || 'Failed to generate token');
      onNotify?.(err.message || 'Failed to generate token', 'error');
    } finally {
      setActionLoading(false);
    }
  };

  const handleRevoke = async () => {
    if (!window.confirm('Are you sure you want to revoke your LinkedIn extension token? The extension will no longer be able to ingest job postings until a new token is generated.')) {
      return;
    }
    setActionLoading(true);
    setError(null);
    try {
      await revokeExtensionToken();
      setNewTokenData(null);
      await loadStatus();
      onNotify?.('Extension token revoked successfully', 'info');
    } catch (err: any) {
      setError(err.message || 'Failed to revoke token');
      onNotify?.(err.message || 'Failed to revoke token', 'error');
    } finally {
      setActionLoading(false);
    }
  };

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    onNotify?.('Token copied to clipboard', 'info');
    setTimeout(() => setCopied(false), 2500);
  };

  const formatDate = (isoString?: string | null) => {
    if (!isoString) return 'Never';
    try {
      const d = new Date(isoString);
      return d.toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return isoString;
    }
  };

  return (
    <div className="space-y-6">
      {/* Header Info */}
      <div>
        <h3 className="text-base font-semibold text-gray-900 flex items-center gap-2">
          <Layers className="w-5 h-5 text-indigo-600" />
          LinkedIn Browser Extension
        </h3>
        <p className="text-xs text-gray-500 mt-1">
          Capture single job postings directly from LinkedIn behind login walls without sharing account passwords.
        </p>
      </div>

      {error && (
        <div className="p-3.5 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-red-500 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Newly Generated Raw Token Banner */}
      {newTokenData && (
        <div className="p-4 bg-emerald-50/80 border border-emerald-300 rounded-xl space-y-3 animate-in fade-in duration-300">
          <div className="flex items-center gap-2 text-emerald-900 font-semibold text-xs">
            <ShieldCheck className="w-4 h-4 text-emerald-600" />
            <span>New Extension Token Generated (Copy Immediately)</span>
          </div>
          <p className="text-[11px] text-emerald-800">
            For security, this raw token is never stored in plaintext on the server and will not be displayed again.
          </p>

          <div className="flex items-center gap-2">
            <input
              type="text"
              readOnly
              value={newTokenData.raw_token}
              className="flex-1 px-3 py-2 bg-white border border-emerald-300 rounded-lg text-xs font-mono text-gray-800 select-all"
            />
            <button
              type="button"
              onClick={() => handleCopy(newTokenData.raw_token)}
              className="inline-flex items-center gap-1.5 px-3 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-semibold transition-colors shadow-2xs cursor-pointer flex-shrink-0"
            >
              {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
              <span>{copied ? 'Copied!' : 'Copy Token'}</span>
            </button>
          </div>
        </div>
      )}

      {/* Main Token Status Card */}
      <div className="p-5 border border-gray-200 rounded-xl bg-white shadow-2xs space-y-4">
        {loading ? (
          <div className="py-8 flex items-center justify-center gap-2 text-xs text-gray-500">
            <Loader2 className="w-4 h-4 animate-spin text-indigo-600" />
            <span>Loading token status...</span>
          </div>
        ) : (
          <>
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-gray-100">
              <div className="flex items-center gap-3">
                <div className={`w-10 h-10 rounded-lg flex items-center justify-center font-bold ${
                  status?.is_active ? 'bg-emerald-100 text-emerald-700' : 'bg-gray-100 text-gray-500'
                }`}>
                  <Key className="w-5 h-5" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-gray-900">
                      {status?.name || 'LinkedIn Browser Extension'}
                    </span>
                    <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold ${
                      status?.is_active
                        ? 'bg-emerald-100 text-emerald-800 border border-emerald-200'
                        : 'bg-gray-100 text-gray-600 border border-gray-200'
                    }`}>
                      {status?.is_active ? 'Active' : status?.has_token ? 'Revoked' : 'Not Configured'}
                    </span>
                  </div>
                  <p className="text-[11px] text-gray-500 mt-0.5 font-mono">
                    {status?.token_prefix ? `Prefix: ${status.token_prefix}` : 'No active token issued'}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={actionLoading}
                  onClick={handleGenerate}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-xs font-medium transition-colors shadow-2xs cursor-pointer disabled:opacity-50"
                >
                  {actionLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
                  <span>{status?.has_token ? 'Regenerate Token' : 'Generate Token'}</span>
                </button>

                {status?.is_active && (
                  <button
                    type="button"
                    disabled={actionLoading}
                    onClick={handleRevoke}
                    className="inline-flex items-center gap-1 px-3 py-1.5 bg-red-50 hover:bg-red-100 text-red-600 border border-red-200 rounded-lg text-xs font-medium transition-colors cursor-pointer disabled:opacity-50"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                    <span>Revoke</span>
                  </button>
                )}
              </div>
            </div>

            {/* Timestamps & Audit Stats */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-1">
              <div className="p-3 bg-gray-50/70 border border-gray-100 rounded-lg">
                <div className="text-[11px] text-gray-500 flex items-center gap-1">
                  <Clock className="w-3 h-3 text-gray-400" />
                  <span>Last Ingest Activity</span>
                </div>
                <div className="text-xs font-medium text-gray-800 mt-1">
                  {formatDate(status?.last_used_at)}
                </div>
              </div>

              <div className="p-3 bg-gray-50/70 border border-gray-100 rounded-lg">
                <div className="text-[11px] text-gray-500">Created At</div>
                <div className="text-xs font-medium text-gray-800 mt-1">
                  {formatDate(status?.created_at)}
                </div>
              </div>

              <div className="p-3 bg-gray-50/70 border border-gray-100 rounded-lg">
                <div className="text-[11px] text-gray-500">Security Model</div>
                <div className="text-xs font-medium text-emerald-700 mt-1 flex items-center gap-1">
                  <ShieldCheck className="w-3.5 h-3.5" />
                  <span>SHA-256 Hashed (Revocable)</span>
                </div>
              </div>
            </div>
          </>
        )}
      </div>

      {/* Extension Setup Guide Card */}
      <div className="p-5 border border-indigo-100 bg-indigo-50/30 rounded-xl space-y-3">
        <h4 className="text-xs font-semibold text-indigo-950 flex items-center gap-1.5">
          <Download className="w-4 h-4 text-indigo-600" />
          Extension Installation Guide
        </h4>
        <ol className="list-decimal list-inside space-y-1.5 text-xs text-indigo-900/80 leading-relaxed">
          <li>Open your browser extensions manager (e.g. <code className="px-1.5 py-0.5 bg-white rounded border border-indigo-200">chrome://extensions</code> or <code className="px-1.5 py-0.5 bg-white rounded border border-indigo-200">edge://extensions</code>).</li>
          <li>Enable <strong>Developer mode</strong> in the top right toggle.</li>
          <li>Click <strong>Load unpacked</strong> and select the <code className="px-1.5 py-0.5 bg-white rounded border border-indigo-200">extension/</code> directory from this repository.</li>
          <li>Click the extension icon in your browser toolbar, open <strong>Settings</strong>, and paste your Extension Token.</li>
          <li>Visit any LinkedIn job posting (<code className="px-1.5 py-0.5 bg-white rounded border border-indigo-200">linkedin.com/jobs/view/*</code>) and click the <strong>"Send to Job Agent"</strong> button.</li>
        </ol>
      </div>
    </div>
  );
};
