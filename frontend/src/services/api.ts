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

// ============================================================================
// AI Agent API Integration (Milestone 6)
// ============================================================================

export interface AgentChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface ConfirmationChallenge {
  status: 'confirmation_required';
  tool: string;
  target_id: string;
  action: string;
  confirmation_token: string;
  message: string;
}

export interface ToolActivityInfo {
  name: string;
  status: 'running' | 'completed' | 'failed' | 'confirmation_required';
  summary: string;
}

export interface AgentChatRequest {
  message: string;
  history?: AgentChatMessage[] | null;
  confirmation_token?: string | null;
  session_id?: string | null;
  disable_personalization?: boolean;
}

export interface PersonalizationMetadata {
  level: 'NONE' | 'LOW' | 'MEDIUM' | 'HIGH';
  applied_keys: string[];
  categories: string[];
  reason: string;
}

export interface AgentChatResponse {
  message: string;
  execution_id: string;
  tool_activities: ToolActivityInfo[];
  confirmation_required?: ConfirmationChallenge | null;
  metadata: {
    model?: string;
    duration_ms?: number;
    tool_calls_count?: number;
    personalization_metadata?: PersonalizationMetadata;
    [key: string]: any;
  };
  personalization_metadata?: PersonalizationMetadata | null;
}

export interface ToolDefinitionSchema {
  name: string;
  description: string;
  risk_level: 'READ' | 'LOW_RISK_WRITE' | 'HIGH_RISK_WRITE';
  parameters: Record<string, any>;
}

export interface AgentToolsResponse {
  tools: ToolDefinitionSchema[];
  total: number;
}

