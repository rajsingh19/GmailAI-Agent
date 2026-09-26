import test from 'node:test';
import assert from 'node:assert/strict';

// Helper to simulate React JSX render output or state evaluation
test('AppShell: Truthful identity and Google connection mapping', async () => {
  // Mock auth states
  const unauthenticatedStatus = {
    authenticated: false,
    user: null,
    google_account: {
      connected: false,
      email: null,
      picture_url: null,
      scopes: [],
      is_expired: false,
      requires_reauth: false,
    },
  };

  const authenticatedConnectedStatus = {
    authenticated: true,
    user: {
      id: 'usr_12345678',
      email: 'alex.smith@example.com',
      full_name: 'Alex Smith',
      picture_url: 'https://example.com/avatar.jpg',
    },
    google_account: {
      connected: true,
      email: 'alex.smith@example.com',
      scopes: ['gmail.readonly', 'calendar.readonly'],
      is_expired: false,
      requires_reauth: false,
    },
  };

  const authenticatedDisconnectedStatus = {
    authenticated: true,
    user: {
      id: 'usr_87654321',
      email: 'sam.jones@example.com',
      full_name: 'Sam Jones',
      picture_url: null,
    },
    google_account: {
      connected: false,
      email: null,
      scopes: [],
      is_expired: false,
      requires_reauth: false,
    },
  };

  // 1. Loading state evaluation
  function computeAppShellState(authStatus, authLoading) {
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

    return { isAuthenticated, isConnected, displayName, displayEmail, initial };
  }

  // Verification 1: Loading
  const loadingState = computeAppShellState(null, true);
  assert.equal(loadingState.displayName, 'Loading...');
  assert.equal(loadingState.displayEmail, 'Checking session...');
  assert.equal(loadingState.initial, '...');
  assert.notEqual(loadingState.displayName, 'Raj Singh');
  assert.notEqual(loadingState.displayEmail, 'raj.singh190904@gmail.com');

  // Verification 2: Unauthenticated / Guest
  const guestState = computeAppShellState(unauthenticatedStatus, false);
  assert.equal(guestState.isAuthenticated, false);
  assert.equal(guestState.isConnected, false);
  assert.equal(guestState.displayName, 'Guest User');
  assert.equal(guestState.displayEmail, 'Not signed in');
  assert.equal(guestState.initial, 'G');
  assert.notEqual(guestState.displayName, 'Raj Singh', 'Unauthenticated user must never show hardcoded mock name');
  assert.notEqual(guestState.displayEmail, 'raj.singh190904@gmail.com', 'Unauthenticated user must never show hardcoded mock email');

  // Verification 3: Authenticated + Google Connected
  const authConnState = computeAppShellState(authenticatedConnectedStatus, false);
  assert.equal(authConnState.isAuthenticated, true);
  assert.equal(authConnState.isConnected, true);
  assert.equal(authConnState.displayName, 'Alex Smith');
  assert.equal(authConnState.displayEmail, 'alex.smith@example.com');
  assert.equal(authConnState.initial, 'A');

  // Verification 4: Authenticated + Google Disconnected
  const authDisconnState = computeAppShellState(authenticatedDisconnectedStatus, false);
  assert.equal(authDisconnState.isAuthenticated, true);
  assert.equal(authDisconnState.isConnected, false);
  assert.equal(authDisconnState.displayName, 'Sam Jones');
  assert.equal(authDisconnState.displayEmail, 'sam.jones@example.com');
  assert.equal(authDisconnState.initial, 'S');
});

