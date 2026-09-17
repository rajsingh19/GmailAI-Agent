/**
 * Personal AI Assistant Service Worker
 * Handles Web Push notifications, lifecycle events, and notification click navigation.
 * Contains no secrets or sensitive user credentials.
 */

self.addEventListener('install', (event) => {
  // Activate immediately without waiting for old instances to close
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  // Claim control of all open pages immediately
  event.waitUntil(self.clients.claim());
});

self.addEventListener('push', (event) => {
  let payload = {};
  if (event.data) {
    try {
      payload = event.data.json();
    } catch (e) {
      payload = {
        title: 'Personal AI Assistant',
        body: event.data.text(),
      };
    }
  }

  const title = payload.title || 'Personal AI Assistant';
  const options = {
    body: payload.body || 'You have a new update.',
    icon: payload.icon || '/icons/icon-192.png',
    badge: payload.badge || '/icons/badge-72.png',
    tag: payload.tag || (payload.reminder_id ? `reminder-${payload.reminder_id}` : 'ai-alert'),
    renotify: true,
    requireInteraction: payload.type === 'reminder' || payload.type === 'urgent',
    data: {
      url: payload.url || '/',
      type: payload.type,
      reminder_id: payload.reminder_id,
      task_id: payload.task_id,
      notification_id: payload.notification_id,
    },
    actions: [
      { action: 'open', title: 'Open Dashboard' },
      { action: 'dismiss', title: 'Dismiss' },
    ],
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  if (event.action === 'dismiss') {
    return;
  }

  const notificationData = event.notification.data || {};
  const targetUrl = notificationData.url || '/';

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      // Focus existing window if open
      for (const client of clientList) {
        if (client.url && 'focus' in client) {
          return client.focus();
        }
      }
      // Otherwise open a new window
      if (self.clients.openWindow) {
        return self.clients.openWindow(targetUrl);
      }
    })
  );
});
