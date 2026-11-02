/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { memo, useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { X, Clock, Check, AlertCircle, Loader2, Play, History, Trash2 } from 'lucide-react';
import apiClient from '@/lib/api-client';
import type { WorkflowSchedule, CronValidationResult, ScheduledRunLog } from '@/types/workflow';

interface ScheduleDialogProps {
  isOpen: boolean;
  onClose: () => void;
  workflowId: number;
  existingSchedule?: WorkflowSchedule | null;
  onSaved: () => void;
}

// Module-level list: labels are built by a function so they can be translated.
const cronPresets = (tr: (k: string) => string) => [
  { label: tr('sch_every_minute'), value: '* * * * *' },
  { label: tr('sch_every_5'), value: '*/5 * * * *' },
  { label: tr('sch_every_15'), value: '*/15 * * * *' },
  { label: tr('sch_every_hour'), value: '0 * * * *' },
  { label: tr('sch_every_6h'), value: '0 */6 * * *' },
  { label: tr('sch_daily_9am'), value: '0 9 * * *' },
  { label: tr('sch_daily_midnight'), value: '0 0 * * *' },
  { label: tr('sch_weekly_sunday'), value: '0 0 * * 0' },
  { label: tr('sch_monthly'), value: '0 0 1 * *' },
];

const TIMEZONES = [
  'UTC',
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'Europe/London',
  'Europe/Paris',
  'Europe/Berlin',
  'Asia/Tokyo',
  'Asia/Shanghai',
  'Australia/Sydney',
];

/**
 * Dialog for creating or editing a workflow schedule
 */
const ScheduleDialog = memo(function ScheduleDialog({
  isOpen,
  onClose,
  workflowId,
  existingSchedule,
  onSaved,
}: ScheduleDialogProps) {
  const { t: tr } = useTranslation('chat');
  const [name, setName] = useState('');
  const [cronExpression, setCronExpression] = useState('0 9 * * *');
  const [timezone, setTimezone] = useState('UTC');
  const [enabled, setEnabled] = useState(true);
  const [maxConcurrentRuns, setMaxConcurrentRuns] = useState(1);
  const [timeoutMinutes, setTimeoutMinutes] = useState(60);
  const [idempotencyKeyTemplate, setIdempotencyKeyTemplate] = useState('');
  const [defaultInputData, setDefaultInputData] = useState('{}');

  const [validation, setValidation] = useState<CronValidationResult | null>(null);
  const [validating, setValidating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [showHistory, setShowHistory] = useState(false);
  const [history, setHistory] = useState<ScheduledRunLog[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);

  const isEditing = !!existingSchedule;

  // Initialize form with existing schedule data
  useEffect(() => {
    if (existingSchedule) {
      setName(existingSchedule.name || '');
      setCronExpression(existingSchedule.cron_expression);
      setTimezone(existingSchedule.timezone);
      setEnabled(existingSchedule.enabled);
      setMaxConcurrentRuns(existingSchedule.max_concurrent_runs);
      setTimeoutMinutes(existingSchedule.timeout_minutes);
      setIdempotencyKeyTemplate(existingSchedule.idempotency_key_template || '');
      setDefaultInputData(JSON.stringify(existingSchedule.default_input_data || {}, null, 2));
    } else {
      // Reset to defaults for new schedule
      setName('');
      setCronExpression('0 9 * * *');
      setTimezone('UTC');
      setEnabled(true);
      setMaxConcurrentRuns(1);
      setTimeoutMinutes(60);
      setIdempotencyKeyTemplate('');
      setDefaultInputData('{}');
    }
    setValidation(null);
    setError(null);
  }, [existingSchedule, isOpen]);

  // Validate cron expression
  const validateCron = useCallback(async (cron: string, tz: string) => {
    if (!cron.trim()) {
      setValidation(null);
      return;
    }

    setValidating(true);
    try {
      const response = await apiClient.validateCronExpression(cron, tz);
      setValidation(response.data);
    } catch (err: any) {
      setValidation({
        valid: false,
        error: err?.response?.data?.detail || tr('sch_validation_failed'),
        next_runs: [],
      });
    } finally {
      setValidating(false);
    }
  }, []);

  // Debounced validation
  useEffect(() => {
    const timer = setTimeout(() => {
      validateCron(cronExpression, timezone);
    }, 300);

    return () => clearTimeout(timer);
  }, [cronExpression, timezone, validateCron]);

  // Load execution history
  const loadHistory = useCallback(async () => {
    if (!existingSchedule) return;

    setLoadingHistory(true);
    try {
      const response = await apiClient.getScheduleHistory(existingSchedule.id, { limit: 20 });
      setHistory(response.data.runs || []);
    } catch (err) {
      console.error(tr('sch_load_history_failed'), err);
    } finally {
      setLoadingHistory(false);
    }
  }, [existingSchedule]);

  useEffect(() => {
    if (showHistory && existingSchedule) {
      loadHistory();
    }
  }, [showHistory, existingSchedule, loadHistory]);

  const handlePresetSelect = (preset: string) => {
    setCronExpression(preset);
  };

  const handleSave = async () => {
    setError(null);
    setSaving(true);

    try {
      // Validate JSON input
      let parsedInputData = {};
      if (defaultInputData.trim()) {
        try {
          parsedInputData = JSON.parse(defaultInputData);
        } catch {
          setError(tr('sch_invalid_json'));
          setSaving(false);
          return;
        }
      }

      const scheduleData = {
        workflow_id: workflowId,
        name: name.trim() || undefined,
        cron_expression: cronExpression,
        timezone,
        enabled,
        max_concurrent_runs: maxConcurrentRuns,
        timeout_minutes: timeoutMinutes,
        idempotency_key_template: idempotencyKeyTemplate.trim() || undefined,
        default_input_data: parsedInputData,
      };

      if (isEditing && existingSchedule) {
        await apiClient.updateSchedule(existingSchedule.id, scheduleData);
      } else {
        await apiClient.createSchedule(scheduleData);
      }

      onSaved();
      onClose();
    } catch (err: any) {
      setError(err?.response?.data?.detail || tr('sch_save_failed'));
    } finally {
      setSaving(false);
    }
  };

  const handleTriggerNow = async () => {
    if (!existingSchedule) return;

    try {
      await apiClient.triggerScheduleNow(existingSchedule.id);
      // Optionally refresh history
      loadHistory();
    } catch (err: any) {
      setError(err?.response?.data?.detail || tr('sch_trigger_failed'));
    }
  };

  const handleDelete = async () => {
    if (!existingSchedule) return;

    if (!window.confirm(tr('sch_confirm_delete'))) {
      return;
    }

    try {
      await apiClient.deleteSchedule(existingSchedule.id);
      onSaved();
      onClose();
    } catch (err: any) {
      setError(err?.response?.data?.detail || tr('sch_delete_failed'));
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div
        className="w-full max-w-lg rounded-xl shadow-2xl overflow-hidden max-h-[90vh] flex flex-col"
        style={{
          backgroundColor: 'var(--color-panel-dark)',
          border: '1px solid var(--color-border-dark)',
        }}
      >
        {/* Header */}
        <div
          className="px-6 py-4 border-b flex justify-between items-center shrink-0"
          style={{ borderColor: 'var(--color-border-dark)' }}
        >
          <div className="flex items-center gap-2">
            <Clock size={20} style={{ color: 'var(--color-primary)' }} />
            <h3 className="text-lg font-semibold" style={{ color: 'var(--color-text-primary)' }}>
              {isEditing ? tr('sch_edit') : tr('sch_create')}
            </h3>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-white/10 transition-colors"
            style={{ color: 'var(--color-text-muted)' }}
          >
            <X size={20} />
          </button>
        </div>

        {/* Content */}
        <div className="p-6 space-y-5 overflow-y-auto flex-1">
          {/* Schedule Name */}
          <div>
            <label className="text-sm font-medium block mb-1" style={{ color: 'var(--color-text-primary)' }}>
              {tr('sch_name')}
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Daily Report"
              className="w-full px-3 py-2 rounded-lg text-sm"
              style={{
                backgroundColor: 'var(--color-background-dark)',
                border: '1px solid var(--color-border-dark)',
                color: 'var(--color-text-primary)',
              }}
            />
          </div>

          {/* Cron Expression */}
          <div>
            <label className="text-sm font-medium block mb-1" style={{ color: 'var(--color-text-primary)' }}>
              {tr('sch_cron')}
            </label>
            <input
              type="text"
              value={cronExpression}
              onChange={(e) => setCronExpression(e.target.value)}
              placeholder="* * * * *"
              className="w-full px-3 py-2 rounded-lg text-sm font-mono"
              style={{
                backgroundColor: 'var(--color-background-dark)',
                border: '1px solid var(--color-border-dark)',
                color: 'var(--color-text-primary)',
              }}
            />

            {/* Presets */}
            <div className="mt-2 flex flex-wrap gap-1">
              {cronPresets(tr).map((preset) => (
                <button
                  key={preset.value}
                  onClick={() => handlePresetSelect(preset.value)}
                  className={`px-2 py-1 rounded text-xs transition-colors ${
                    cronExpression === preset.value ? 'bg-primary text-white' : 'hover:bg-white/10'
                  }`}
                  style={{
                    backgroundColor: cronExpression === preset.value ? undefined : 'var(--color-background-dark)',
                    border: '1px solid var(--color-border-dark)',
                    color: cronExpression === preset.value ? undefined : 'var(--color-text-muted)',
                  }}
                >
                  {preset.label}
                </button>
              ))}
            </div>

            {/* Validation Status */}
            <div className="mt-2 flex items-start gap-2">
              {validating ? (
                <>
                  <Loader2 size={14} className="animate-spin mt-0.5" style={{ color: 'var(--color-text-muted)' }} />
                  <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                    Validating...
                  </span>
                </>
              ) : validation?.valid ? (
                <div>
                  <div className="flex items-center gap-1">
                    <Check size={14} style={{ color: '#22c55e' }} />
                    <span className="text-xs" style={{ color: '#22c55e' }}>
                      {validation.human_readable || tr('sch_valid')}
                    </span>
                  </div>
                  {validation.next_runs.length > 0 && (
                    <div className="mt-1">
                      <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>{tr('sch_next_runs')}</p>
                      <ul className="text-xs mt-1 space-y-0.5" style={{ color: 'var(--color-text-secondary)' }}>
                        {validation.next_runs.slice(0, 3).map((run, i) => (
                          <li key={i}>{new Date(run).toLocaleString()}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              ) : validation?.error ? (
                <>
                  <AlertCircle size={14} className="mt-0.5" style={{ color: '#ef4444' }} />
                  <span className="text-xs" style={{ color: '#ef4444' }}>
                    {validation.error}
                  </span>
                </>
              ) : null}
            </div>
          </div>

          {/* Timezone */}
          <div>
            <label className="text-sm font-medium block mb-1" style={{ color: 'var(--color-text-primary)' }}>
              {tr('sch_timezone')}
            </label>
            <select
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
              className="w-full px-3 py-2 rounded-lg text-sm"
              style={{
                backgroundColor: 'var(--color-background-dark)',
                border: '1px solid var(--color-border-dark)',
                color: 'var(--color-text-primary)',
              }}
            >
              {TIMEZONES.map((tz) => (
                <option key={tz} value={tz}>
                  {tz}
                </option>
              ))}
            </select>
          </div>

          {/* Enabled Toggle */}
          <div className="flex items-center justify-between">
            <label className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
              {tr('sch_enabled')}
            </label>
            <div
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors cursor-pointer ${
                enabled ? 'bg-primary' : 'bg-gray-600'
              }`}
              onClick={() => setEnabled(!enabled)}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  enabled ? 'translate-x-6' : 'translate-x-1'
                }`}
              />
            </div>
          </div>

          {/* Advanced Settings */}
          <details className="group">
            <summary
              className="text-sm font-medium cursor-pointer"
              style={{ color: 'var(--color-text-primary)' }}
            >
              {tr('sch_advanced')}
            </summary>
            <div className="mt-3 space-y-4 pl-2">
              {/* Max Concurrent Runs */}
              <div>
                <label className="text-xs font-medium block mb-1" style={{ color: 'var(--color-text-muted)' }}>
                  Max Concurrent Runs
                </label>
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={maxConcurrentRuns}
                  onChange={(e) => setMaxConcurrentRuns(parseInt(e.target.value) || 1)}
                  className="w-24 px-3 py-1.5 rounded text-sm"
                  style={{
                    backgroundColor: 'var(--color-background-dark)',
                    border: '1px solid var(--color-border-dark)',
                    color: 'var(--color-text-primary)',
                  }}
                />
              </div>

              {/* Timeout */}
              <div>
                <label className="text-xs font-medium block mb-1" style={{ color: 'var(--color-text-muted)' }}>
                  Timeout (minutes)
                </label>
                <input
                  type="number"
                  min={1}
                  max={1440}
                  value={timeoutMinutes}
                  onChange={(e) => setTimeoutMinutes(parseInt(e.target.value) || 60)}
                  className="w-24 px-3 py-1.5 rounded text-sm"
                  style={{
                    backgroundColor: 'var(--color-background-dark)',
                    border: '1px solid var(--color-border-dark)',
                    color: 'var(--color-text-primary)',
                  }}
                />
              </div>

              {/* Idempotency Key Template */}
              <div>
                <label className="text-xs font-medium block mb-1" style={{ color: 'var(--color-text-muted)' }}>
                  Idempotency Key Template (optional)
                </label>
                <input
                  type="text"
                  value={idempotencyKeyTemplate}
                  onChange={(e) => setIdempotencyKeyTemplate(e.target.value)}
                  placeholder="e.g., report_{date}"
                  className="w-full px-3 py-1.5 rounded text-sm font-mono"
                  style={{
                    backgroundColor: 'var(--color-background-dark)',
                    border: '1px solid var(--color-border-dark)',
                    color: 'var(--color-text-primary)',
                  }}
                />
                <p className="text-xs mt-1" style={{ color: 'var(--color-text-muted)' }}>
                  Placeholders: {'{date}'}, {'{datetime}'}, {'{week}'}, {'{month}'}
                </p>
              </div>

              {/* Default Input Data */}
              <div>
                <label className="text-xs font-medium block mb-1" style={{ color: 'var(--color-text-muted)' }}>
                  Default Input Data (JSON)
                </label>
                <textarea
                  value={defaultInputData}
                  onChange={(e) => setDefaultInputData(e.target.value)}
                  rows={4}
                  className="w-full px-3 py-2 rounded text-sm font-mono"
                  style={{
                    backgroundColor: 'var(--color-background-dark)',
                    border: '1px solid var(--color-border-dark)',
                    color: 'var(--color-text-primary)',
                  }}
                />
              </div>
            </div>
          </details>

          {/* Error Message */}
          {error && (
            <div className="p-3 rounded-lg" style={{ backgroundColor: 'rgba(239, 68, 68, 0.15)' }}>
              <p className="text-sm" style={{ color: '#ef4444' }}>
                {error}
              </p>
            </div>
          )}

          {/* Execution History (Edit mode only) */}
          {isEditing && (
            <div>
              <button
                onClick={() => setShowHistory(!showHistory)}
                className="flex items-center gap-2 text-sm font-medium"
                style={{ color: 'var(--color-text-primary)' }}
              >
                <History size={16} />
                {showHistory ? tr('pc_hide') : tr('pc_show')} Execution History
              </button>
              {showHistory && (
                <div className="mt-3 space-y-2">
                  {loadingHistory ? (
                    <div className="flex items-center gap-2">
                      <Loader2 size={14} className="animate-spin" />
                      <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                        {tr('sch_loading_history')}
                      </span>
                    </div>
                  ) : history.length === 0 ? (
                    <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                      {tr('sch_no_executions')}
                    </p>
                  ) : (
                    <div className="max-h-40 overflow-y-auto space-y-1">
                      {history.map((run) => (
                        <div
                          key={run.id}
                          className="flex items-center justify-between p-2 rounded text-xs"
                          style={{
                            backgroundColor: 'var(--color-background-dark)',
                            border: '1px solid var(--color-border-dark)',
                          }}
                        >
                          <span style={{ color: 'var(--color-text-secondary)' }}>
                            {new Date(run.scheduled_for).toLocaleString()}
                          </span>
                          <span
                            className={`px-2 py-0.5 rounded ${
                              run.status === 'SUCCESS'
                                ? 'bg-green-500/20 text-green-400'
                                : run.status === 'FAILED'
                                ? 'bg-red-500/20 text-red-400'
                                : run.status === 'RUNNING'
                                ? 'bg-blue-500/20 text-blue-400'
                                : 'bg-gray-500/20 text-gray-400'
                            }`}
                          >
                            {run.status}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div
          className="px-6 py-4 border-t flex justify-between items-center shrink-0"
          style={{ borderColor: 'var(--color-border-dark)', backgroundColor: 'var(--color-background-dark)' }}
        >
          <div className="flex gap-2">
            {isEditing && (
              <>
                <button
                  onClick={handleTriggerNow}
                  disabled={!enabled}
                  className="px-3 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2 hover:bg-white/10 disabled:opacity-50"
                  style={{
                    border: '1px solid var(--color-border-dark)',
                    color: 'var(--color-text-primary)',
                  }}
                >
                  <Play size={14} />
                  {tr('sch_run_now')}
                </button>
                <button
                  onClick={handleDelete}
                  className="px-3 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2 hover:bg-red-500/20"
                  style={{
                    color: '#ef4444',
                  }}
                >
                  <Trash2 size={14} />
                  {tr('c_delete')}
                </button>
              </>
            )}
          </div>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-lg text-sm font-medium transition-colors hover:bg-white/10"
              style={{ color: 'var(--color-text-muted)' }}
            >
              {tr('c_cancel')}
            </button>
            <button
              onClick={handleSave}
              disabled={saving || !validation?.valid}
              className="px-4 py-2 rounded-lg text-sm font-medium transition-colors bg-primary text-white hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            >
              {saving && <Loader2 size={14} className="animate-spin" />}
              {isEditing ? tr('sch_save_changes') : tr('sch_create')}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
});

export default ScheduleDialog;
