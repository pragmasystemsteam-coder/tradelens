// Live updates over Server-Sent Events (Detailed Design 4.4). Messages only say what changed:
// the page refetches over REST, and after any reconnect it refetches everything it shows.
//
// One EventSource per page: every component subscribes here and the hub opens a single stream
// with the union of their topics (a page with the scanner and a chart would otherwise hold two
// connections of the 6 a user may have, and two of the browser's 6 HTTP/1.1 slots).
// EventSource retries on its own after a network drop, but an HTTP error (502 during a deploy,
// 429 when all streams are taken) closes it for good: then the hub reopens it with backoff.

export type StreamHandlers = {
  onEvent: (event: string, data: Record<string, unknown>) => void;
  /** Called when the stream comes back after an error: refetch everything on screen. */
  onReconnect: () => void;
  onStateChange?: (connected: boolean) => void;
};

type Subscriber = { topics: string[]; handlers: StreamHandlers };

const EVENTS = [
  "scanner.updated",
  "chart.updated",
  "price",
  "series.delayed",
  "series.resumed",
  "notification",
  "plan.changed",
  "session.ended",
];
const BACKOFF_MS = [1000, 2000, 5000, 10000, 30000];

const subscribers = new Set<Subscriber>();
let source: EventSource | null = null;
let currentTopics = "";
let failed = false;
let attempt = 0;
let retryTimer: ReturnType<typeof setTimeout> | null = null;
let syncQueued = false;

function each(fn: (h: StreamHandlers) => void) {
  for (const s of subscribers) fn(s.handlers);
}

function close() {
  if (retryTimer) clearTimeout(retryTimer);
  retryTimer = null;
  source?.close();
  source = null;
}

function connect() {
  if (subscribers.size === 0) return;
  const es = new EventSource(`/api/v1/stream?topics=${encodeURIComponent(currentTopics)}`, {
    withCredentials: true,
  });
  source = es;
  es.onopen = () => {
    attempt = 0;
    each((h) => h.onStateChange?.(true));
    if (failed) {
      failed = false;
      each((h) => h.onReconnect());
    }
  };
  es.onerror = () => {
    failed = true;
    each((h) => h.onStateChange?.(false));
    if (es.readyState === EventSource.CLOSED && source === es) {
      const wait = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)];
      attempt += 1;
      retryTimer = setTimeout(connect, wait);
    }
  };
  for (const name of EVENTS) {
    es.addEventListener(name, (msg) => {
      if (source !== es) return;
      let data: Record<string, unknown> = {};
      try {
        data = JSON.parse((msg as MessageEvent<string>).data);
      } catch {
        return;
      }
      if (name === "session.ended") {
        close();
        window.location.assign("/login?ended=1");
        return;
      }
      each((h) => h.onEvent(name, data));
    });
  }
}

/** Reopen the shared stream when the union of topics changed (batched per tick). */
function sync() {
  if (syncQueued) return;
  syncQueued = true;
  queueMicrotask(() => {
    syncQueued = false;
    if (subscribers.size === 0) {
      close();
      currentTopics = "";
      return;
    }
    const topics = [...new Set([...subscribers].flatMap((s) => s.topics))].sort().join(",");
    if (topics === currentTopics && source) return;
    close();
    currentTopics = topics;
    connect();
  });
}

export function openStream(topics: string[], handlers: StreamHandlers): () => void {
  const sub: Subscriber = { topics, handlers };
  subscribers.add(sub);
  sync();
  return () => {
    subscribers.delete(sub);
    sync();
  };
}
