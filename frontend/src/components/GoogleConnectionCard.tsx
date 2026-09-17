import React from 'react';
import {
  CheckCircle2,
  AlertCircle,
  Mail,
  Shield,
  LogOut,
  RefreshCw,
  ExternalLink,
  AlertTriangle,
} from 'lucide-react';
import { AuthStatusResponse, disconnectGoogleAccount, logout, getGoogleOAuthUrl } from '../services/api';

interface GoogleConnectionCardProps {
  authStatus: AuthStatusResponse | null;
  loading: boolean;
  onRefresh: () => void;
  error?: string | null;
}

export const GoogleConnectionCard: React.FC<GoogleConnectionCardProps> = ({
  authStatus,
  loading,
  onRefresh,
  error,
}) => {
  const [actionLoading, setActionLoading] = React.useState<boolean>(false);
  const [actionError, setActionError] = React.useState<string | null>(null);

  const isConnected = authStatus?.google_account?.connected ?? false;
  const isExpired = authStatus?.google_account?.is_expired ?? false;
  const requiresReauth = authStatus?.google_account?.requires_reauth ?? false;
  const googleEmail = authStatus?.google_account?.email;
  const user = authStatus?.user;

  const handleConnect = () => {
    // Standard OAuth 2.0 redirect to backend /auth/google
    window.location.href = getGoogleOAuthUrl();
  };

  const handleDisconnect = async () => {
    if (!window.confirm('Are you sure you want to disconnect your Google Account? This will revoke backend access to Gmail.')) {
      return;
    }
    setActionLoading(true);
    setActionError(null);
    try {
      await disconnectGoogleAccount();
      onRefresh();
    } catch (err: any) {
      setActionError(err.message || 'Failed to disconnect account');
    } finally {
      setActionLoading(false);
    }
  };

  const handleLogout = async () => {
    setActionLoading(true);
    try {
      await logout();
      onRefresh();
    } catch (err: any) {
      setActionError(err.message || 'Failed to log out');
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div className="glass-panel-glow rounded-2xl p-6 sm:p-8 transition-all duration-300">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pb-6 border-b border-slate-800">
        <div className="flex items-center gap-3.5">
          <div className="w-12 h-12 rounded-xl bg-gradient-to-tr from-rose-500/20 to-red-500/10 border border-rose-500/30 flex items-center justify-center text-rose-400">
            <Mail className="w-6 h-6" />
          </div>
          <div>
            <h2 className="text-xl font-semibold text-white tracking-tight flex items-center gap-2.5">
              Google Account & Gmail
              {/* Connection Status Badge */}
              {loading ? (
                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-800 text-slate-400 border border-slate-700">
                  <RefreshCw className="w-3 h-3 animate-spin" />
                  Checking...
                </span>
              ) : isConnected ? (
                requiresReauth ? (
                  <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-500/15 text-amber-400 border border-amber-500/30">
                    <AlertTriangle className="w-3 h-3" />
                    Reauthorization Required
                  </span>
                ) : isExpired ? (
                  <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-500/15 text-amber-400 border border-amber-500/30">
                    <RefreshCw className="w-3 h-3" />
                    Auto-Refreshing
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping"></span>
                    Google Connected
                  </span>
                )
              ) : (
                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-800 text-slate-400 border border-slate-700">
                  Not Connected
                </span>
              )}
            </h2>
            <p className="text-sm text-slate-400 mt-0.5">
              Secure OAuth 2.0 connection with strictly read-only Gmail access
            </p>
          </div>
        </div>

        {/* Top Actions */}
        <div className="flex items-center gap-2.5 w-full sm:w-auto">
          {isConnected && (
            <button
              id="disconnect-google-btn"
              onClick={handleDisconnect}
              disabled={actionLoading}
              className="flex-1 sm:flex-none inline-flex items-center justify-center gap-2 px-3.5 py-2 rounded-xl text-xs font-medium bg-slate-900 hover:bg-slate-800 border border-slate-700 text-rose-300 hover:text-rose-200 transition-colors disabled:opacity-50"
            >
              Disconnect Google
            </button>
          )}

          {authStatus?.authenticated && (
            <button
              id="logout-btn"
              onClick={handleLogout}
              disabled={actionLoading}
              title="Log Out Session"
              className="p-2 rounded-xl text-slate-400 hover:text-slate-200 bg-slate-900 hover:bg-slate-800 border border-slate-800 transition-colors"
            >
              <LogOut className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {/* Errors */}
      {(error || actionError) && (
        <div className="mt-5 p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 flex items-start gap-3 text-xs">
          <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0 text-rose-400" />
          <div>
            <div className="font-semibold text-sm">Authentication Notice</div>
            <div className="mt-0.5">{error || actionError}</div>
          </div>
        </div>
      )}

      {/* Body: Connected vs Not Connected */}
      <div className="mt-6">
        {isConnected ? (
          <div className="space-y-5">
            {/* Account Details Banner */}
            <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
              <div className="flex items-center gap-3.5">
                {user?.picture_url ? (
                  <img
                    src={user.picture_url}
                    alt={user.full_name || 'User avatar'}
                    className="w-12 h-12 rounded-full border border-slate-700 object-cover"
                  />
                ) : (
                  <div className="w-12 h-12 rounded-full bg-blue-600/20 border border-blue-500/30 flex items-center justify-center text-blue-400 font-semibold text-base">
                    {googleEmail ? googleEmail[0].toUpperCase() : 'G'}
                  </div>
                )}
                <div>
                  <div className="text-base font-semibold text-white flex items-center gap-2">
                    {user?.full_name || 'Google User'}
                  </div>
                  <div className="text-xs text-slate-400 mt-0.5">
                    {googleEmail}
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <span className="text-xs font-medium text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-3 py-1 rounded-full flex items-center gap-1.5">
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  Active Connection
                </span>
              </div>
            </div>

            {/* Permissions summary */}
            <div className="bg-slate-900/50 border border-slate-800/80 rounded-xl p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div className="space-y-1">
                <div className="text-xs font-medium text-slate-400 flex items-center gap-1.5">
                  <Shield className="w-3.5 h-3.5 text-blue-400" />
                  Account Permissions
                </div>
                <div className="text-xs text-slate-300">
                  Read-only access to Gmail and Google Calendar.
                </div>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-[11px] font-medium px-2.5 py-1 rounded-lg bg-blue-500/10 text-blue-400 border border-blue-500/20">
                  Gmail & Calendar Read-Only
                </span>
              </div>
            </div>
          </div>
        ) : (
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-6 bg-slate-900/50 border border-slate-800/90 rounded-xl p-6">
            <div className="space-y-1.5 max-w-xl">
              <h3 className="text-base font-semibold text-white">
                Connect your Google Account to enable Gmail intelligence
              </h3>
              <p className="text-xs sm:text-sm text-slate-400 leading-relaxed">
                Allows the Personal AI Assistant to summarize incoming emails, extract tasks, and detect meetings.
                Uses Google's official OAuth 2.0 web flow with strict read-only permissions.
              </p>
              <div className="flex items-center gap-3 pt-2 text-xs text-slate-400">
                <span className="flex items-center gap-1 text-emerald-400">
                  <CheckCircle2 className="w-3.5 h-3.5" /> Read-Only
                </span>
                <span>&bull;</span>
                <span className="flex items-center gap-1 text-emerald-400">
                  <CheckCircle2 className="w-3.5 h-3.5" /> Isolated Per User
                </span>
                <span>&bull;</span>
                <span className="flex items-center gap-1 text-emerald-400">
                  <CheckCircle2 className="w-3.5 h-3.5" /> CSRF Protected
                </span>
              </div>
            </div>

            <button
              id="connect-google-btn"
              onClick={handleConnect}
              disabled={loading}
              className="w-full sm:w-auto flex-shrink-0 inline-flex items-center justify-center gap-2.5 px-6 py-3 rounded-xl text-sm font-semibold bg-white hover:bg-slate-100 text-slate-900 transition-all shadow-lg hover:shadow-white/10 active:scale-95 cursor-pointer disabled:opacity-50"
            >
              {/* Google G Logo SVG */}
              <svg className="w-4 h-4" viewBox="0 0 24 24">
                <path
                  fill="#4285F4"
                  d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                />
                <path
                  fill="#34A853"
                  d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                />
                <path
                  fill="#FBBC05"
                  d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"
                />
                <path
                  fill="#EA4335"
                  d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"
                />
              </svg>
              Connect Google Account
              <ExternalLink className="w-3.5 h-3.5 text-slate-500" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
