import React, { useEffect, useState, useCallback } from 'react';
import { CheckCircle2, AlertCircle, X } from 'lucide-react';
import { fetchAuthStatus, AuthStatusResponse, fetchNotifications } from './services/api';
import { AppShell, NavTab } from './components/layout/AppShell';
import { DashboardPage } from './components/pages/DashboardPage';
import { ChatPage } from './components/pages/ChatPage';
import { TasksPage } from './components/pages/TasksPage';
import { GmailPage } from './components/pages/GmailPage';
import { CalendarPage } from './components/pages/CalendarPage';
import { RemindersPage } from './components/pages/RemindersPage';
import { SettingsPage } from './components/pages/SettingsPage';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<NavTab>('dashboard');
  const [authStatus, setAuthStatus] = useState<AuthStatusResponse | null>(null);
  const [authLoading, setAuthLoading] = useState<boolean>(true);
  const [unreadCount, setUnreadCount] = useState<number>(0);

  const [bannerNotice, setBannerNotice] = useState<{
    type: 'success' | 'error' | 'info';
    message: string;
  } | null>(null);

  const checkAuthStatus = useCallback(async () => {
    setAuthLoading(true);
    try {
      const [status, notifRes] = await Promise.all([
        fetchAuthStatus(),
        fetchNotifications().catch(() => ({ items: [], unread_count: 0 })),
      ]);
      setAuthStatus(status);
      setUnreadCount(notifRes.unread_count || 0);
    } catch (err: any) {
      console.warn('Auth status check error:', err);
    } finally {
      setAuthLoading(false);
    }
  }, []);

  useEffect(() => {
    // 1. Initial auth status check
    checkAuthStatus();

    // 2. Check for redirect query parameters from OAuth callback
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.has('auth') && urlParams.get('auth') === 'success') {
      setBannerNotice({
        type: 'success',
        message: 'Google Account successfully connected! Gmail & Calendar access is enabled.',
      });
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

    const handleDataUpdate = () => {
      checkAuthStatus();
    };
    window.addEventListener('assistant-data-updated', handleDataUpdate);
    return () => window.removeEventListener('assistant-data-updated', handleDataUpdate);
  }, [checkAuthStatus]);

  const handleNotify = (message: string, type: 'success' | 'error' | 'info') => {
    setBannerNotice({ message, type });
  };

  const handleGlobalSearch = (query: string) => {
    const q = query.toLowerCase();
    if (q.startsWith('from:') || q.startsWith('is:') || q.startsWith('subject:') || q.startsWith('label:')) {
      setActiveTab('gmail');
    } else if (q.startsWith('task:') || q.includes('todo') || q.includes('task')) {
      setActiveTab('tasks');
    } else {
      setActiveTab('chat');
    }
  };

  return (
    <AppShell
      activeTab={activeTab}
      onTabChange={setActiveTab}
      authStatus={authStatus}
      unreadCount={unreadCount}
      onSearch={handleGlobalSearch}
    >
      {/* Global Notification Banner */}
      {bannerNotice && (
        <div
          className={`mb-6 p-4 rounded-xl text-sm flex items-center justify-between border transition-all ${
            bannerNotice.type === 'success'
              ? 'bg-emerald-50 border-emerald-200 text-emerald-800'
              : bannerNotice.type === 'error'
              ? 'bg-red-50 border-red-200 text-red-800'
              : 'bg-indigo-50 border-indigo-200 text-indigo-800'
          }`}
        >
          <div className="flex items-center gap-3">
            {bannerNotice.type === 'success' ? (
              <CheckCircle2 className="w-5 h-5 text-emerald-600 flex-shrink-0" />
            ) : bannerNotice.type === 'error' ? (
              <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0" />
            ) : (
              <CheckCircle2 className="w-5 h-5 text-indigo-600 flex-shrink-0" />
            )}
            <span className="font-medium">{bannerNotice.message}</span>
          </div>
          <button
            onClick={() => setBannerNotice(null)}
            className="p-1 hover:bg-black/5 rounded-lg text-gray-500 hover:text-gray-700 transition-colors"
            aria-label="Dismiss banner"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Page Routing */}
      {activeTab === 'dashboard' && (
        <DashboardPage
          authStatus={authStatus}
          onNavigate={setActiveTab}
        />
      )}

      {activeTab === 'chat' && (
        <ChatPage
          isAuthenticated={authStatus?.authenticated ?? false}
          onNotify={handleNotify}
        />
      )}

      {activeTab === 'tasks' && (
        <TasksPage
          isAuthenticated={authStatus?.authenticated ?? false}
        />
      )}

      {activeTab === 'gmail' && (
        <GmailPage
          authStatus={authStatus}
        />
      )}

      {activeTab === 'calendar' && (
        <CalendarPage
          authStatus={authStatus}
        />
      )}

      {activeTab === 'reminders' && (
        <RemindersPage
          isAuthenticated={authStatus?.authenticated ?? false}
        />
      )}

      {activeTab === 'settings' && (
        <SettingsPage
          authStatus={authStatus}
          loading={authLoading}
          onRefresh={checkAuthStatus}
          onNotify={handleNotify}
        />
      )}
    </AppShell>
  );
};

export default App;