export async function sendAgentMessage(request: AgentChatRequest): Promise<AgentChatResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/agent/chat`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to communicate with AI Assistant' }));
    throw new Error(errorData.detail || `AI Assistant error (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function fetchAgentTools(): Promise<AgentToolsResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/agent/tools`, {
    method: 'GET',
    credentials: 'include',
    headers: { 'Accept': 'application/json' },
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to fetch agent tools' }));
    throw new Error(errorData.detail || `Failed to fetch agent tools (HTTP ${response.status})`);
  }

  return await response.json();
}

// ============================================================================
// Personal Knowledge & RAG API Integration (Milestone 7)
// ============================================================================

export interface KnowledgeCitation {
  citation_id: string;
  source_type: string;
  source_id: string;
  title: string;
  similarity_score: number;
}

export interface KnowledgeResultItem {
  citation_id: string;
  source_type: string;
  source_id: string;
  title: string;
  snippet: string;
  similarity_score: number;
  timestamp?: string | null;
  metadata?: Record<string, any>;
}

export interface KnowledgeSearchRequest {
  query: string;
  source_type?: string | null;
  top_k?: number | null;
  similarity_threshold?: number | null;
}

export interface KnowledgeSearchResponse {
  status: string;
  total_found: number;
  results: KnowledgeResultItem[];
  citations: KnowledgeCitation[];
}

export interface SourceStatusSummary {
  document_count: number;
  last_indexed?: string | null;
}

export interface KnowledgeStatusResponse {
  total_documents: number;
  total_chunks: number;
  last_indexed?: string | null;
  sources: Record<string, SourceStatusSummary>;
}

export interface KnowledgeReindexResponse {
  status: string;
  documents_processed: number;
  documents_indexed: number;
  documents_skipped: number;
  chunks_created: number;
  duration_ms: number;
  errors: string[];
}

export async function fetchKnowledgeStatus(): Promise<KnowledgeStatusResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/knowledge/status`, {
    method: 'GET',
    credentials: 'include',
    headers: { 'Accept': 'application/json' },
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to fetch knowledge status' }));
    throw new Error(errorData.detail || `Failed to fetch knowledge status (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function searchKnowledge(request: KnowledgeSearchRequest): Promise<KnowledgeSearchResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/knowledge/search`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to execute knowledge search' }));
    throw new Error(errorData.detail || `Knowledge search error (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function reindexKnowledge(): Promise<KnowledgeReindexResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/knowledge/reindex`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Accept': 'application/json' },
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to reindex knowledge' }));
    throw new Error(errorData.detail || `Knowledge reindex error (HTTP ${response.status})`);
  }

  return await response.json();
}

// ==========================================
// Milestone 8: Proactive AI Assistant Interfaces & API
// ==========================================

export interface SuggestedAction {
  action_type: string;
  target_resource: string;
  target_id: string;
  risk_level: 'READ' | 'LOW_RISK_WRITE' | 'HIGH_RISK_WRITE';
  display_label: string;
  action_payload: Record<string, any>;
}

export interface ProactiveCitation {
  source_type: string;
  source_id: string;
  title: string;
  snippet?: string;
  reference_time?: string;
}

export interface ProactiveNotification {
  id: string;
  user_id: string;
  title: string;
  message: string | null;
  notification_type: string;
  priority: 'low' | 'medium' | 'high' | 'urgent';
  source_type: string | null;
  source_id: string | null;
  status: string;
  created_at: string;
  read_at?: string | null;
  dismissed_at?: string | null;
  snoozed_until?: string | null;
  suggested_action?: SuggestedAction | null;
  citations: ProactiveCitation[];
  metadata: Record<string, any>;
}

export interface UserPreferences {
  proactive_enabled: boolean;
  memory_enabled?: boolean;
  calendar_alerts_enabled: boolean;
  task_alerts_enabled: boolean;
  reminder_alerts_enabled: boolean;
  email_alerts_enabled: boolean;
  quiet_hours_enabled: boolean;
  quiet_hours_start: string;
  quiet_hours_end: string;
  defer_high_priority_in_quiet_hours: boolean;
  user_timezone: string;
  min_priority: 'low' | 'medium' | 'high' | 'urgent';
  max_proactive_per_day: number;
  cooldown_minutes: number;
  last_gmail_proactive_check_at?: string | null;
  updated_at?: string;
}

export interface ProactiveStatusResponse {
  proactive_enabled: boolean;
  total_active_notifications: number;
  quiet_hours_active: boolean;
  user_timezone: string;
  last_check_at: string | null;
  category_status: {
    calendar: boolean;
    tasks: boolean;
    reminders: boolean;
    gmail: boolean;
  };
}

export interface ActionExecuteRequest {
  notification_id: string;
  action_type: string;
  target_id?: string | null;
  action_payload?: Record<string, any>;
  confirmation_token?: string;
}

export interface ActionExecuteResponse {
  status: 'completed' | 'success' | 'confirmation_required' | 'failed' | 'error';
  result?: any;
  message: string;
  confirmation_token?: string;
  confirmation_prompt?: string;
  confirmation_challenge?: {
    action: string;
    details: Record<string, any>;
    challenge_id: string;
    confirmation_token: string;
    expires_at: string;
  };
}

export interface ProactiveTriggerResponse {
  status: string;
  candidates_detected: number;
  notifications_created: number;
  details: Record<string, any>;
}

export async function fetchProactiveStatus(): Promise<ProactiveStatusResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/proactive/status`, {
    method: 'GET',
    credentials: 'include',
    headers: { 'Accept': 'application/json' },
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to fetch proactive status' }));
    throw new Error(errorData.detail || `Failed to fetch proactive status (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function fetchProactivePreferences(): Promise<UserPreferences> {
  const response = await fetch(`${API_BASE_URL}/api/v1/proactive/preferences`, {
    method: 'GET',
    credentials: 'include',
    headers: { 'Accept': 'application/json' },
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to fetch proactive preferences' }));
    throw new Error(errorData.detail || `Failed to fetch proactive preferences (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function updateProactivePreferences(prefs: Partial<UserPreferences>): Promise<UserPreferences> {
  const response = await fetch(`${API_BASE_URL}/api/v1/proactive/preferences`, {
    method: 'PATCH',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify(prefs),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to update preferences' }));
    throw new Error(errorData.detail || `Update preferences error (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function fetchProactiveNotifications(params?: {
  active_only?: boolean;
  limit?: number;
}): Promise<ProactiveNotification[]> {
  const query = new URLSearchParams();
  if (params?.active_only !== undefined) {
    query.set('active_only', String(params.active_only));
  }
  if (params?.limit !== undefined) {
    query.set('limit', String(params.limit));
  }

  const url = `${API_BASE_URL}/api/v1/proactive/notifications${query.toString() ? '?' + query.toString() : ''}`;
  const response = await fetch(url, {
    method: 'GET',
    credentials: 'include',
    headers: { 'Accept': 'application/json' },
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to fetch proactive notifications' }));
    throw new Error(errorData.detail || `Failed to fetch proactive notifications (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function markProactiveNotificationRead(notificationId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/v1/proactive/notifications/${notificationId}/read`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Accept': 'application/json' },
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to mark notification read' }));
    throw new Error(errorData.detail || `Mark read error (HTTP ${response.status})`);
  }
}

export async function dismissProactiveNotification(notificationId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/v1/proactive/notifications/${notificationId}/dismiss`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Accept': 'application/json' },
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to dismiss notification' }));
    throw new Error(errorData.detail || `Dismiss error (HTTP ${response.status})`);
  }
}

export async function snoozeProactiveNotification(notificationId: string, snoozeMinutes: number = 60): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/v1/proactive/notifications/${notificationId}/snooze`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify({ snooze_minutes: snoozeMinutes }),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to snooze notification' }));
    throw new Error(errorData.detail || `Snooze error (HTTP ${response.status})`);
  }
}

export async function executeProactiveAction(request: ActionExecuteRequest): Promise<ActionExecuteResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/proactive/actions/execute`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to execute action' }));
    throw new Error(errorData.detail || `Action execute error (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function triggerProactiveCheck(): Promise<ProactiveTriggerResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/proactive/trigger-check`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Accept': 'application/json' },
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to trigger proactive check' }));
    throw new Error(errorData.detail || `Trigger check error (HTTP ${response.status})`);
  }

  return await response.json();
}

// ==========================================
// Milestone 11: Long-Term Personal Memory & Personalization API
// ==========================================

export type MemoryCategory =
  | 'user_preference'
  | 'user_fact'
  | 'project_context'
  | 'workflow_preference'
  | 'explicit_user_memory';

export type MemoryConfidence =
  | 'EXPLICIT'
  | 'HIGH_CONFIDENCE'
  | 'MEDIUM_CONFIDENCE'
  | 'LOW_CONFIDENCE';

export interface MemoryItem {
  id: string;
  user_id: string;
  category: MemoryCategory;
  key: string;
  value: string;
  description: string | null;
  confidence: MemoryConfidence;
  confidence_score: number;
  source: string;
  source_reference: string | null;
  explicitly_confirmed: boolean;
  active: boolean;
  last_confirmed_at: string;
  memory_metadata: Record<string, any>;
  created_at: string;
  updated_at: string;
}

export interface MemoryListResponse {
  status: string;
  total: number;
  count: number;
  items: MemoryItem[];
}

export interface MemorySearchResponse {
  status: string;
  total_found: number;
  results: MemoryItem[];
}

export interface MemoryStatsResponse {
  total_memories: number;
  active_memories: number;
  inactive_memories: number;
  memory_enabled: boolean;
  by_category: Record<string, number>;
  by_confidence: Record<string, number>;
}

export interface MemoryCreateRequest {
  category: MemoryCategory;
  key: string;
  value: string;
  description?: string;
  confidence?: MemoryConfidence;
  source?: string;
  source_reference?: string;
  explicitly_confirmed?: boolean;
}

export interface MemoryUpdateRequest {
  value?: string;
  description?: string;
  category?: MemoryCategory;
  active?: boolean;
  explicitly_confirmed?: boolean;
  confidence?: MemoryConfidence;
}

export async function fetchMemories(params?: {
  category?: string;
  active?: boolean;
  limit?: number;
  offset?: number;
}): Promise<MemoryListResponse> {
  const queryParams = new URLSearchParams();
  if (params?.category) queryParams.append('category', params.category);
  if (params?.active !== undefined) queryParams.append('active', String(params.active));
  if (params?.limit) queryParams.append('limit', String(params.limit));
  if (params?.offset) queryParams.append('offset', String(params.offset));

  const qs = queryParams.toString();
  const url = `${API_BASE_URL}/api/v1/memories${qs ? `?${qs}` : ''}`;

  const response = await fetch(url, {
    method: 'GET',
    credentials: 'include',
    headers: { 'Accept': 'application/json' },
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Failed to fetch memories' }));
    throw new Error(err.detail || `Memory fetch error (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function createMemory(request: MemoryCreateRequest): Promise<MemoryItem> {
  const response = await fetch(`${API_BASE_URL}/api/v1/memories`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Failed to create memory' }));
    throw new Error(err.detail || `Memory creation error (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function searchMemories(query: string, category?: string): Promise<MemorySearchResponse> {
  const queryParams = new URLSearchParams({ query });
  if (category) queryParams.append('category', category);

  const response = await fetch(`${API_BASE_URL}/api/v1/memories/search?${queryParams.toString()}`, {
    method: 'GET',
    credentials: 'include',
    headers: { 'Accept': 'application/json' },
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Failed to search memories' }));
    throw new Error(err.detail || `Memory search error (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function fetchMemoryStats(): Promise<MemoryStatsResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/memories/stats`, {
    method: 'GET',
    credentials: 'include',
    headers: { 'Accept': 'application/json' },
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Failed to fetch memory stats' }));
    throw new Error(err.detail || `Memory stats error (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function getMemory(memoryId: string): Promise<MemoryItem> {
  const response = await fetch(`${API_BASE_URL}/api/v1/memories/${memoryId}`, {
    method: 'GET',
    credentials: 'include',
    headers: { 'Accept': 'application/json' },
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Memory not found' }));
    throw new Error(err.detail || `Memory fetch error (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function updateMemory(memoryId: string, update: MemoryUpdateRequest): Promise<MemoryItem> {
  const response = await fetch(`${API_BASE_URL}/api/v1/memories/${memoryId}`, {
    method: 'PATCH',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify(update),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Failed to update memory' }));
    throw new Error(err.detail || `Memory update error (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function deactivateMemory(memoryId: string): Promise<MemoryItem> {
  const response = await fetch(`${API_BASE_URL}/api/v1/memories/${memoryId}/deactivate`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Accept': 'application/json' },
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Failed to deactivate memory' }));
    throw new Error(err.detail || `Memory deactivate error (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function deleteMemory(memoryId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/v1/memories/${memoryId}`, {
    method: 'DELETE',
    credentials: 'include',
    headers: { 'Accept': 'application/json' },
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Failed to delete memory' }));
    throw new Error(err.detail || `Memory delete error (HTTP ${response.status})`);
  }
}

// ============================================================================
// MILESTONE 12: PERSONALIZATION INTELLIGENCE & POLICY
// ============================================================================

export type PersonalizationLevelType = 'NONE' | 'LOW' | 'MEDIUM' | 'HIGH';

export interface PersonalizationConfigResponse {
  personalization_enabled: boolean;
  personalization_level: PersonalizationLevelType;
  personalize_response_style: boolean;
  personalize_project_context: boolean;
  personalize_workflow_habits: boolean;
}

export interface PersonalizationConfigUpdate {
  personalization_enabled?: boolean;
  personalization_level?: PersonalizationLevelType;
  personalize_response_style?: boolean;
  personalize_project_context?: boolean;
  personalize_workflow_habits?: boolean;
}

export interface PersonalizationPreviewItem {
  category: string;
  key: string;
  relevance_score: number;
  is_selected: boolean;
  selection_reason: string;
}

export interface PersonalizationPreviewResponse {
  query: string;
  items: PersonalizationPreviewItem[];
}

export interface PersonalizationSessionOverrideResponse {
  session_id: string;
  personalization_disabled: boolean;
  message: string;
}

export async function fetchPersonalizationConfig(): Promise<PersonalizationConfigResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/personalization/config`, {
    method: 'GET',
    credentials: 'include',
    headers: { 'Accept': 'application/json' },
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Failed to fetch personalization config' }));
    throw new Error(err.detail || `Personalization config error (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function updatePersonalizationConfig(
  update: PersonalizationConfigUpdate
): Promise<PersonalizationConfigResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/personalization/config`, {
    method: 'PATCH',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify(update),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Failed to update personalization config' }));
    throw new Error(err.detail || `Personalization update error (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function previewPersonalization(
  query: string,
  limit: number = 10
): Promise<PersonalizationPreviewResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/personalization/preview`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify({ query, limit }),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Failed to preview personalization' }));
    throw new Error(err.detail || `Personalization preview error (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function setPersonalizationSessionOverride(
  sessionId: string,
  disablePersonalization: boolean
): Promise<PersonalizationSessionOverrideResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/personalization/session-override`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify({
      session_id: sessionId,
      disable_personalization: disablePersonalization,
    }),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Failed to set session override' }));
    throw new Error(err.detail || `Personalization session override error (HTTP ${response.status})`);
  }

  return await response.json();
}

// ---------------------------------------------------------------------------
// Web Push Notifications API
// ---------------------------------------------------------------------------

export interface PushDevice {
  id: string;
  endpoint: string;
  user_agent: string | null;
  created_at: string;
  last_used_at: string | null;
}

export interface PushStatusResponse {
  enabled: boolean;
  vapid_public_key: string | null;
  active_subscriptions: number;
  devices: PushDevice[];
}

export interface PushTestResponse {
  status: string;
  message: string;
  delivered_count: number;
  failed_count: number;
}

export async function fetchVapidPublicKey(): Promise<{ vapid_public_key: string }> {
  const response = await fetch(`${API_BASE_URL}/api/v1/notifications/push/vapid-public-key`, {
    method: 'GET',
    credentials: 'include',
    headers: {
      'Accept': 'application/json',
    },
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Failed to fetch VAPID public key' }));
    throw new Error(err.detail || `VAPID key error (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function fetchPushStatus(): Promise<PushStatusResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/notifications/push/status`, {
    method: 'GET',
    credentials: 'include',
    headers: {
      'Accept': 'application/json',
    },
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Failed to fetch push status' }));
    throw new Error(err.detail || `Push status error (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function subscribePushDevice(subscription: PushSubscription): Promise<{ id: string; endpoint: string }> {
  const subJson = subscription.toJSON();
  if (!subJson.endpoint || !subJson.keys?.p256dh || !subJson.keys?.auth) {
    throw new Error('Malformed push subscription object from browser');
  }

  const response = await fetch(`${API_BASE_URL}/api/v1/notifications/push/subscribe`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify({
      endpoint: subJson.endpoint,
      keys: {
        p256dh: subJson.keys.p256dh,
        auth: subJson.keys.auth,
      },
      user_agent: navigator.userAgent,
    }),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Failed to register push subscription' }));
    throw new Error(err.detail || `Push subscribe error (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function unsubscribePushDevice(endpoint: string): Promise<{ status: string; message: string }> {
  const response = await fetch(`${API_BASE_URL}/api/v1/notifications/push/unsubscribe`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify({ endpoint }),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Failed to unsubscribe push device' }));
    throw new Error(err.detail || `Push unsubscribe error (HTTP ${response.status})`);
  }

  return await response.json();
}

export async function sendTestPushNotification(title?: string, body?: string): Promise<PushTestResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/notifications/push/test`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify({ title, body }),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Failed to send test push notification' }));
    throw new Error(err.detail || `Test push error (HTTP ${response.status})`);
  }

  return await response.json();
}
