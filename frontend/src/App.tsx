import React, { useEffect, useState, useCallback } from 'react';
import { Bot, Sparkles, ShieldAlert, Cpu, CheckCircle2, AlertCircle, X } from 'lucide-react';
import { fetchHealth, fetchAuthStatus, HealthCheckResult, AuthStatusResponse } from './services/api';
import { HealthStatusCard } from './components/HealthStatusCard';
import { GoogleConnectionCard } from './components/GoogleConnectionCard';
import { SystemOverview } from './components/SystemOverview';

export const App: React.FC = () => {
  const [health, setHealth] = useState<HealthCheckResult | null>(null);
  const [healthLoading, setHealthLoading] = useState<boolean>(true);

  const [authStatus, setAuthStatus] = useState<AuthStatusResponse | null>(null);
  const [authLoading, setAuthLoading] = useState<boolean>(true);
  const [authError, setAuthError] = useState<string | null>(null);

  const [bannerNotice, setBannerNotice] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  const checkBackendHealth = useCallback(async () => {
    setHealthLoading(true);
    const result = await fetchHealth();
    setHealth(result);
    setHealthLoading(false);
  }, []);

  const checkAuthStatus = useCallback(async () => {
    setAuthLoading(true);
    setAuthError(null);
    try {
      const status = await fetchAuthStatus();
      setAuthStatus(status);
    } catch (err: any) {
      setAuthError(err.message || 'Unable to fetch authentication status');
    } finally {
      setAuthLoading(false);
    }
  }, []);

  useEffect(() => {
    // 1. Initial health and auth status checks
    checkBackendHealth();
    checkAuthStatus();

    // 2. Check for redirect query parameters from OAuth callback
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.has('auth') && urlParams.get('auth') === 'success') {
      setBannerNotice({
        type: 'success',
        message: 'Google Account successfully connected! Gmail read-only access is enabled.',
      });
      // Clean query parameters from address bar
      window.history.replaceState({}, '', window.location.pathname);
      checkAuthStatus();
    } else if (urlParams.has('auth_error')) {
      const errCode = urlParams.get('auth_error');
      setBannerNotice({
        type: 'error',
        message: `Google OAuth flow failed or was cancelled (${errCode}). Please try again.`,
      });
      window.history.replaceState({}, '', window.location.pathname);
    }
  }, [checkBackendHealth, checkAuthStatus]);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col relative overflow-hidden">
      {/* Background glow effects */}
      <div className="absolute top-0 left-1/4 w-96 h-96 bg-blue-600/10 rounded-full blur-3xl pointer-events-none -z-0"></div>
      <div className="absolute top-1/3 right-1/4 w-96 h-96 bg-purple-600/10 rounded-full blur-3xl pointer-events-none -z-0"></div>

      {/* Navigation Header */}
      <header className="border-b border-slate-800/80 bg-slate-950/70 backdrop-blur-md sticky top-0 z-50">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-blue-600 to-indigo-500 flex items-center justify-center shadow-lg shadow-blue-500/25">
              <Bot className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-base sm:text-lg font-bold tracking-tight text-white flex items-center gap-2">
                Personal AI Assistant
                <span className="hidden sm:inline-flex items-center text-[10px] font-semibold uppercase tracking-wider bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 px-2 py-0.5 rounded-full">
                  Milestone 2 Active
                </span>
              </h1>
            </div>
          </div>

          <div className="flex items-center gap-3 text-xs">
            <div className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-slate-400">
              <Cpu className="w-3.5 h-3.5 text-blue-400" />
              <span>FastAPI &bull; Port 8000</span>
            </div>
            <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-slate-400">
              <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
              <span>React 18 + Vite</span>
            </div>
          </div>
        </div>
      </header>

      {/* Toast / Notification Banner */}
      {bannerNotice && (
        <div className={`border-b px-4 py-3 text-xs sm:text-sm flex items-center justify-between z-40 transition-all ${
          bannerNotice.type === 'success'
            ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
            : 'bg-rose-500/10 border-rose-500/30 text-rose-300'
        }`}>
          <div className="max-w-6xl mx-auto w-full flex items-center justify-between gap-3">
            <div className="flex items-center gap-2.5">
              {bannerNotice.type === 'success' ? (
                <CheckCircle2 className="w-4 h-4 flex-shrink-0 text-emerald-400" />
              ) : (
                <AlertCircle className="w-4 h-4 flex-shrink-0 text-rose-400" />
              )}
              <span>{bannerNotice.message}</span>
            </div>
            <button
              onClick={() => setBannerNotice(null)}
              className="p-1 hover:bg-white/10 rounded transition-colors cursor-pointer"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* Main Content Area */}
      <main className="flex-1 max-w-6xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 sm:py-10 z-10 space-y-8">
        {/* Hero Section */}
        <div>
          <h2 className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight">
            Personal AI Assistant Dashboard
          </h2>
          <p className="text-sm sm:text-base text-slate-400 mt-2 max-w-2xl leading-relaxed">
            Connect your personal Google Account via OAuth 2.0 to grant the AI assistant read-only access to analyze incoming emails and triage important messages.
          </p>
        </div>

        {/* Milestone 2: Google OAuth Connection Card */}
        <section aria-labelledby="google-connection-heading">
          <GoogleConnectionCard
            authStatus={authStatus}
            loading={authLoading}
            onRefresh={checkAuthStatus}
            error={authError}
          />
        </section>

        {/* Backend Operational Health Status Card */}
        <section aria-labelledby="health-heading">
          <HealthStatusCard
            health={health}
            loading={healthLoading}
            onRefresh={checkBackendHealth}
          />
        </section>

        {/* Security & Multi-User Architecture Notice */}
        <section className="glass-panel rounded-2xl p-6 border border-slate-800/80 bg-slate-900/40">
          <div className="flex items-start gap-4">
            <div className="p-2.5 rounded-xl bg-amber-500/10 text-amber-400 border border-amber-500/20 flex-shrink-0 mt-0.5">
              <ShieldAlert className="w-5 h-5" />
            </div>
            <div className="space-y-1">
              <h3 className="text-sm font-semibold text-slate-200">
                Security & Multi-Tenant Isolation Active
              </h3>
              <p className="text-xs sm:text-sm text-slate-400 leading-relaxed">
                Tokens are encrypted symmetrically using Fernet (AES-128-CBC) at rest and never exposed to the frontend.
                Every request requires a secure, signed server-side session cookie.
                Users are strictly isolated by <code className="text-xs bg-slate-800 px-1 py-0.5 rounded text-blue-400">user_id</code>.
              </p>
            </div>
          </div>
        </section>

        {/* Architecture Services Roadmap */}
        <section aria-labelledby="architecture-blueprint">
          <SystemOverview />
        </section>
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-800/80 py-6 text-center text-xs text-slate-500 z-10">
        Personal AI Assistant &copy; 2026 &bull; Multi-User Google OAuth Foundation
      </footer>
    </div>
  );
};

export default App;
