/**
 * TerminalTab — a VS Code-style interactive shell terminal.
 *
 * xterm.js renders the shell; a WebSocket to /api/debug/terminal/ws bridges
 * input/output with a real subprocess on the backend (PTY on POSIX, pipes on
 * Windows). The backend restarts during dev (uvicorn --reload), so if the
 * socket drops without an explicit exit frame we auto-reconnect and spawn a
 * fresh shell, keeping the tab alive.
 */
import { useEffect, useRef } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import { useLayoutTokens } from './tokens';

interface TerminalTabProps {
  terminalId: string;
  isActive: boolean;
  /** Called once when the backend reports which shell is running (tab title). */
  onReady?: (shellName: string) => void;
}

const MAX_RECONNECTS = 3;

export default function TerminalTab({ terminalId, isActive, onReady }: TerminalTabProps) {
  const t = useLayoutTokens();
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttempts = useRef(0);
  const exitedRef = useRef(false);
  const onReadyRef = useRef(onReady);
  onReadyRef.current = onReady;

  // ── Create the xterm instance once ───────────────────────────
  useEffect(() => {
    const term = new Terminal({
      cursorBlink: true,
      fontSize: 12,
      fontFamily: '"SF Mono", "Fira Code", Menlo, monospace',
      scrollback: 5000,
      theme: {
        background: t.bgContent,
        foreground: '#d4d4d4',
        cursor: t.accent,
        cursorAccent: '#000000',
        selectionBackground: 'rgba(255,255,255,0.25)',
        black: '#000000',
        red: '#f14c4c',
        green: '#23d18b',
        yellow: '#f5f543',
        blue: '#3b8eea',
        magenta: '#d670d6',
        cyan: '#29b8db',
        white: '#e5e5e5',
        brightBlack: '#5c6370',
        brightRed: '#ff6b6b',
        brightGreen: '#5cf09b',
        brightYellow: '#ffe08a',
        brightBlue: '#74b9ff',
        brightMagenta: '#f78fe0',
        brightCyan: '#66e0ff',
        brightWhite: '#ffffff',
      },
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(containerRef.current!);
    termRef.current = term;
    fitRef.current = fit;

    // Forward keystrokes to the backend shell
    term.onData(data => {
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN && !exitedRef.current) {
        ws.send(JSON.stringify({ type: 'input', data }));
      }
    });

    // Keep the PTY window size in sync with the xterm viewport
    term.onResize(({ cols, rows }) => {
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'resize', cols, rows }));
      }
    });

    return () => {
      term.dispose();
      termRef.current = null;
      fitRef.current = null;
      wsRef.current?.close();
      wsRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Fit when this tab becomes visible again ──────────────────
  useEffect(() => {
    if (!isActive || !fitRef.current) return;
    const raf = requestAnimationFrame(() => {
      try {
        fitRef.current!.fit();
      } catch {
        // Container may still be zero-sized; ignore
      }
    });
    return () => cancelAnimationFrame(raf);
  }, [isActive]);

  // ── Refit whenever the container (panel) resizes ─────────────
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      if (!isActive) return;
      requestAnimationFrame(() => {
        try {
          fitRef.current?.fit();
        } catch {
          // ignore
        }
      });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [isActive]);

  // ── WebSocket bridge ─────────────────────────────────────────
  useEffect(() => {
    let disposed = false;

    const sendResize = () => {
      const fit = fitRef.current;
      const ws = wsRef.current;
      if (!fit || !ws || ws.readyState !== WebSocket.OPEN) return;
      try {
        const dims = fit.proposeDimensions();
        if (dims) ws.send(JSON.stringify({ type: 'resize', cols: dims.cols, rows: dims.rows }));
      } catch {
        // ignore
      }
    };

    const connect = () => {
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const ws = new WebSocket(
        `${proto}//${window.location.host}/api/debug/terminal/ws?terminal_id=${encodeURIComponent(terminalId)}`,
      );
      wsRef.current = ws;

      ws.onopen = () => {
        reconnectAttempts.current = 0;
        sendResize();
      };

      ws.onmessage = ev => {
        let msg: { type?: string; data?: string; name?: string; code?: number; message?: string };
        try {
          msg = JSON.parse(ev.data);
        } catch {
          return;
        }
        const term = termRef.current;
        if (!term) return;
        switch (msg.type) {
          case 'output':
            term.write(msg.data ?? '');
            break;
          case 'ready':
            onReadyRef.current?.(msg.name ?? 'Terminal');
            break;
          case 'error':
            exitedRef.current = true;
            term.write(`\r\n\x1b[31m${msg.message ?? 'shell error'}\x1b[0m\r\n`);
            break;
          case 'exit':
            exitedRef.current = true;
            term.write(`\r\n\x1b[90m[process exited with code ${msg.code ?? '?'}]\x1b[0m\r\n`);
            break;
        }
      };

      ws.onclose = () => {
        if (disposed) return;
        // Backend restart (no exit frame) — reconnect for a fresh shell
        if (!exitedRef.current && reconnectAttempts.current < MAX_RECONNECTS) {
          reconnectAttempts.current += 1;
          setTimeout(connect, 1000);
        } else if (!exitedRef.current) {
          termRef.current?.write('\r\n\x1b[90m[connection lost — reopen the terminal to restart]\x1b[0m\r\n');
          exitedRef.current = true;
        }
      };
    };

    connect();
    return () => {
      disposed = true;
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [terminalId]);

  return (
    <div ref={containerRef} style={{ width: '100%', height: '100%', overflow: 'hidden', padding: '2px 0 0 4px' }}>
      {/* xterm mounts its viewport here */}
    </div>
  );
}
