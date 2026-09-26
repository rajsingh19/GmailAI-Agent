import React, { useState } from 'react';
import {
  LayoutDashboard,
  MessageCircle,
  CheckSquare,
  Calendar,
  Mail,
  Bell,
  Settings,
  Search,
  Bot,
  Menu,
  X,
  ShieldCheck,
  Briefcase,
  CheckCircle2,
  LogIn,
  Loader2,
} from 'lucide-react';
import { AuthStatusResponse, getGoogleOAuthUrl } from '../../services/api';

export type NavTab = 'dashboard' | 'chat' | 'jobs' | 'tasks' | 'calendar' | 'gmail' | 'reminders' | 'settings';

interface AppShellProps {
  activeTab: NavTab;
  onTabChange: (tab: NavTab) => void;
  authStatus: AuthStatusResponse | null;
  authLoading?: boolean;
  unreadCount?: number;
  children: React.ReactNode;
  onSearch?: (query: string) => void;
}

export const AppShell: React.FC<AppShellProps> = ({
  activeTab,
  onTabChange,
  authStatus,
  authLoading = false,
  unreadCount = 0,
  children,
  onSearch,
}) => {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');

  const isAuthenticated = authStatus?.authenticated === true;
  const user = authStatus?.user;
  const googleAccount = authStatus?.google_account;
  const isConnected = isAuthenticated && (googleAccount?.connected === true);

  const displayName = authLoading
    ? 'Loading...'
    : isAuthenticated
    ? (user?.full_name || user?.email || 'User')
    : 'Guest User';

  const displayEmail = authLoading
    ? 'Checking session...'
    : isAuthenticated
    ? (user?.email || '')
    : 'Not signed in';

  const initial = authLoading
    ? '...'
    : isAuthenticated
    ? (displayName.charAt(0).toUpperCase() || 'U')
    : 'G';

  const navItems = [
    { id: 'dashboard' as NavTab, label: 'Dashboard', icon: LayoutDashboard },
    { id: 'jobs' as NavTab, label: 'Job Agent', icon: Briefcase },
    { id: 'chat' as NavTab, label: 'Chat', icon: MessageCircle },
    { id: 'tasks' as NavTab, label: 'Tasks', icon: CheckSquare },
    { id: 'calendar' as NavTab, label: 'Calendar', icon: Calendar },
    { id: 'gmail' as NavTab, label: 'Gmail', icon: Mail },
    { id: 'reminders' as NavTab, label: 'Reminders', icon: Bell, badge: unreadCount > 0 ? unreadCount : undefined },
    { id: 'settings' as NavTab, label: 'Settings', icon: Settings },
  ];

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (onSearch && searchQuery.trim()) {
      onSearch(searchQuery.trim());
    }
  };

  const renderNavContent = () => (
    <div className="flex flex-col h-full bg-white border-r border-[#E5E7EB]">
      {/* Brand Header */}
      <div className="p-4 sm:p-5 flex items-center gap-3 border-b border-[#E5E7EB]">
        <div className="w-8 h-8 rounded-lg bg-[#4F46E5] flex items-center justify-center text-white flex-shrink-0">
          <Bot className="w-4 h-4" />
        </div>
        <div className="min-w-0">
          <h1 className="text-sm font-semibold text-[#111827] tracking-tight leading-tight truncate">
            Personal AI Assistant
          </h1>
          <p className="text-[11px] text-[#64748B] truncate">
            Your smart productivity partner
          </p>
        </div>
      </div>

      {/* Navigation Links */}
      <nav className="flex-1 px-3 py-3 space-y-0.5 overflow-y-auto">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = activeTab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => {
                onTabChange(item.id);
                setMobileMenuOpen(false);
              }}
              className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-xs sm:text-sm font-medium transition-colors cursor-pointer ${
                isActive
                  ? 'bg-[#EEF2FF] text-[#4F46E5] font-semibold'
                  : 'text-[#475569] hover:text-[#111827] hover:bg-[#F1F5F9]'
              }`}
            >
              <div className="flex items-center gap-2.5">
                <Icon className={`w-4 h-4 ${isActive ? 'text-[#4F46E5]' : 'text-[#64748B]'}`} />
                <span>{item.label}</span>
              </div>
              {item.badge !== undefined && (
                <span className="px-1.5 py-0.2 text-[10px] font-bold rounded-full bg-amber-100 text-amber-700">
                  {item.badge}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      {/* User Profile / Auth Footer */}
      <div className="p-3 border-t border-[#E5E7EB]">
        {authLoading ? (
          <div className="flex items-center gap-2.5 p-1.5 text-slate-400">
            <Loader2 className="w-4 h-4 animate-spin" />
            <span className="text-xs">Loading profile...</span>
          </div>
        ) : !isAuthenticated ? (
          <div className="space-y-2">
            <div className="flex items-center gap-2.5 p-1 rounded-lg">
              <div className="w-7 h-7 rounded-full bg-slate-100 text-slate-500 border border-slate-200 flex items-center justify-center text-xs font-semibold flex-shrink-0">
                G
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-xs font-semibold text-[#111827] truncate">Guest User</div>
                <div className="text-[11px] text-[#64748B] truncate">Not signed in</div>
              </div>
            </div>
            <a
              href={getGoogleOAuthUrl()}
              className="w-full inline-flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#4F46E5] hover:bg-[#4338CA] text-white text-xs font-medium transition-colors shadow-2xs"
            >
              <LogIn className="w-3.5 h-3.5" />
              <span>Sign in with Google</span>
            </a>
          </div>
        ) : (
          <button
            onClick={() => {
              onTabChange('settings');
              setMobileMenuOpen(false);
            }}
            className="w-full flex items-center gap-2.5 p-1.5 rounded-lg hover:bg-[#F1F5F9] transition-colors text-left cursor-pointer"
          >
            {user?.picture_url ? (
              <img
                src={user.picture_url}
                alt={displayName}
                className="w-8 h-8 rounded-full object-cover border border-[#E5E7EB]"
              />
            ) : (
              <div className="w-8 h-8 rounded-full bg-[#4F46E5] text-white flex items-center justify-center text-xs font-semibold flex-shrink-0">
                {initial}
              </div>
            )}
            <div className="min-w-0 flex-1">
              <div className="text-xs font-semibold text-[#111827] truncate">
                {displayName}
              </div>
              <div className="text-[11px] text-[#64748B] truncate">
                {displayEmail}
              </div>
            </div>
          </button>
        )}
      </div>
    </div>
  );

  return (
    <div className="min-h-screen bg-[#F8FAFC] flex flex-col md:flex-row text-[#111827]">
      {/* Desktop Sidebar (Fixed left width 230px) */}
      <aside className="hidden md:block w-56 lg:w-60 flex-shrink-0 sticky top-0 h-screen z-30">
        {renderNavContent()}
      </aside>

      {/* Mobile Drawer Backdrop */}
      {mobileMenuOpen && (
        <div
          className="fixed inset-0 bg-slate-900/30 z-40 md:hidden backdrop-blur-xs"
          onClick={() => setMobileMenuOpen(false)}
        />
      )}

      {/* Mobile Drawer Menu */}
      <div
        className={`fixed inset-y-0 left-0 w-60 bg-white z-50 transform transition-transform duration-200 ease-in-out md:hidden shadow-xl ${
          mobileMenuOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="absolute right-2.5 top-3.5">
          <button
            onClick={() => setMobileMenuOpen(false)}
            className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100"
            aria-label="Close menu"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        {renderNavContent()}
      </div>

      {/* Main Content Area with Top Bar */}
      <div className="flex-1 flex flex-col min-w-0 min-h-screen">
        {/* Top Bar */}
        <header className="h-14 bg-white border-b border-[#E5E7EB] px-4 sm:px-6 flex items-center justify-between gap-4 sticky top-0 z-20">
          {/* Mobile hamburger button */}
          <button
            onClick={() => setMobileMenuOpen(true)}
            className="md:hidden p-1.5 rounded-lg text-slate-600 hover:bg-slate-100 cursor-pointer"
            aria-label="Open menu"
          >
            <Menu className="w-5 h-5" />
          </button>

          {/* Search bar (280px-320px wide) */}
          <form onSubmit={handleSearchSubmit} className="hidden sm:block w-72 lg:w-80">
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search anything..."
                className="w-full pl-8 pr-3 py-1.5 bg-slate-50 border border-[#E5E7EB] rounded-lg text-xs text-[#111827] placeholder:text-slate-400 focus:outline-none focus:bg-white focus:border-[#4F46E5] transition-colors"
              />
            </div>
          </form>

          {/* Right Topbar Controls */}
          <div className="flex items-center gap-2.5 ml-auto">
            {/* Google Connection / Auth Pill */}
            {authLoading ? (
              <div className="hidden sm:flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-slate-50 text-slate-500 text-xs font-medium border border-slate-200">
                <Loader2 className="w-3 h-3 animate-spin text-slate-400" />
                <span>Checking...</span>
              </div>
            ) : !isAuthenticated ? (
              <a
                href={getGoogleOAuthUrl()}
                className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1 rounded-lg bg-[#4F46E5] hover:bg-[#4338CA] text-white text-xs font-medium transition-colors shadow-2xs"
              >
                <LogIn className="w-3.5 h-3.5" />
                <span>Sign in with Google</span>
              </a>
            ) : isConnected ? (
              <div className="hidden sm:flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-emerald-50 text-emerald-700 text-xs font-medium border border-emerald-200">
                <CheckCircle2 className="w-3 h-3 text-emerald-600" />
                <span>Google Connected</span>
              </div>
            ) : (
              <button
                onClick={() => onTabChange('settings')}
                className="hidden sm:flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-amber-50 text-amber-700 text-xs font-medium border border-amber-200 hover:bg-amber-100 transition-colors"
              >
                <ShieldCheck className="w-3 h-3 text-amber-600" />
                <span>Connect Google</span>
              </button>
            )}

            {/* Notification Bell */}
            <button
              onClick={() => onTabChange('reminders')}
              className="p-1.5 rounded-lg text-slate-500 hover:text-slate-800 hover:bg-slate-100 transition-colors relative cursor-pointer"
              title="Notifications & Alerts"
              aria-label="Notifications"
            >
              <Bell className="w-4 h-4" />
              {unreadCount > 0 && (
                <span className="w-2 h-2 rounded-full bg-amber-500 absolute top-1 right-1 ring-2 ring-white"></span>
              )}
            </button>

            {/* Avatar */}
            <button
              onClick={() => onTabChange('settings')}
              className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold cursor-pointer overflow-hidden border ${
                isAuthenticated
                  ? 'bg-[#4F46E5] text-white border-[#E5E7EB]'
                  : 'bg-slate-100 text-slate-600 border-slate-300'
              }`}
              title={isAuthenticated ? "Settings & Profile" : "Guest User (Click to Sign In)"}
              aria-label="User Profile"
            >
              {isAuthenticated && user?.picture_url ? (
                <img src={user.picture_url} alt={displayName} className="w-full h-full object-cover" />
              ) : (
                initial
              )}
            </button>
          </div>
        </header>

        {/* Page Body: max-w-[1400px] compact SaaS layout */}
        <main className="flex-1 p-5 sm:p-6 lg:p-7 max-w-[1400px] w-full mx-auto">
          {children}
        </main>
      </div>
    </div>
  );
};
