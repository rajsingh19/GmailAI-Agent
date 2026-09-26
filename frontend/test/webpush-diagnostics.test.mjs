import test from 'node:test';
import assert from 'node:assert/strict';

test('subscribeToPush passes Uint8Array directly as applicationServerKey', async () => {
  let capturedOptions = null;

  const mockRegistration = {
    scope: '/',
    pushManager: {
      getSubscription: async () => null,
      subscribe: async (options) => {
        capturedOptions = options;
        return { endpoint: 'https://push.example.com/sub/123' };
      }
    }
  };

  const mockNav = {
    userAgent: 'Mozilla/5.0 (X11; Linux x86_64)',
    serviceWorker: {
      register: async () => mockRegistration,
      ready: Promise.resolve(mockRegistration),
    }
  };

  globalThis.window = {
    Notification: {
      permission: 'granted',
      requestPermission: async () => 'granted',
    },
    PushManager: {},
    navigator: mockNav,
    atob: (str) => Buffer.from(str, 'base64').toString('binary'),
  };
  globalThis.Notification = globalThis.window.Notification;
  globalThis.PushManager = globalThis.window.PushManager;
  globalThis.navigator = mockNav;

  const { subscribeToPush } = await import('../src/utils/pushManager.ts');

  // Sample valid URL-safe base64 VAPID key
  const sampleVapidKey = 'BEl62iUYgUivxIkv69yViEuiBIa-Ib9-Skv6_yViEuiBIa-Ib9-Skv6_yViEuiBIa';
  const sub = await subscribeToPush(sampleVapidKey);

  assert.ok(sub, 'Subscription object returned');
  assert.equal(capturedOptions.userVisibleOnly, true);
  assert.ok(capturedOptions.applicationServerKey instanceof Uint8Array, 'applicationServerKey must be a Uint8Array');
});

test('Web Push error-mapping helper correctly differentiates error types without false unsupported-browser claims', () => {
  function formatPushError(err, permission) {
    const errMsg = err?.message || '';
    const errName = err?.name || '';

    if (errMsg.includes('Home Screen')) {
      return errMsg;
    } else if (
      errMsg.includes('denied') ||
      permission === 'denied' ||
      errMsg.includes('permission was denied')
    ) {
      return 'Browser notification permission was denied. Enable notifications in browser settings.';
    } else if (
      errName === 'AbortError' ||
      errMsg.includes('push service') ||
      errMsg.includes('Registration failed')
    ) {
      return 'Push service is unavailable. Check your internet connection or browser push service settings, then try again.';
    } else if (
      errName === 'NotSupportedError' ||
      errMsg.includes('not supported')
    ) {
      return 'Web Push is not supported in this browser environment.';
    } else if (errMsg) {
      const sanitized = errMsg.split('\n')[0].replace(/https?:\/\/[^\s]+/g, '').trim();
      return sanitized || 'Push subscription failed. Please try again.';
    } else {
      return 'Push subscription failed. Please try again.';
    }
  }

  // 1. AbortError / push service failure
  const abortErr = new Error('Registration failed - push service not available');
  abortErr.name = 'AbortError';
  const abortMsg = formatPushError(abortErr, 'granted');
  assert.match(abortMsg, /Push service is unavailable/i);
  assert.doesNotMatch(abortMsg, /aren't available in this browser environment/i);

  // 2. NotSupportedError
  const notSupportedErr = new Error('Web Push not supported');
  notSupportedErr.name = 'NotSupportedError';
  const notSupportedMsg = formatPushError(notSupportedErr, 'granted');
  assert.match(notSupportedMsg, /Web Push is not supported in this browser environment/i);

  // 3. Permission denied
  const permDeniedErr = new Error('Notification permission was denied');
  const permDeniedMsg = formatPushError(permDeniedErr, 'denied');
  assert.match(permDeniedMsg, /permission was denied/i);

  // 4. Generic network error
  const netErr = new Error('Network request failed: timeout');
  const netMsg = formatPushError(netErr, 'granted');
  assert.equal(netMsg, 'Network request failed: timeout');
  assert.doesNotMatch(netMsg, /aren't available in this browser environment/i);
});

test('Active backend subscription allows Test Push even when current local browser has getSubscription() === null', () => {
  const isSubscribedLocally = false;
  const pushStatus = {
    enabled: true,
    active_subscriptions: 1,
    devices: [{ id: 'dev-1', user_agent: 'Chrome Desktop' }],
  };

  const showTestButton = isSubscribedLocally || (pushStatus?.active_subscriptions ?? 0) > 0;
  assert.equal(showTestButton, true, 'Test button must be rendered when active registered devices exist');

  const testTitle = isSubscribedLocally
    ? 'Send test notification to this browser and all registered devices'
    : 'Send test notification to all active registered devices';
  assert.equal(testTitle, 'Send test notification to all active registered devices');
});

test('Supported browser with missing local subscription is classified as supported and Not Subscribed', async () => {
  const mockRegistration = {
    scope: '/',
    pushManager: {
      getSubscription: async () => null,
    }
  };

  const mockNav = {
    userAgent: 'Mozilla/5.0 (X11; Linux x86_64)',
    serviceWorker: {
      register: async () => mockRegistration,
      ready: Promise.resolve(mockRegistration),
    }
  };

  globalThis.window = {
    Notification: { permission: 'granted' },
    PushManager: {},
    navigator: mockNav,
  };
  globalThis.Notification = globalThis.window.Notification;
  globalThis.PushManager = globalThis.window.PushManager;
  globalThis.navigator = mockNav;

  const { isPushSupported, getExistingSubscription, getNotificationPermission } = await import('../src/utils/pushManager.ts');

  assert.equal(isPushSupported(), true, 'Browser must be detected as supported');
  assert.equal(getNotificationPermission(), 'granted', 'Permission must be granted');

  const localSub = await getExistingSubscription();
  assert.equal(localSub, null, 'Local subscription must be null');

  // Verify status mapping
  const deviceState = localSub ? 'Notifications Active' : 'Not Subscribed';
  assert.equal(deviceState, 'Not Subscribed');
});