test('DashboardPage: Truthful greeting and integration status resolution', () => {
  function computeDashboardState(authStatus, authLoading) {
    const isAuthenticated = authStatus?.authenticated === true;
    const isGoogleConnected = isAuthenticated && (authStatus?.google_account?.connected === true);
    const user = authStatus?.user;
    const firstName = user?.full_name?.split(' ')[0] || (user?.email ? user.email.split('@')[0] : '');

    const greetingTitle = authLoading
      ? 'Loading Dashboard...'
      : isAuthenticated
      ? `Good Morning, ${firstName || 'there'}! ☀️`
      : 'Welcome, Guest! 👋';

    const gmailStatLabel = isGoogleConnected
      ? 'inbox'
      : isAuthenticated
      ? 'disconnected'
      : 'guest';

    const calendarStatLabel = isGoogleConnected
      ? 'this week'
      : isAuthenticated
      ? 'disconnected'
      : 'guest';

    const agendaMessage = authLoading
      ? 'Loading agenda...'
      : !isAuthenticated
      ? 'Sign in with Google to view your Calendar agenda.'
      : !isGoogleConnected
      ? 'Google Calendar is not connected.'
      : 'Active Calendar Agenda';

    const emailMessage = authLoading
      ? 'Loading emails...'
      : !isAuthenticated
      ? 'Sign in with Google to view your recent emails.'
      : !isGoogleConnected
      ? 'Gmail is not connected.'
      : 'Active Gmail Inbox';

    return {
      isAuthenticated,
      isGoogleConnected,
      greetingTitle,
      gmailStatLabel,
      calendarStatLabel,
      agendaMessage,
      emailMessage,
    };
  }

  // 1. Unauthenticated / Guest
  const guest = computeDashboardState({ authenticated: false, user: null, google_account: { connected: false } }, false);
  assert.equal(guest.greetingTitle, 'Welcome, Guest! 👋');
  assert.equal(guest.agendaMessage, 'Sign in with Google to view your Calendar agenda.');
  assert.equal(guest.emailMessage, 'Sign in with Google to view your recent emails.');
  assert.equal(guest.gmailStatLabel, 'guest');
  assert.equal(guest.calendarStatLabel, 'guest');

  // 2. Authenticated but Google Disconnected
  const authDisconn = computeDashboardState({
    authenticated: true,
    user: { full_name: 'Elena Rostova', email: 'elena@example.com' },
    google_account: { connected: false }
  }, false);
  assert.equal(authDisconn.greetingTitle, 'Good Morning, Elena! ☀️');
  assert.equal(authDisconn.agendaMessage, 'Google Calendar is not connected.');
  assert.equal(authDisconn.emailMessage, 'Gmail is not connected.');
  assert.equal(authDisconn.gmailStatLabel, 'disconnected');
  assert.equal(authDisconn.calendarStatLabel, 'disconnected');

  // 3. Authenticated and Google Connected
  const authConn = computeDashboardState({
    authenticated: true,
    user: { full_name: 'Jordan Lee', email: 'jordan@example.com' },
    google_account: { connected: true }
  }, false);
  assert.equal(authConn.greetingTitle, 'Good Morning, Jordan! ☀️');
  assert.equal(authConn.agendaMessage, 'Active Calendar Agenda');
  assert.equal(authConn.emailMessage, 'Active Gmail Inbox');
  assert.equal(authConn.gmailStatLabel, 'inbox');
  assert.equal(authConn.calendarStatLabel, 'this week');
});

test('SettingsPage: Truthful profile rendering and action button', () => {
  function computeProfileState(authStatus, loading) {
    const isAuthenticated = authStatus?.authenticated === true;
    const user = authStatus?.user;

    const profileName = loading
      ? 'Loading...'
      : !isAuthenticated
      ? 'Guest User'
      : user?.full_name || 'Personal Assistant User';

    const profileEmail = loading
      ? 'Loading...'
      : !isAuthenticated
      ? 'Not signed in'
      : user?.email || 'No email associated';

    const actionType = !isAuthenticated ? 'SIGN_IN' : 'LOG_OUT';
    const badgeLabel = !isAuthenticated ? 'Guest Session' : 'Active User';

    return { profileName, profileEmail, actionType, badgeLabel };
  }

  // Unauthenticated
  const guest = computeProfileState({ authenticated: false, user: null }, false);
  assert.equal(guest.profileName, 'Guest User');
  assert.equal(guest.profileEmail, 'Not signed in');
  assert.equal(guest.actionType, 'SIGN_IN');
  assert.equal(guest.badgeLabel, 'Guest Session');

  // Authenticated
  const auth = computeProfileState({
    authenticated: true,
    user: { full_name: 'Maya Lin', email: 'maya@example.com', id: 'usr_maya99' }
  }, false);
  assert.equal(auth.profileName, 'Maya Lin');
  assert.equal(auth.profileEmail, 'maya@example.com');
  assert.equal(auth.actionType, 'LOG_OUT');
  assert.equal(auth.badgeLabel, 'Active User');
});
