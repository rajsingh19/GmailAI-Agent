export interface HealthResponse {
  status: string;
  service: string;
  version: string;
  environment: string;
  timestamp: string;
}

export interface HealthCheckResult {
  data: HealthResponse | null;
  latencyMs: number;
  error: string | null;
  fetchedAt: Date;
}

export interface GoogleAccountStatus {
  connected: boolean;
  email: string | null;
  google_user_id?: string;
  picture_url: string | null;
  scopes: string[];
  is_expired: boolean;
  requires_reauth: boolean;
  connected_at?: string | null;
}

export interface UserProfile {
  id: string;
  email: string;
  full_name: string | null;
  picture_url: string | null;
}

export interface AuthStatusResponse {
  authenticated: boolean;
  user: UserProfile | null;
  google_account: GoogleAccountStatus;
}

export const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export async function fetchHealth(): Promise<HealthCheckResult> {
  const startTime = performance.now();
  try {
    const response = await fetch(`${API_BASE_URL}/health`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      },
    });

    const latencyMs = Math.round(performance.now() - startTime);

    if (!response.ok) {
      throw new Error(`Server returned HTTP ${response.status}: ${response.statusText}`);
    }

    const data: HealthResponse = await response.json();
    return {
      data,
      latencyMs,
      error: null,
      fetchedAt: new Date(),
    };
  } catch (err: any) {
    const latencyMs = Math.round(performance.now() - startTime);
    return {
      data: null,
      latencyMs,
      error: err.message || 'Unable to connect to backend server',
      fetchedAt: new Date(),
    };
  }
}

