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
