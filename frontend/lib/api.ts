export type ChatRole = 'user' | 'assistant' | 'system';

export type ChatMessage = {
  role: ChatRole;
  content: string;
};

export type Token = {
  access_token: string;
  token_type: string;
  expires_at: string;
};

export type UserProfile = {
  id?: number;
  email: string;
  username?: string | null;
};

export type UserResponse = UserProfile & {
  token: Token;
};

export type Session = {
  session_id: string;
  name: string;
  token: Token;
};

type StreamEvent = {
  content: string;
  done: boolean;
};

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000/api/v1';

async function readError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as {
      detail?: string;
      errors?: Array<{ field?: string; message?: string }>;
    };
    if (payload.errors?.length) {
      return payload.errors
        .map((item) => item.message)
        .filter(Boolean)
        .join('；');
    }
    return payload.detail ?? `请求失败（${response.status}）`;
  } catch {
    return `请求失败（${response.status}）`;
  }
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  token?: string,
): Promise<T> {
  const headers = new Headers(init.headers);
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (init.body && !(init.body instanceof URLSearchParams)) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
  });

  if (!response.ok) throw new Error(await readError(response));
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function healthCheck(): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE_URL}/health`);
    return response.ok;
  } catch {
    return false;
  }
}

export function register(input: {
  email: string;
  password: string;
  username?: string;
}): Promise<UserResponse> {
  return request<UserResponse>('/auth/register', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function login(email: string, password: string): Promise<Token> {
  const body = new URLSearchParams({ email, password, grant_type: 'password' });
  return request<Token>('/auth/login', { method: 'POST', body });
}

export function listSessions(userToken: string): Promise<Session[]> {
  return request<Session[]>('/auth/sessions', {}, userToken);
}

export function createSession(userToken: string): Promise<Session> {
  return request<Session>('/auth/session', { method: 'POST' }, userToken);
}

export function renameSession(
  session: Session,
  name: string,
): Promise<Session> {
  const body = new URLSearchParams({ name });
  return request<Session>(
    `/auth/session/${session.session_id}/name`,
    { method: 'PATCH', body },
    session.token.access_token,
  );
}

export function deleteSession(session: Session): Promise<void> {
  return request<void>(
    `/auth/session/${session.session_id}`,
    { method: 'DELETE' },
    session.token.access_token,
  );
}

export async function getMessages(session: Session): Promise<ChatMessage[]> {
  const response = await request<{ messages: ChatMessage[] }>(
    '/chatbot/messages',
    {},
    session.token.access_token,
  );
  return response.messages;
}

export function clearMessages(session: Session): Promise<{ message: string }> {
  return request<{ message: string }>(
    '/chatbot/messages',
    { method: 'DELETE' },
    session.token.access_token,
  );
}

export async function streamMessage(
  session: Session,
  content: string,
  onChunk: (content: string) => void,
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/chatbot/chat/stream`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${session.token.access_token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ messages: [{ role: 'user', content }] }),
  });

  if (!response.ok) throw new Error(await readError(response));
  if (!response.body) throw new Error('浏览器未收到流式响应');

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const events = buffer.split('\n\n');
    buffer = events.pop() ?? '';

    for (const event of events) {
      const data = event
        .split('\n')
        .find((line) => line.startsWith('data: '))
        ?.slice(6);
      if (!data) continue;
      const payload = JSON.parse(data) as StreamEvent;
      if (payload.content) onChunk(payload.content);
    }

    if (done) break;
  }
}
