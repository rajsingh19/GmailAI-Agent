import React, { useState } from 'react';
import {
  User,
  Sparkles,
  Link2,
  Bell,
  Palette,
  Shield,
  AlertTriangle,
  LogOut,
  Mail,
  Calendar,
  Lock,
  Database,
  Check,
} from 'lucide-react';
import { AuthStatusResponse, disconnectGoogleAccount, logout, getGoogleOAuthUrl } from '../../services/api';
import { PersonalizationSettings } from '../PersonalizationSettings';
import { MemoryManager } from '../MemoryManager';
import { PersonalKnowledgeCard } from '../PersonalKnowledgeCard';
import { NotificationSettings } from '../NotificationSettings';

interface SettingsPageProps {
  authStatus: AuthStatusResponse | null;
  loading?: boolean;
  onRefresh: () => void;
  onNotify?: (message: string, type: 'success' | 'error' | 'info') => void;
}

type SettingsTab =
  | 'profile'
  | 'ai'
  | 'accounts'
  | 'notifications'
  | 'appearance'
  | 'privacy';

export const SettingsPage: React.FC<SettingsPageProps> = ({
  authStatus,
  onRefresh,
  onNotify,
}) => {
  const [activeTab, setActiveTab] = useState<SettingsTab>('profile');
  const [themePreference, setThemePreference] = useState<'light' | 'dark' | 'system'>('light');
  const [actionLoading, setActionLoading] = useState<boolean>(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const isConnected = authStatus?.google_account?.connected ?? false;
  const requiresReauth = authStatus?.google_account?.requires_reauth ?? false;
  const googleEmail = authStatus?.google_account?.email;
  const user = authStatus?.user;

  const handleConnect = () => {
    window.location.href = getGoogleOAuthUrl();
  };

  const handleDisconnect = async () => {
    if (!window.confirm('Are you sure you want to disconnect your Google Account? This will revoke backend access to Gmail and Google Calendar.')) {
      return;
    }
    setActionLoading(true);
    setActionError(null);
    try {
      await disconnectGoogleAccount();
      onRefresh();
      onNotify?.('Google account disconnected successfully', 'info');
    } catch (err: any) {
      setActionError(err.message || 'Failed to disconnect account');
      onNotify?.(err.message || 'Failed to disconnect account', 'error');
    } finally {
      setActionLoading(false);
    }
  };

  const handleLogout = async () => {
    setActionLoading(true);
    try {
      await logout();
      onRefresh();
      onNotify?.('Logged out successfully', 'info');
    } catch (err: any) {
      setActionError(err.message || 'Failed to log out');
    } finally {
      setActionLoading(false);
    }
  };

  const navItems = [
    { id: 'profile', label: 'Profile', icon: User, desc: 'Personal details & session' },
    { id: 'ai', label: 'AI & Personalization', icon: Sparkles, desc: 'Memory, RAG & preferences' },
    { id: 'accounts', label: 'Connected Accounts', icon: Link2, desc: 'Google, Gmail & Calendar' },
    { id: 'notifications', label: 'Notifications', icon: Bell, desc: 'Web Push & PWA alerts' },
    { id: 'appearance', label: 'Appearance', icon: Palette, desc: 'Theme & workspace styling' },
    { id: 'privacy', label: 'Privacy & Security', icon: Shield, desc: 'Permissions & safeguards' },
  ] as const;

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900 tracking-tight">Settings</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          Manage your personal workspace, AI preferences, and connected integrations
        </p>
      </div>

      {/* Main Container with Left Sub-nav */}
      <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden flex flex-col md:flex-row min-h-[600px]">
        {/* Left Sub-Navigation Sidebar */}
        <aside className="w-full md:w-64 border-b md:border-b-0 md:border-r border-gray-200 p-3 bg-gray-50/50 flex-shrink-0">
          <nav className="space-y-1">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = activeTab === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => setActiveTab(item.id)}
                  className={`w-full flex items-center gap-3 px-3.5 py-2.5 rounded-lg text-sm font-medium text-left transition-all ${
                    isActive
                      ? 'bg-indigo-50 text-indigo-600 font-semibold'
                      : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100/70'
                  }`}
                >
                  <Icon className={`w-4 h-4 flex-shrink-0 ${isActive ? 'text-indigo-600' : 'text-gray-400'}`} />
                  <span className="truncate">{item.label}</span>
                </button>
              );
            })}
          </nav>
        </aside>

        {/* Right Content Area */}
        <main className="flex-1 p-6 md:p-8 overflow-y-auto">
          {/* PROFILE SECTION */}
          {activeTab === 'profile' && (
            <div className="space-y-6 max-w-2xl">
              <div>
                <h2 className="text-lg font-semibold text-gray-900">Profile</h2>
                <p className="text-xs text-gray-500 mt-0.5">
                  Manage your personal account profile and active session
                </p>
              </div>

              {/* Profile Card */}
              <div className="p-6 border border-gray-200 rounded-xl bg-gray-50/30 flex items-center gap-5">
                <div className="w-16 h-16 rounded-full bg-indigo-600 text-white flex items-center justify-center font-bold text-xl ring-4 ring-indigo-50">
                  {user?.full_name ? user.full_name.charAt(0).toUpperCase() : 'R'}
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="text-base font-semibold text-gray-900 truncate">
                    {user?.full_name || 'Raj Singh'}
                  </h3>
                  <p className="text-xs text-gray-500 truncate mt-0.5">
                    {user?.email || 'raj@example.com'}
                  </p>
                  <div className="flex items-center gap-2 mt-2">
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
                      Active User
                    </span>
                    <span className="text-[11px] text-gray-400">
                      ID: {user?.id ? user.id.slice(0, 8) + '...' : 'authenticated'}
                    </span>
                  </div>
                </div>
              </div>

              {/* Details form */}
              <div className="space-y-4 pt-2">
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Full Name</label>
                  <input
                    type="text"
                    disabled
                    value={user?.full_name || 'Raj Singh'}
                    className="w-full px-3.5 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm text-gray-800"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Email Address</label>
                  <input
                    type="email"
                    disabled
                    value={user?.email || 'raj@example.com'}
                    className="w-full px-3.5 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm text-gray-800"
                  />
                </div>
              </div>

              {/* Session / Logout */}
              <div className="pt-6 border-t border-gray-200 flex items-center justify-between">
                <div>
                  <h4 className="text-xs font-medium text-gray-900">Sign Out</h4>
                  <p className="text-xs text-gray-500 mt-0.5">
                    End your current session on this device.
                  </p>
                </div>
                <button
                  onClick={handleLogout}
                  disabled={actionLoading}
                  className="inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-medium text-red-600 bg-red-50 hover:bg-red-100 border border-red-200 rounded-lg transition-colors disabled:opacity-50"
                >
                  <LogOut className="w-3.5 h-3.5" />
                  <span>Log Out</span>
                </button>
              </div>
            </div>
          )}

          {/* AI & PERSONALIZATION SECTION */}
          {activeTab === 'ai' && (
            <div className="space-y-8">
              <div>
                <h2 className="text-lg font-semibold text-gray-900">AI & Personalization</h2>
                <p className="text-xs text-gray-500 mt-0.5">
                  Configure Gemini personality, long-term memory, and personal knowledge retrieval
                </p>
              </div>

              {/* Personalization Config Card */}
              <div className="border border-gray-200 rounded-xl p-5 bg-white">
                <PersonalizationSettings onClose={() => {}} />
              </div>

              {/* Long-Term Memory Manager */}
              <div className="border border-gray-200 rounded-xl p-5 bg-white">
                <MemoryManager isAuthenticated={authStatus?.authenticated ?? false} onNotify={onNotify} />
              </div>

              {/* Personal Knowledge RAG */}
              <div className="border border-gray-200 rounded-xl p-5 bg-white">
                <PersonalKnowledgeCard onNotify={onNotify} />
              </div>
            </div>
          )}

          {/* CONNECTED ACCOUNTS SECTION */}
          {activeTab === 'accounts' && (
            <div className="space-y-6 max-w-2xl">
              <div>
                <h2 className="text-lg font-semibold text-gray-900">Connected Accounts</h2>
                <p className="text-xs text-gray-500 mt-0.5">
                  Integrate your Google account for strictly read-only Gmail & Calendar synchronization
                </p>
              </div>

              {actionError && (
                <div className="p-4 bg-red-50 border border-red-200 rounded-xl flex items-start gap-3 text-red-700 text-xs">
                  <AlertTriangle className="w-4 h-4 mt-0.5 flex-shrink-0 text-red-500" />
                  <div>
                    <span className="font-semibold">Action Failed:</span> {actionError}
                  </div>
                </div>
              )}

              {/* Google Integration Card */}
              <div className="p-6 border border-gray-200 rounded-xl bg-white space-y-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex items-center gap-3.5">
                    <div className="w-10 h-10 rounded-xl bg-red-50 text-red-600 flex items-center justify-center font-bold text-base border border-red-100">
                      G
                    </div>
                    <div>
                      <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
                        Google Workspace
                        {isConnected ? (
                          requiresReauth ? (
                            <span className="px-2 py-0.5 text-[10px] font-medium bg-amber-50 text-amber-700 border border-amber-200 rounded-full">
                              Reauth Required
                            </span>
                          ) : (
                            <span className="px-2 py-0.5 text-[10px] font-medium bg-emerald-50 text-emerald-700 border border-emerald-200 rounded-full flex items-center gap-1">
                              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
                              Connected
                            </span>
                          )
                        ) : (
                          <span className="px-2 py-0.5 text-[10px] font-medium bg-gray-100 text-gray-600 rounded-full">
                            Not Connected
                          </span>
                        )}
                      </h3>
                      <p className="text-xs text-gray-500 mt-0.5">
                        {googleEmail ? googleEmail : 'Connect to sync Gmail and Google Calendar'}
                      </p>
                    </div>
                  </div>

                  <div>
                    {isConnected ? (
                      <button
                        onClick={handleDisconnect}
                        disabled={actionLoading}
                        className="px-3 py-1.5 text-xs font-medium text-red-600 bg-red-50 hover:bg-red-100 border border-red-200 rounded-lg transition-colors disabled:opacity-50"
                      >
                        Disconnect
                      </button>
                    ) : (
                      <button
                        onClick={handleConnect}
                        className="px-3.5 py-1.5 text-xs font-medium text-white bg-indigo-600 hover:bg-indigo-700 rounded-lg shadow-sm transition-colors"
                      >
                        Connect Google
                      </button>
                    )}
                  </div>
                </div>

                {/* Scopes Description */}
                <div className="pt-4 border-t border-gray-100 grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div className="p-3 bg-gray-50 rounded-lg flex items-start gap-2.5">
                    <Mail className="w-4 h-4 text-blue-600 mt-0.5 flex-shrink-0" />
                    <div>
                      <div className="text-xs font-medium text-gray-900">Gmail Access</div>
                      <div className="text-[11px] text-gray-500 mt-0.5">
                        Strictly read-only (`gmail.readonly`). Cannot send, delete or modify emails.
                      </div>
                    </div>
                  </div>

                  <div className="p-3 bg-gray-50 rounded-lg flex items-start gap-2.5">
                    <Calendar className="w-4 h-4 text-emerald-600 mt-0.5 flex-shrink-0" />
                    <div>
                      <div className="text-xs font-medium text-gray-900">Google Calendar</div>
                      <div className="text-[11px] text-gray-500 mt-0.5">
                        Strictly read-only (`calendar.readonly`). Syncs events and schedule agenda.
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* NOTIFICATIONS SECTION */}
          {activeTab === 'notifications' && (
            <div className="space-y-6 max-w-2xl">
              <div>
                <h2 className="text-lg font-semibold text-gray-900">Notifications & Web Push</h2>
                <p className="text-xs text-gray-500 mt-0.5">
                  Configure browser push alerts, VAPID encryption, and device subscriptions
                </p>
              </div>

              <div className="border border-gray-200 rounded-xl p-5 bg-white">
                <NotificationSettings />
              </div>
            </div>
          )}

          {/* APPEARANCE SECTION */}
          {activeTab === 'appearance' && (
            <div className="space-y-6 max-w-2xl">
              <div>
                <h2 className="text-lg font-semibold text-gray-900">Appearance</h2>
                <p className="text-xs text-gray-500 mt-0.5">
                  Customize the visual theme and layout density of your workspace
                </p>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <button
                  type="button"
                  onClick={() => setThemePreference('light')}
                  className={`p-4 rounded-xl border text-left transition-all ${
                    themePreference === 'light'
                      ? 'border-indigo-600 ring-2 ring-indigo-500/20 bg-indigo-50/20'
                      : 'border-gray-200 hover:border-gray-300 bg-white'
                  }`}
                >
                  <div className="w-full h-16 bg-white border border-gray-200 rounded-lg shadow-xs mb-3 flex flex-col p-2 gap-1.5">
                    <div className="h-2 w-12 bg-indigo-600 rounded"></div>
                    <div className="h-1.5 w-full bg-gray-100 rounded"></div>
                    <div className="h-1.5 w-3/4 bg-gray-100 rounded"></div>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-gray-900">Light (Default)</span>
                    {themePreference === 'light' && <Check className="w-4 h-4 text-indigo-600" />}
                  </div>
                  <p className="text-[11px] text-gray-500 mt-0.5">Clean, minimal SaaS aesthetic</p>
                </button>

                <button
                  type="button"
                  onClick={() => setThemePreference('dark')}
                  className={`p-4 rounded-xl border text-left transition-all ${
                    themePreference === 'dark'
                      ? 'border-indigo-600 ring-2 ring-indigo-500/20 bg-indigo-50/20'
                      : 'border-gray-200 hover:border-gray-300 bg-white'
                  }`}
                >
                  <div className="w-full h-16 bg-gray-900 border border-gray-800 rounded-lg shadow-xs mb-3 flex flex-col p-2 gap-1.5">
                    <div className="h-2 w-12 bg-indigo-400 rounded"></div>
                    <div className="h-1.5 w-full bg-gray-800 rounded"></div>
                    <div className="h-1.5 w-3/4 bg-gray-800 rounded"></div>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-gray-900">Dark</span>
                    {themePreference === 'dark' && <Check className="w-4 h-4 text-indigo-600" />}
                  </div>
                  <p className="text-[11px] text-gray-500 mt-0.5">Low-light high contrast</p>
                </button>

                <button
                  type="button"
                  onClick={() => setThemePreference('system')}
                  className={`p-4 rounded-xl border text-left transition-all ${
                    themePreference === 'system'
                      ? 'border-indigo-600 ring-2 ring-indigo-500/20 bg-indigo-50/20'
                      : 'border-gray-200 hover:border-gray-300 bg-white'
                  }`}
                >
                  <div className="w-full h-16 bg-gradient-to-r from-white via-gray-100 to-gray-900 border border-gray-200 rounded-lg shadow-xs mb-3 flex items-center justify-center">
                    <Palette className="w-5 h-5 text-gray-600" />
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-gray-900">System</span>
                    {themePreference === 'system' && <Check className="w-4 h-4 text-indigo-600" />}
                  </div>
                  <p className="text-[11px] text-gray-500 mt-0.5">Sync with OS appearance</p>
                </button>
              </div>
            </div>
          )}

          {/* PRIVACY & SECURITY SECTION */}
          {activeTab === 'privacy' && (
            <div className="space-y-6 max-w-2xl">
              <div>
                <h2 className="text-lg font-semibold text-gray-900">Privacy & Security</h2>
                <p className="text-xs text-gray-500 mt-0.5">
                  Understand how your data is processed, encrypted, and isolated
                </p>
              </div>

              <div className="space-y-3">
                <div className="p-4 border border-gray-200 rounded-xl bg-white flex items-start gap-3.5">
                  <Lock className="w-5 h-5 text-indigo-600 mt-0.5 flex-shrink-0" />
                  <div>
                    <h3 className="text-sm font-semibold text-gray-900">Read-Only Integrations</h3>
                    <p className="text-xs text-gray-600 mt-0.5">
                      Gmail and Google Calendar connections strictly enforce read-only OAuth scopes. The AI assistant cannot draft, send, delete or modify emails or calendar events.
                    </p>
                  </div>
                </div>

                <div className="p-4 border border-gray-200 rounded-xl bg-white flex items-start gap-3.5">
                  <Shield className="w-5 h-5 text-indigo-600 mt-0.5 flex-shrink-0" />
                  <div>
                    <h3 className="text-sm font-semibold text-gray-900">HMAC-Signed Confirmation Challenges</h3>
                    <p className="text-xs text-gray-600 mt-0.5">
                      State-modifying operations (such as deleting tasks, bulk edits, or memory clearance) require explicit HMAC confirmation tokens and user approval before execution.
                    </p>
                  </div>
                </div>

                <div className="p-4 border border-gray-200 rounded-xl bg-white flex items-start gap-3.5">
                  <Database className="w-5 h-5 text-indigo-600 mt-0.5 flex-shrink-0" />
                  <div>
                    <h3 className="text-sm font-semibold text-gray-900">Encrypted Token Storage</h3>
                    <p className="text-xs text-gray-600 mt-0.5">
                      OAuth tokens and credentials are encrypted using AES-256 GCM in the local PostgreSQL database and never exposed in frontend API payloads.
                    </p>
                  </div>
                </div>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
};