export async function fetchAuthStatus(): Promise<AuthStatusResponse> {
  const response = await fetch(`${API_BASE_URL}/auth/status`, {
    method: 'GET',
    credentials: 'include', // Include HttpOnly session cookie
    headers: {
      'Accept': 'application/json',
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch auth status (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function logout(): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/auth/logout`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Accept': 'application/json',
    },
  });

  if (!response.ok) {
    throw new Error(`Logout failed (HTTP ${response.status})`);
  }
}

export async function disconnectGoogleAccount(): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/auth/google/disconnect`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Accept': 'application/json',
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to disconnect Google account (HTTP ${response.status})`);
  }
}

export function getGoogleOAuthUrl(): string {
  return `${API_BASE_URL}/auth/google`;
}

// ============================================================================
// Gmail API Integration
// ============================================================================

export interface GmailProfile {
  email: string;
  messages_total: number;
  threads_total: number;
  history_id?: string | null;
}

export interface GmailAttachmentMetadata {
  attachment_id?: string | null;
  filename: string;
  mime_type: string;
  size: number;
}

export interface GmailMessageSummary {
  id: string;
  thread_id: string;
  subject: string;
  sender: string;
  recipients: string[];
  timestamp?: string | null;
  snippet: string;
  labels: string[];
  is_unread: boolean;
  has_attachments: boolean;
}

export interface GmailMessageDetail {
  id: string;
  thread_id: string;
  subject: string;
  sender: string;
  recipients: string[];
  cc: string[];
  bcc: string[];
  timestamp?: string | null;
  snippet: string;
  body_plain?: string | null;
  body_html_text?: string | null;
  labels: string[];
  is_unread: boolean;
  attachments: GmailAttachmentMetadata[];
}

export interface GmailMessageListResponse {
  messages: GmailMessageSummary[];
  next_page_token?: string | null;
  result_size_estimate: number;
}

export async function fetchGmailProfile(): Promise<GmailProfile> {
  const response = await fetch(`${API_BASE_URL}/api/v1/gmail/profile`, {
    method: 'GET',
    credentials: 'include',
    headers: {
      'Accept': 'application/json',
    },
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to fetch Gmail profile' }));
    throw new Error(errorData.detail || `Failed to fetch Gmail profile (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function fetchGmailMessages(params?: {
  max_results?: number;
  page_token?: string;
  query?: string;
}): Promise<GmailMessageListResponse> {
  const queryParams = new URLSearchParams();
  if (params?.max_results) queryParams.set('max_results', params.max_results.toString());
  if (params?.page_token) queryParams.set('page_token', params.page_token);
  if (params?.query) queryParams.set('query', params.query);

  const url = `${API_BASE_URL}/api/v1/gmail/messages${queryParams.toString() ? `?${queryParams.toString()}` : ''}`;
  const response = await fetch(url, {
    method: 'GET',
    credentials: 'include',
    headers: {
      'Accept': 'application/json',
    },
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to fetch messages' }));
    throw new Error(errorData.detail || `Failed to fetch Gmail messages (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function fetchGmailMessageDetail(messageId: string): Promise<GmailMessageDetail> {
  const response = await fetch(`${API_BASE_URL}/api/v1/gmail/messages/${encodeURIComponent(messageId)}`, {
    method: 'GET',
    credentials: 'include',
    headers: {
      'Accept': 'application/json',
    },
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to fetch message details' }));
    throw new Error(errorData.detail || `Failed to fetch message details (HTTP ${response.status})`);
  }

  return await response.json();
}

// ============================================================================
// Google Calendar API Integration
// ============================================================================

export interface CalendarSummary {
  id: string;
  summary: string;
  description?: string | null;
  time_zone?: string | null;
  primary: boolean;
  background_color?: string | null;
  access_role?: string | null;
  selected: boolean;
  hidden: boolean;
}

export interface CalendarListResponse {
  calendars: CalendarSummary[];
  next_page_token?: string | null;
}

export interface CalendarDetail {
  id: string;
  summary: string;
  description?: string | null;
  location?: string | null;
  time_zone?: string | null;
  primary: boolean;
  access_role?: string | null;
  selected: boolean;
  hidden: boolean;
}

export interface CalendarAttendee {
  email?: string | null;
  display_name?: string | null;
  response_status?: string | null;
  organizer: boolean;
  self: boolean;
}

export interface CalendarConferenceData {
  entry_point_type?: string | null;
  uri?: string | null;
  label?: string | null;
  solution_name?: string | null;
}

export interface CalendarEventSummary {
  id: string;
  calendar_id: string;
  summary: string;
  description?: string | null;
  location?: string | null;
  start: string;
  end: string;
  time_zone?: string | null;
  status: string;
  html_link?: string | null;
  organizer?: string | null;
  attendees_count: number;
  is_all_day: boolean;
  has_conference: boolean;
  conference_uri?: string | null;
}

export interface CalendarEventDetail {
  id: string;
  calendar_id: string;
  summary: string;
  description?: string | null;
  location?: string | null;
  start: string;
  end: string;
  time_zone?: string | null;
  status: string;
  html_link?: string | null;
  organizer?: string | null;
  creator?: string | null;
  attendees: CalendarAttendee[];
  conference?: CalendarConferenceData | null;
  recurrence: string[];
  is_all_day: boolean;
}

export interface CalendarEventListResponse {
  events: CalendarEventSummary[];
  next_page_token?: string | null;
  calendar_id: string;
}

export async function fetchCalendars(pageToken?: string): Promise<CalendarListResponse> {
  const queryParams = new URLSearchParams();
  if (pageToken) queryParams.set('page_token', pageToken);

  const url = `${API_BASE_URL}/api/v1/calendar/calendars${queryParams.toString() ? `?${queryParams.toString()}` : ''}`;
  const response = await fetch(url, {
    method: 'GET',
    credentials: 'include',
    headers: {
      'Accept': 'application/json',
    },
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to fetch calendars' }));
    throw new Error(errorData.detail || `Failed to fetch calendars (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function fetchCalendar(calendarId: string): Promise<CalendarDetail> {
  const response = await fetch(`${API_BASE_URL}/api/v1/calendar/calendars/${encodeURIComponent(calendarId)}`, {
    method: 'GET',
    credentials: 'include',
    headers: {
      'Accept': 'application/json',
    },
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to fetch calendar' }));
    throw new Error(errorData.detail || `Failed to fetch calendar (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function fetchCalendarEvents(params?: {
  calendar_id?: string;
  time_min?: string;
  time_max?: string;
  max_results?: number;
  page_token?: string;
  query?: string;
  single_events?: boolean;
}): Promise<CalendarEventListResponse> {
  const queryParams = new URLSearchParams();
  if (params?.calendar_id) queryParams.set('calendar_id', params.calendar_id);
  if (params?.time_min) queryParams.set('time_min', params.time_min);
  if (params?.time_max) queryParams.set('time_max', params.time_max);
  if (params?.max_results) queryParams.set('max_results', params.max_results.toString());
  if (params?.page_token) queryParams.set('page_token', params.page_token);
  if (params?.query) queryParams.set('query', params.query);
  if (params?.single_events !== undefined) queryParams.set('single_events', String(params.single_events));

  const url = `${API_BASE_URL}/api/v1/calendar/events${queryParams.toString() ? `?${queryParams.toString()}` : ''}`;
  const response = await fetch(url, {
    method: 'GET',
    credentials: 'include',
    headers: {
      'Accept': 'application/json',
    },
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to fetch calendar events' }));
    throw new Error(errorData.detail || `Failed to fetch calendar events (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function fetchCalendarEventDetail(
  calendarId: string,
  eventId: string,
): Promise<CalendarEventDetail> {
  const response = await fetch(
    `${API_BASE_URL}/api/v1/calendar/calendars/${encodeURIComponent(calendarId)}/events/${encodeURIComponent(eventId)}`,
    {
      method: 'GET',
      credentials: 'include',
      headers: {
        'Accept': 'application/json',
      },
    },
  );

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to fetch event details' }));
    throw new Error(errorData.detail || `Failed to fetch event details (HTTP ${response.status})`);
  }

  return await response.json();
}

// ============================================================================
// Tasks & Reminders API Integration (Milestone 5)
// ============================================================================

export interface Task {
  id: string;
  user_id: string;
  title: string;
  description?: string | null;
  status: 'pending' | 'completed' | 'cancelled';
  priority: 'low' | 'medium' | 'high';
  due_at?: string | null;
  timezone?: string | null;
  completed_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface TaskListResponse {
  items: Task[];
  total: number;
}

export interface TaskCreateInput {
  title: string;
  description?: string;
  priority?: 'low' | 'medium' | 'high';
  due_at?: string | null;
  timezone?: string;
}

export interface TaskUpdateInput {
  title?: string;
  description?: string;
  priority?: 'low' | 'medium' | 'high';
  status?: 'pending' | 'completed' | 'cancelled';
  due_at?: string | null;
  timezone?: string;
}

export interface Reminder {
  id: string;
  user_id: string;
  task_id?: string | null;
  title: string;
  message?: string | null;
  remind_at: string;
  timezone: string;
  recurrence_rule?: string | null;
  status: 'scheduled' | 'processing' | 'triggered' | 'snoozed' | 'cancelled' | 'failed';
  last_triggered_at?: string | null;
  next_trigger_at?: string | null;
  snoozed_until?: string | null;
  retry_count: number;
  created_at: string;
  updated_at: string;
}

export interface ReminderListResponse {
  items: Reminder[];
  total: number;
}

export interface ReminderCreateInput {
  title: string;
  message?: string;
  remind_at: string;
  timezone?: string;
  recurrence_rule?: string;
  task_id?: string;
}

export interface ReminderSnoozeInput {
  duration?: '5m' | '15m' | '30m' | '1h' | '1d';
  snooze_until?: string;
}

export interface Notification {
  id: string;
  user_id: string;
  reminder_id?: string | null;
  idempotency_key: string;
  title: string;
  message?: string | null;
  status: 'unread' | 'read';
  created_at: string;
  read_at?: string | null;
}

export interface NotificationListResponse {
  items: Notification[];
  total: number;
  unread_count: number;
}

export async function fetchTasks(params?: {
  status?: string;
  priority?: string;
  limit?: number;
  offset?: number;
}): Promise<TaskListResponse> {
  const queryParams = new URLSearchParams();
  if (params?.status) queryParams.set('status', params.status);
  if (params?.priority) queryParams.set('priority', params.priority);
  if (params?.limit) queryParams.set('limit', params.limit.toString());
  if (params?.offset) queryParams.set('offset', params.offset.toString());

  const url = `${API_BASE_URL}/api/v1/tasks${queryParams.toString() ? `?${queryParams.toString()}` : ''}`;
  const response = await fetch(url, {
    method: 'GET',
    credentials: 'include',
    headers: { 'Accept': 'application/json' },
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to fetch tasks' }));
    throw new Error(errorData.detail || `Failed to fetch tasks (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function createTask(input: TaskCreateInput): Promise<Task> {
  const response = await fetch(`${API_BASE_URL}/api/v1/tasks`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify(input),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to create task' }));
    throw new Error(errorData.detail || `Failed to create task (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function updateTask(taskId: string, input: TaskUpdateInput): Promise<Task> {
  const response = await fetch(`${API_BASE_URL}/api/v1/tasks/${encodeURIComponent(taskId)}`, {
    method: 'PATCH',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify(input),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to update task' }));
    throw new Error(errorData.detail || `Failed to update task (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function completeTask(taskId: string): Promise<Task> {
  const response = await fetch(`${API_BASE_URL}/api/v1/tasks/${encodeURIComponent(taskId)}/complete`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Accept': 'application/json' },
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to complete task' }));
    throw new Error(errorData.detail || `Failed to complete task (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function deleteTask(taskId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/v1/tasks/${encodeURIComponent(taskId)}`, {
    method: 'DELETE',
    credentials: 'include',
    headers: { 'Accept': 'application/json' },
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to delete task' }));
    throw new Error(errorData.detail || `Failed to delete task (HTTP ${response.status})`);
  }
}

export async function fetchReminders(params?: {
  status?: string;
  task_id?: string;
  limit?: number;
  offset?: number;
}): Promise<ReminderListResponse> {
  const queryParams = new URLSearchParams();
  if (params?.status) queryParams.set('status', params.status);
  if (params?.task_id) queryParams.set('task_id', params.task_id);
  if (params?.limit) queryParams.set('limit', params.limit.toString());
  if (params?.offset) queryParams.set('offset', params.offset.toString());

  const url = `${API_BASE_URL}/api/v1/reminders${queryParams.toString() ? `?${queryParams.toString()}` : ''}`;
  const response = await fetch(url, {
    method: 'GET',
    credentials: 'include',
    headers: { 'Accept': 'application/json' },
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to fetch reminders' }));
    throw new Error(errorData.detail || `Failed to fetch reminders (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function createReminder(input: ReminderCreateInput): Promise<Reminder> {
  const response = await fetch(`${API_BASE_URL}/api/v1/reminders`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify(input),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to create reminder' }));
    throw new Error(errorData.detail || `Failed to create reminder (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function snoozeReminder(reminderId: string, input: ReminderSnoozeInput): Promise<Reminder> {
  const response = await fetch(`${API_BASE_URL}/api/v1/reminders/${encodeURIComponent(reminderId)}/snooze`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify(input),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to snooze reminder' }));
    throw new Error(errorData.detail || `Failed to snooze reminder (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function cancelReminder(reminderId: string): Promise<Reminder> {
  const response = await fetch(`${API_BASE_URL}/api/v1/reminders/${encodeURIComponent(reminderId)}/cancel`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Accept': 'application/json' },
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to cancel reminder' }));
    throw new Error(errorData.detail || `Failed to cancel reminder (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function deleteReminder(reminderId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/v1/reminders/${encodeURIComponent(reminderId)}`, {
    method: 'DELETE',
    credentials: 'include',
    headers: { 'Accept': 'application/json' },
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to delete reminder' }));
    throw new Error(errorData.detail || `Failed to delete reminder (HTTP ${response.status})`);
  }
}

export async function fetchNotifications(params?: {
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<NotificationListResponse> {
  const queryParams = new URLSearchParams();
  if (params?.status) queryParams.set('status', params.status);
  if (params?.limit) queryParams.set('limit', params.limit.toString());
  if (params?.offset) queryParams.set('offset', params.offset.toString());

  const url = `${API_BASE_URL}/api/v1/notifications${queryParams.toString() ? `?${queryParams.toString()}` : ''}`;
  const response = await fetch(url, {
    method: 'GET',
    credentials: 'include',
    headers: { 'Accept': 'application/json' },
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to fetch notifications' }));
    throw new Error(errorData.detail || `Failed to fetch notifications (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function markNotificationsRead(notificationIds?: string[]): Promise<{ marked_read_count: number }> {
  const response = await fetch(`${API_BASE_URL}/api/v1/notifications/read`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify({ notification_ids: notificationIds || null }),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to mark notifications read' }));
    throw new Error(errorData.detail || `Failed to mark notifications read (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function deleteNotification(notificationId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/v1/notifications/${encodeURIComponent(notificationId)}`, {
    method: 'DELETE',
    credentials: 'include',
    headers: { 'Accept': 'application/json' },
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to delete notification' }));
    throw new Error(errorData.detail || `Failed to delete notification (HTTP ${response.status})`);
  }
}



