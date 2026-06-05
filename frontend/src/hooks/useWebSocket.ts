/**
 * React hook for the BTC Signal Pro WebSocket connection.
 *
 * Manages connection lifecycle, exponential back-off reconnection,
 * and dispatches incoming messages to registered handlers.
 *
 * Usage:
 *   const { connected } = useWebSocket({ onMessage: handleMessage });
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { WsMessage } from "../utils/types";

interface UseWebSocketOptions {
  url?: string;
  onMessage: (msg: WsMessage) => void;
  enabled?: boolean;
}

interface UseWebSocketReturn {
  connected: boolean;
  reconnectCount: number;
}

const WS_URL =
  import.meta.env.VITE_WS_URL ||
  `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws`;

const INITIAL_DELAY = 1000;
const MAX_DELAY = 30_000;

export function useWebSocket({
  url = WS_URL,
  onMessage,
  enabled = true,
}: UseWebSocketOptions): UseWebSocketReturn {
  const [connected, setConnected] = useState(false);
  const [reconnectCount, setReconnectCount] = useState(0);
  const wsRef = useRef<WebSocket | null>(null);
  const delayRef = useRef(INITIAL_DELAY);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);
  const onMessageRef = useRef(onMessage);

  // Keep callback ref current without triggering reconnects
  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  const connect = useCallback(() => {
    if (!mountedRef.current || !enabled) return;

    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!mountedRef.current) return;
        setConnected(true);
        setReconnectCount((c) => c + 1);
        delayRef.current = INITIAL_DELAY; // reset back-off on successful connect
      };

      ws.onmessage = (event) => {
        try {
          const msg: WsMessage = JSON.parse(event.data as string);
          if (msg.type !== "ping") {
            onMessageRef.current(msg);
          }
        } catch {
          // Ignore unparseable messages
        }
      };

      ws.onclose = () => {
        if (!mountedRef.current) return;
        setConnected(false);
        // Schedule reconnect with exponential back-off
        timerRef.current = setTimeout(() => {
          delayRef.current = Math.min(delayRef.current * 2, MAX_DELAY);
          connect();
        }, delayRef.current);
      };

      ws.onerror = () => {
        ws.close();
      };
    } catch {
      timerRef.current = setTimeout(connect, delayRef.current);
      delayRef.current = Math.min(delayRef.current * 2, MAX_DELAY);
    }
  }, [url, enabled]);

  useEffect(() => {
    mountedRef.current = true;
    if (enabled) {
      connect();
    }
    return () => {
      mountedRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
      wsRef.current?.close();
    };
  }, [connect, enabled]);

  return { connected, reconnectCount };
}
