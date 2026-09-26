import test from 'node:test';
import assert from 'node:assert/strict';

test('registerServiceWorker reuses in-flight promise and prevents duplicate calls', async () => {
  let registerCallCount = 0;

  const mockRegistration = {
    scope: '/',
    active: { state: 'activated' }
  };

  const mockNav = {
    userAgent: 'Mozilla/5.0 (X11; Linux x86_64)',
    serviceWorker: {
      register: async (scriptUrl, options) => {
        registerCallCount++;
        return mockRegistration;
      },
      ready: Promise.resolve(mockRegistration)
    }
  };

  // Setup globals for mock browser environment
  globalThis.window = {
    Notification: { permission: 'default' },
    PushManager: {},
    navigator: mockNav,
  };
  globalThis.Notification = globalThis.window.Notification;
  globalThis.PushManager = globalThis.window.PushManager;
  globalThis.navigator = mockNav;

  // Dynamically import pushManager
  const { registerServiceWorker } = await import('../src/utils/pushManager.ts');

  // Call 1: Startup registration (e.g. from main.tsx)
  const reg1 = await registerServiceWorker();
  assert.equal(registerCallCount, 1, 'First call should register service worker');
  assert.equal(reg1, mockRegistration);

  // Call 2: Visiting Settings -> Notifications
  const reg2 = await registerServiceWorker();
  assert.equal(registerCallCount, 1, 'Second call must reuse cached registration and not call register() again');
  assert.equal(reg2, reg1);

  // Call 3: Another tab/action
  const reg3 = await registerServiceWorker();
  assert.equal(registerCallCount, 1, 'Third call must also not call register() again');
  assert.equal(reg3, reg1);
});
