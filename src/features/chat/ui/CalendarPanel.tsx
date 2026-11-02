import { useState, useEffect, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import {
  CalendarDays, ChevronLeft, ChevronRight, RefreshCw, X, Loader2, AlertCircle, Clock,
} from 'lucide-react';
import apiClient from '../../../lib/api-client';

/**
 * CalendarPanel — a read-only month view over the `.ics` files the agent wrote
 * into its own workspace.
 *
 * It deliberately owns no state beyond "which month / which day is selected":
 * the events live in the workspace files, so this panel re-reads them instead
 * of keeping a second copy. Times are shown exactly as the file states them —
 * when a file carries no TZID (a "floating" time) we say so rather than
 * pretending it is the browser's local time.
 */

interface CalendarEvent {
  title: string;
  start: string;          // ISO 8601; date-only when the event is all-day
  end: string;
  all_day: boolean;
  timezone: string | null;
  location: string;
  description: string;
  file: string;
  modified_at?: string | null;
}

interface CalendarPanelProps {
  sessionId: string | null;
  onClose: () => void;
}

const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日'];

/** Local yyyy-mm-dd key for a date (no UTC shifting). */
const ymd = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

/** "2026-11-03T14:00:00" → "14:00"; all-day → "全天". */
const timeLabel = (event: CalendarEvent) => {
  if (event.all_day) return '全天';
  const match = /T(\d{2}:\d{2})/.exec(event.start);
  return match ? match[1] : '';
};

const dayKey = (event: CalendarEvent) => (event.start || '').slice(0, 10);

/** Six weeks of cells (Mon-first) covering the given month. */
function monthMatrix(year: number, month: number): Date[] {
  const first = new Date(year, month, 1);
  const offset = (first.getDay() + 6) % 7; // Sunday=0 → Monday=0
  const start = new Date(year, month, 1 - offset);
  return Array.from({ length: 42 }, (_, i) =>
    new Date(start.getFullYear(), start.getMonth(), start.getDate() + i),
  );
}

export default function CalendarPanel({ sessionId, onClose }: CalendarPanelProps) {
  const { t: tr } = useTranslation('chat');
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [unparsed, setUnparsed] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cursor, setCursor] = useState(() => new Date());
  const [selectedDay, setSelectedDay] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!sessionId) {
      setEvents([]);
      setUnparsed([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await apiClient.get(`/api/chat/${sessionId}/calendar`);
      const list: CalendarEvent[] = Array.isArray(response.data?.events) ? response.data.events : [];
      setEvents(list);
      setUnparsed(Array.isArray(response.data?.unparsed_files) ? response.data.unparsed_files : []);
      // Jump to the month of the next upcoming event, so the panel opens on
      // something instead of an empty current month.
      if (list.length > 0) {
        const today = ymd(new Date());
        const upcoming = list.find(e => dayKey(e) >= today) || list[list.length - 1];
        const [y, m] = dayKey(upcoming).split('-').map(Number);
        if (y && m) setCursor(new Date(y, m - 1, 1));
      }
    } catch (err) {
      console.error(tr('cal_load_failed') + '', err);
      setError('读取日程文件失败');
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    load();
  }, [load]);

  const byDay = useMemo(() => {
    const map = new Map<string, CalendarEvent[]>();
    for (const event of events) {
      const key = dayKey(event);
      if (!key) continue;
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(event);
    }
    return map;
  }, [events]);

  const cells = useMemo(() => monthMatrix(cursor.getFullYear(), cursor.getMonth()), [cursor]);
  const todayKey = ymd(new Date());
  const selected = selectedDay ? (byDay.get(selectedDay) || []) : [];
  const floatingCount = events.filter(e => !e.timezone).length;

  const shiftMonth = (delta: number) =>
    setCursor(prev => new Date(prev.getFullYear(), prev.getMonth() + delta, 1));

  return (
    <div className="h-full flex flex-col overflow-hidden" style={{ color: 'var(--color-text-primary)' }}>
      {/* ── header ─────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-3 py-2 border-b" style={{ borderColor: 'var(--color-border-dark)' }}>
        <span className="text-xs font-semibold flex items-center gap-1.5">
          <CalendarDays className="w-3.5 h-3.5" style={{ color: 'var(--color-primary)' }} />
          {tr('cal_title')}
          <span className="font-normal" style={{ color: 'var(--color-text-muted)' }}>
            {cursor.getFullYear()} 年 {cursor.getMonth() + 1} 月
          </span>
        </span>
        <div className="flex items-center gap-1">
          <button onClick={() => shiftMonth(-1)} className="p-1 rounded" title="上一月">
            <ChevronLeft className="w-3.5 h-3.5" style={{ color: 'var(--color-text-muted)' }} />
          </button>
          <button
            onClick={() => { setCursor(new Date()); setSelectedDay(todayKey); }}
            className="px-1.5 py-0.5 rounded text-[10px]"
            style={{ color: 'var(--color-text-muted)' }}
            title="回到本月"
          >
            今天
          </button>
          <button onClick={() => shiftMonth(1)} className="p-1 rounded" title="下一月">
            <ChevronRight className="w-3.5 h-3.5" style={{ color: 'var(--color-text-muted)' }} />
          </button>
          <button onClick={load} className="p-1 rounded" title="刷新">
            {loading
              ? <Loader2 className="w-3.5 h-3.5 animate-spin" style={{ color: 'var(--color-primary)' }} />
              : <RefreshCw className="w-3.5 h-3.5" style={{ color: 'var(--color-text-muted)' }} />}
          </button>
          <button onClick={onClose} className="p-1 rounded" title="关闭">
            <X className="w-3.5 h-3.5" style={{ color: 'var(--color-text-muted)' }} />
          </button>
        </div>
      </div>

      {/* ── month grid ─────────────────────────────────────────── */}
      <div className="px-2 pt-2">
        <div className="grid grid-cols-7 gap-px text-[10px] mb-1" style={{ color: 'var(--color-text-muted)' }}>
          {WEEKDAYS.map(d => (
            <div key={d} className="text-center py-0.5">{d}</div>
          ))}
        </div>
        <div className="grid grid-cols-7 gap-px">
          {cells.map(cell => {
            const key = ymd(cell);
            const dayEvents = byDay.get(key) || [];
            const inMonth = cell.getMonth() === cursor.getMonth();
            const isToday = key === todayKey;
            const isSelected = key === selectedDay;
            return (
              <button
                key={key}
                onClick={() => setSelectedDay(dayEvents.length ? key : (isSelected ? null : key))}
                className="text-left rounded px-1 py-0.5 min-h-[46px] align-top transition-colors"
                style={{
                  background: isSelected ? 'var(--color-input-background)' : 'transparent',
                  border: `1px solid ${isToday ? 'var(--color-primary)' : 'transparent'}`,
                  opacity: inMonth ? 1 : 0.35,
                }}
                title={dayEvents.map(e => `${timeLabel(e)} ${e.title}`).join('\n') || undefined}
              >
                <div
                  className="text-[10px] font-medium"
                  style={{ color: isToday ? 'var(--color-primary)' : 'var(--color-text-muted)' }}
                >
                  {cell.getDate()}
                </div>
                {dayEvents.slice(0, 2).map((event, i) => (
                  <div
                    key={`${event.file}-${i}`}
                    className="truncate text-[9px] leading-tight rounded px-0.5 mt-0.5"
                    style={{ background: 'rgba(0,109,221,0.18)', color: 'var(--color-text-primary)' }}
                  >
                    {timeLabel(event)} {event.title}
                  </div>
                ))}
                {dayEvents.length > 2 && (
                  <div className="text-[9px] mt-0.5" style={{ color: 'var(--color-text-muted)' }}>
                    +{dayEvents.length - 2}
                  </div>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* ── selected day / all events ─────────────────────────── */}
      <div className="flex-1 overflow-auto px-2 py-2 border-t mt-2" style={{ borderColor: 'var(--color-border-dark)' }}>
        {error && (
          <div className="flex items-center gap-1.5 text-[11px]" style={{ color: '#ef4444' }}>
            <AlertCircle className="w-3 h-3" /> {error}
          </div>
        )}
        {!error && loading && events.length === 0 && (
          <div className="text-[11px] flex items-center gap-1.5" style={{ color: 'var(--color-text-muted)' }}>
            <Loader2 className="w-3 h-3 animate-spin" /> 读取中…
          </div>
        )}
        {!error && !loading && events.length === 0 && (
          <div className="text-[11px] leading-relaxed" style={{ color: 'var(--color-text-muted)' }}>
            这个会话还没有日程。<br />
            让 agent 排一个（它会写一个 <code>.ics</code> 到工作区），再点刷新。
          </div>
        )}
        {selectedDay && selected.length === 0 && (
          <div className="text-[11px]" style={{ color: 'var(--color-text-muted)' }}>
            {selectedDay} 没有日程。
          </div>
        )}
        {(selectedDay ? selected : events).map((event, i) => (
          <div
            key={`${event.file}-${i}`}
            className="rounded px-2 py-1.5 mb-1"
            style={{ background: 'var(--color-input-background)' }}
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-[11px] font-medium truncate">{event.title}</span>
              <span className="text-[10px] flex-shrink-0" style={{ color: 'var(--color-text-muted)' }}>
                <Clock className="w-2.5 h-2.5 inline mr-0.5" />
                {event.all_day ? event.start : `${event.start.slice(0, 10)} ${timeLabel(event)}`}
                {event.end && !event.all_day ? `–${(event.end.slice(11, 16) || '')}` : ''}
              </span>
            </div>
            {event.location && (
              <div className="text-[10px] mt-0.5" style={{ color: 'var(--color-text-muted)' }}>@ {event.location}</div>
            )}
            {event.description && (
              <div className="text-[10px] mt-0.5 whitespace-pre-wrap" style={{ color: 'var(--color-text-muted)' }}>
                {event.description}
              </div>
            )}
            <div className="text-[9px] mt-0.5 truncate" style={{ color: 'var(--color-text-muted)' }}>
              <code>{event.file}</code>
              <span className="ml-1">· {event.timezone || '未写时区'}</span>
            </div>
          </div>
        ))}
      </div>

      {/* ── honesty footer ────────────────────────────────────── */}
      {(floatingCount > 0 || unparsed.length > 0) && (
        <div
          className="px-2 py-1.5 border-t text-[9px] leading-relaxed"
          style={{ borderColor: 'var(--color-border-dark)', color: 'var(--color-text-muted)' }}
        >
          {floatingCount > 0 && <div>{floatingCount} 个日程的文件没写时区，时间按文件字面显示。</div>}
          {unparsed.length > 0 && (
            <div title={unparsed.join('\n')}>
              {unparsed.length} 个 .ics 读不出日程：<code>{unparsed.slice(0, 3).join(', ')}</code>
              {unparsed.length > 3 ? ' …' : ''}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
