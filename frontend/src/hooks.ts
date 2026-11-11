import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, streamUrl } from "./api/client";
import type { StreamMessage } from "./api/types";

export type Async<T> =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "missing" } // the API answered 404: nothing has been produced yet
  | { state: "ready"; data: T };

/**
 * Load data from the API. A failed request is reported as an error and a 404 as
 * "missing"; neither is ever replaced by placeholder values.
 */
export function useApi<T>(
  loader: () => Promise<T>,
  deps: unknown[] = [],
): [Async<T>, () => void] {
  const [result, setResult] = useState<Async<T>>({ state: "loading" });
  const [version, setVersion] = useState(0);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    let cancelled = false;
    setResult({ state: "loading" });
    loaderRef
      .current()
      .then((data) => {
        if (!cancelled) setResult({ state: "ready", data });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (error instanceof ApiError && error.status === 404) {
          setResult({ state: "missing" });
        } else {
          const message = error instanceof Error ? error.message : "Unknown error";
          setResult({ state: "error", message });
        }
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version, ...deps]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  return [result, reload];
}

/** Connect to the live stream and report whether it is connected. */
export function useStream(onMessage: (message: StreamMessage) => void): boolean {
  const [connected, setConnected] = useState(false);
  const handler = useRef(onMessage);
  handler.current = onMessage;

  useEffect(() => {
    if (typeof WebSocket === "undefined") return;
    let socket: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let closed = false;

    const connect = () => {
      socket = new WebSocket(streamUrl());
      socket.onopen = () => setConnected(true);
      socket.onmessage = (event) => {
        try {
          handler.current(JSON.parse(String(event.data)) as StreamMessage);
        } catch {
          // Ignore malformed messages.
        }
      };
      socket.onclose = () => {
        setConnected(false);
        if (!closed) timer = setTimeout(connect, 5000);
      };
      socket.onerror = () => socket?.close();
    };
    connect();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      socket?.close();
    };
  }, []);

  return connected;
}
