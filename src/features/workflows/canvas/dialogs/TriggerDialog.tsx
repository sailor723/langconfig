/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { memo, useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import {
  X, Webhook, FolderSearch, Check, AlertCircle, Loader2,
  Play, History, Trash2, Copy, RefreshCw, Eye, EyeOff
} from 'lucide-react';
import apiClient from '@/lib/api-client';
import type { WorkflowTrigger, TriggerType, TriggerLog } from '@/types/workflow';

interface TriggerDialogProps {
  isOpen: boolean;
  onClose: () => void;
  workflowId: number;
  existingTrigger?: WorkflowTrigger | null;
  onSaved: () => void;
}

// Module-level lists: labels and descriptions are built by functions of the
// translator, because a constant cannot call a hook.
const triggerTypes = (tr: (k: string) => string): { value: TriggerType; label: string; icon: typeof Webhook; description: string }[] => [
  {
    value: 'webhook',
    label: tr('tr_webhook'),
    icon: Webhook,
    description: tr('tr_webhook_desc'),
  },
  {
    value: 'file_watch',
    label: tr('tr_file_watch'),
    icon: FolderSearch,
    description: tr('tr_file_watch_desc'),
  },
];

const fileEvents = (tr: (k: string) => string) => [
  { value: 'created', label: tr('tr_file_created') },
  { value: 'modified', label: tr('tr_file_modified') },
  { value: 'deleted', label: tr('tr_file_deleted') },
  { value: 'moved', label: tr('tr_file_moved') },
];

/**
 * Dialog for creating or editing workflow triggers
 */
const TriggerDialog = memo(function TriggerDialog({
  isOpen,
  onClose,
  workflowId,
  existingTrigger,
  onSaved,
}: TriggerDialogProps) {
  const { t: tr } = useTranslation('chat');
  const [triggerType, setTriggerType] = useState<TriggerType>('webhook');
  const [name, setName] = useState('');
  const [enabled, setEnabled] = useState(true);

  // Webhook config
  const [requireSignature, setRequireSignature] = useState(false);
  const [allowedIps, setAllowedIps] = useState('');
  const [showSecret, setShowSecret] = useState(false);

  // File watch config
  const [watchPath, setWatchPath] = useState('');
  const [patterns, setPatterns] = useState('*');
  const [recursive, setRecursive] = useState(false);
  const [events, setEvents] = useState<string[]>(['created']);
  const [debounceSeconds, setDebounceSeconds] = useState(5);

  // State
  const [pathValidation, setPathValidation] = useState<{ valid: boolean; error?: string } | null>(null);
  const [validatingPath, setValidatingPath] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // History
  const [showHistory, setShowHistory] = useState(false);
  const [history, setHistory] = useState<TriggerLog[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);

  const isEditing = !!existingTrigger;

  // Initialize form
  useEffect(() => {
    if (existingTrigger) {
      setTriggerType(existingTrigger.trigger_type);
      setName(existingTrigger.name || '');
      setEnabled(existingTrigger.enabled);

      const config = existingTrigger.config || {};

      if (existingTrigger.trigger_type === 'webhook') {
        setRequireSignature(config.require_signature as boolean || false);
        setAllowedIps((config.allowed_ips as string[] || []).join(', '));
      } else if (existingTrigger.trigger_type === 'file_watch') {
        setWatchPath(config.watch_path as string || '');
        setPatterns((config.patterns as string[] || ['*']).join(', '));
        setRecursive(config.recursive as boolean || false);
        setEvents(config.events as string[] || ['created']);
        setDebounceSeconds(config.debounce_seconds as number || 5);
      }
    } else {
      // Reset to defaults
      setTriggerType('webhook');
      setName('');
      setEnabled(true);
      setRequireSignature(false);
      setAllowedIps('');
      setWatchPath('');
      setPatterns('*');
      setRecursive(false);
      setEvents(['created']);
      setDebounceSeconds(5);
    }
    setPathValidation(null);
    setError(null);
  }, [existingTrigger, isOpen]);

  // Validate file watch path
  const validatePath = useCallback(async (path: string) => {
    if (!path.trim()) {
      setPathValidation(null);
      return;
    }

    setValidatingPath(true);
    try {
      const response = await apiClient.validateWatchPath(path);
      setPathValidation(response.data);
    } catch (err: any) {
      setPathValidation({
        valid: false,
        error: err?.response?.data?.detail || tr('sch_validation_failed')
      });
    } finally {
      setValidatingPath(false);
    }
  }, []);

  // Debounced path validation
  useEffect(() => {
    if (triggerType !== 'file_watch') return;

    const timer = setTimeout(() => {
      validatePath(watchPath);
    }, 500);

    return () => clearTimeout(timer);
  }, [watchPath, triggerType, validatePath]);

  // Load history
  const loadHistory = useCallback(async () => {
    if (!existingTrigger) return;

    setLoadingHistory(true);
    try {
      const response = await apiClient.getTriggerHistory(existingTrigger.id, { limit: 20 });
      setHistory(response.data.logs || []);
    } catch (err) {
      console.error(tr('sch_load_history_failed'), err);
    } finally {
      setLoadingHistory(false);
    }
  }, [existingTrigger]);

  useEffect(() => {
    if (showHistory && existingTrigger) {
      loadHistory();
    }
  }, [showHistory, existingTrigger, loadHistory]);

  const handleEventToggle = (event: string) => {
    setEvents(prev =>
      prev.includes(event)
        ? prev.filter(e => e !== event)
        : [...prev, event]
    );
  };

  const buildConfig = () => {
    if (triggerType === 'webhook') {
      return {
        require_signature: requireSignature,
        allowed_ips: allowedIps.split(',').map(ip => ip.trim()).filter(Boolean),
      };
    } else {
      return {
        watch_path: watchPath,
        patterns: patterns.split(',').map(p => p.trim()).filter(Boolean),
        recursive,
        events,
        debounce_seconds: debounceSeconds,
      };
    }
  };

  const handleSave = async () => {
    setError(null);
    setSaving(true);

    try {
      if (triggerType === 'file_watch' && !watchPath.trim()) {
        setError(tr('tr_watch_required'));
        setSaving(false);
        return;
      }

      const triggerData = {
        workflow_id: workflowId,
        trigger_type: triggerType,
        name: name.trim() || undefined,
        enabled,
        config: buildConfig(),
      };

      if (isEditing && existingTrigger) {
        await apiClient.updateTrigger(existingTrigger.id, triggerData);
      } else {
        await apiClient.createTrigger(triggerData);
      }

      onSaved();
      onClose();
    } catch (err: any) {
      setError(err?.response?.data?.detail || tr('tr_save_failed'));
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    if (!existingTrigger) return;

    try {
      await apiClient.testTrigger(existingTrigger.id, {});
      loadHistory();
    } catch (err: any) {
      setError(err?.response?.data?.detail || tr('tr_test_failed'));
    }
  };

  const handleDelete = async () => {
    if (!existingTrigger) return;
    if (!window.confirm(tr('tr_confirm_delete'))) return;

    try {
      await apiClient.deleteTrigger(existingTrigger.id);
      onSaved();
      onClose();
    } catch (err: any) {
      setError(err?.response?.data?.detail || tr('tr_delete_failed'));
    }
  };

  const handleRegenerateSecret = async () => {
    if (!existingTrigger) return;
    if (!window.confirm(tr('tr_regen_confirm'))) return;

    try {
      await apiClient.regenerateWebhookSecret(existingTrigger.id);
      onSaved();
    } catch (err: any) {
      setError(err?.response?.data?.detail || tr('tr_regen_failed'));
    }
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
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
            {triggerType === 'webhook' ? (
              <Webhook size={20} style={{ color: 'var(--color-primary)' }} />
            ) : (
              <FolderSearch size={20} style={{ color: 'var(--color-primary)' }} />
            )}
            <h3 className="text-lg font-semibold" style={{ color: 'var(--color-text-primary)' }}>
              {isEditing ? tr('tr_edit') : tr('tr_create')}
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
          {/* Trigger Type (only for new triggers) */}
          {!isEditing && (
            <div>
              <label className="text-sm font-medium block mb-2" style={{ color: 'var(--color-text-primary)' }}>
                {tr('tr_type')}
              </label>
              <div className="grid grid-cols-2 gap-2">
                {triggerTypes(tr).map(type => {
                  const Icon = type.icon;
                  return (
                    <button
                      key={type.value}
                      onClick={() => setTriggerType(type.value)}
                      className={`p-3 rounded-lg text-left transition-colors ${
                        triggerType === type.value
                          ? 'bg-primary/20 border-primary'
                          : 'hover:bg-white/5'
                      }`}
                      style={{
                        border: `1px solid ${triggerType === type.value ? 'var(--color-primary)' : 'var(--color-border-dark)'}`,
                      }}
                    >
                      <div className="flex items-center gap-2">
                        <Icon size={16} style={{ color: triggerType === type.value ? 'var(--color-primary)' : 'var(--color-text-muted)' }} />
                        <span className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                          {type.label}
                        </span>
                      </div>
                      <p className="text-xs mt-1" style={{ color: 'var(--color-text-muted)' }}>
                        {type.description}
                      </p>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Name */}
          <div>
            <label className="text-sm font-medium block mb-1" style={{ color: 'var(--color-text-primary)' }}>
              {tr('tr_name')}
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., GitHub Push Webhook"
              className="w-full px-3 py-2 rounded-lg text-sm"
              style={{
                backgroundColor: 'var(--color-background-dark)',
                border: '1px solid var(--color-border-dark)',
                color: 'var(--color-text-primary)',
              }}
            />
          </div>

          {/* Webhook Config */}
          {triggerType === 'webhook' && (
            <>
              {/* Webhook URL (read-only for existing) */}
              {isEditing && existingTrigger?.webhook_url && (
                <div>
                  <label className="text-sm font-medium block mb-1" style={{ color: 'var(--color-text-primary)' }}>
                    {tr('tr_url')}
                  </label>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={existingTrigger.webhook_url}
                      readOnly
                      className="flex-1 px-3 py-2 rounded-lg text-sm font-mono"
                      style={{
                        backgroundColor: 'var(--color-background-dark)',
                        border: '1px solid var(--color-border-dark)',
                        color: 'var(--color-text-secondary)',
                      }}
                    />
                    <button
                      onClick={() => copyToClipboard(existingTrigger.webhook_url!)}
                      className="px-3 py-2 rounded-lg hover:bg-white/10"
                      style={{ border: '1px solid var(--color-border-dark)' }}
                      title={tr('tr_copy_url')}
                    >
                      <Copy size={16} style={{ color: 'var(--color-text-muted)' }} />
                    </button>
                  </div>
                </div>
              )}

              {/* Webhook Secret (read-only for existing) */}
              {isEditing && existingTrigger?.webhook_secret && (
                <div>
                  <label className="text-sm font-medium block mb-1" style={{ color: 'var(--color-text-primary)' }}>
                    {tr('tr_secret')}
                  </label>
                  <div className="flex gap-2">
                    <input
                      type={showSecret ? 'text' : 'password'}
                      value={existingTrigger.webhook_secret}
                      readOnly
                      className="flex-1 px-3 py-2 rounded-lg text-sm font-mono"
                      style={{
                        backgroundColor: 'var(--color-background-dark)',
                        border: '1px solid var(--color-border-dark)',
                        color: 'var(--color-text-secondary)',
                      }}
                    />
                    <button
                      onClick={() => setShowSecret(!showSecret)}
                      className="px-3 py-2 rounded-lg hover:bg-white/10"
                      style={{ border: '1px solid var(--color-border-dark)' }}
                      title={showSecret ? tr('pc_hide') : tr('pc_show')}
                    >
                      {showSecret ? (
                        <EyeOff size={16} style={{ color: 'var(--color-text-muted)' }} />
                      ) : (
                        <Eye size={16} style={{ color: 'var(--color-text-muted)' }} />
                      )}
                    </button>
                    <button
                      onClick={() => copyToClipboard(existingTrigger.webhook_secret!)}
                      className="px-3 py-2 rounded-lg hover:bg-white/10"
                      style={{ border: '1px solid var(--color-border-dark)' }}
                      title={tr('tr_copy_secret')}
                    >
                      <Copy size={16} style={{ color: 'var(--color-text-muted)' }} />
                    </button>
                    <button
                      onClick={handleRegenerateSecret}
                      className="px-3 py-2 rounded-lg hover:bg-white/10"
                      style={{ border: '1px solid var(--color-border-dark)' }}
                      title="Regenerate"
                    >
                      <RefreshCw size={16} style={{ color: 'var(--color-text-muted)' }} />
                    </button>
                  </div>
                </div>
              )}

              {/* Require Signature */}
              <div className="flex items-center justify-between">
                <div>
                  <label className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                    {tr('tr_require_sig')}
                  </label>
                  <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                    Verify HMAC-SHA256 signature in X-Webhook-Signature header
                  </p>
                </div>
                <div
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors cursor-pointer ${
                    requireSignature ? 'bg-primary' : 'bg-gray-600'
                  }`}
                  onClick={() => setRequireSignature(!requireSignature)}
                >
                  <span
                    className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                      requireSignature ? 'translate-x-6' : 'translate-x-1'
                    }`}
                  />
                </div>
              </div>

              {/* Allowed IPs */}
              <div>
                <label className="text-sm font-medium block mb-1" style={{ color: 'var(--color-text-primary)' }}>
                  {tr('tr_allowed_ips')}
                </label>
                <input
                  type="text"
                  value={allowedIps}
                  onChange={(e) => setAllowedIps(e.target.value)}
                  placeholder="e.g., 192.168.1.0/24, 10.0.0.1"
                  className="w-full px-3 py-2 rounded-lg text-sm font-mono"
                  style={{
                    backgroundColor: 'var(--color-background-dark)',
                    border: '1px solid var(--color-border-dark)',
                    color: 'var(--color-text-primary)',
                  }}
                />
                <p className="text-xs mt-1" style={{ color: 'var(--color-text-muted)' }}>
                  tr('tr_allowed_ips_hint')
                </p>
              </div>
            </>
          )}

          {/* File Watch Config */}
          {triggerType === 'file_watch' && (
            <>
              {/* Watch Path */}
              <div>
                <label className="text-sm font-medium block mb-1" style={{ color: 'var(--color-text-primary)' }}>
                  {tr('tr_watch_dir')}
                </label>
                <input
                  type="text"
                  value={watchPath}
                  onChange={(e) => setWatchPath(e.target.value)}
                  placeholder="e.g., C:\Users\Cade\Downloads"
                  className="w-full px-3 py-2 rounded-lg text-sm font-mono"
                  style={{
                    backgroundColor: 'var(--color-background-dark)',
                    border: '1px solid var(--color-border-dark)',
                    color: 'var(--color-text-primary)',
                  }}
                />
                {/* Validation */}
                {watchPath.trim() && (
                  <div className="mt-1 flex items-center gap-1">
                    {validatingPath ? (
                      <Loader2 size={12} className="animate-spin" style={{ color: 'var(--color-text-muted)' }} />
                    ) : pathValidation?.valid ? (
                      <Check size={12} style={{ color: '#22c55e' }} />
                    ) : pathValidation?.error ? (
                      <AlertCircle size={12} style={{ color: '#ef4444' }} />
                    ) : null}
                    <span className="text-xs" style={{ color: pathValidation?.valid ? '#22c55e' : pathValidation?.error ? '#ef4444' : 'var(--color-text-muted)' }}>
                      {validatingPath ? 'Validating...' : pathValidation?.error || (pathValidation?.valid ? 'Valid path' : '')}
                    </span>
                  </div>
                )}
              </div>

              {/* File Patterns */}
              <div>
                <label className="text-sm font-medium block mb-1" style={{ color: 'var(--color-text-primary)' }}>
                  {tr('tr_patterns')}
                </label>
                <input
                  type="text"
                  value={patterns}
                  onChange={(e) => setPatterns(e.target.value)}
                  placeholder="e.g., *.pdf, *.docx, report_*.xlsx"
                  className="w-full px-3 py-2 rounded-lg text-sm font-mono"
                  style={{
                    backgroundColor: 'var(--color-background-dark)',
                    border: '1px solid var(--color-border-dark)',
                    color: 'var(--color-text-primary)',
                  }}
                />
                <p className="text-xs mt-1" style={{ color: 'var(--color-text-muted)' }}>
                  Comma-separated glob patterns. Use * to match all files.
                </p>
              </div>

              {/* Events */}
              <div>
                <label className="text-sm font-medium block mb-2" style={{ color: 'var(--color-text-primary)' }}>
                  {tr('tr_trigger_on')}
                </label>
                <div className="flex flex-wrap gap-2">
                  {fileEvents(tr).map(event => (
                    <button
                      key={event.value}
                      onClick={() => handleEventToggle(event.value)}
                      className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${
                        events.includes(event.value)
                          ? 'bg-primary text-white'
                          : 'hover:bg-white/10'
                      }`}
                      style={{
                        border: '1px solid var(--color-border-dark)',
                        backgroundColor: events.includes(event.value) ? undefined : 'var(--color-background-dark)',
                        color: events.includes(event.value) ? undefined : 'var(--color-text-muted)',
                      }}
                    >
                      {event.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Recursive */}
              <div className="flex items-center justify-between">
                <div>
                  <label className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                    {tr('tr_watch_subdirs')}
                  </label>
                  <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                    tr('tr_watch_subdirs_hint')
                  </p>
                </div>
                <div
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors cursor-pointer ${
                    recursive ? 'bg-primary' : 'bg-gray-600'
                  }`}
                  onClick={() => setRecursive(!recursive)}
                >
                  <span
                    className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                      recursive ? 'translate-x-6' : 'translate-x-1'
                    }`}
                  />
                </div>
              </div>

              {/* Debounce */}
              <div>
                <label className="text-sm font-medium block mb-1" style={{ color: 'var(--color-text-primary)' }}>
                  {tr('tr_debounce')}
                </label>
                <input
                  type="number"
                  min={1}
                  max={300}
                  value={debounceSeconds}
                  onChange={(e) => setDebounceSeconds(parseInt(e.target.value) || 5)}
                  className="w-24 px-3 py-2 rounded-lg text-sm"
                  style={{
                    backgroundColor: 'var(--color-background-dark)',
                    border: '1px solid var(--color-border-dark)',
                    color: 'var(--color-text-primary)',
                  }}
                />
                <p className="text-xs mt-1" style={{ color: 'var(--color-text-muted)' }}>
                  tr('tr_debounce_hint')
                </p>
              </div>
            </>
          )}

          {/* Enabled Toggle */}
          <div className="flex items-center justify-between">
            <label className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
              Enabled
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

          {/* Error */}
          {error && (
            <div className="p-3 rounded-lg" style={{ backgroundColor: 'rgba(239, 68, 68, 0.15)' }}>
              <p className="text-sm" style={{ color: '#ef4444' }}>{error}</p>
            </div>
          )}

          {/* History (edit mode) */}
          {isEditing && (
            <div>
              <button
                onClick={() => setShowHistory(!showHistory)}
                className="flex items-center gap-2 text-sm font-medium"
                style={{ color: 'var(--color-text-primary)' }}
              >
                <History size={16} />
                {showHistory ? tr('pc_hide') : tr('pc_show')} Trigger History
              </button>
              {showHistory && (
                <div className="mt-3 space-y-2">
                  {loadingHistory ? (
                    <div className="flex items-center gap-2">
                      <Loader2 size={14} className="animate-spin" />
                      <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Loading...</span>
                    </div>
                  ) : history.length === 0 ? (
                    <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>{tr('tr_no_triggers')}</p>
                  ) : (
                    <div className="max-h-40 overflow-y-auto space-y-1">
                      {history.map(log => (
                        <div
                          key={log.id}
                          className="flex items-center justify-between p-2 rounded text-xs"
                          style={{
                            backgroundColor: 'var(--color-background-dark)',
                            border: '1px solid var(--color-border-dark)',
                          }}
                        >
                          <div>
                            <span style={{ color: 'var(--color-text-secondary)' }}>
                              {new Date(log.triggered_at).toLocaleString()}
                            </span>
                            {log.trigger_source && (
                              <span className="ml-2" style={{ color: 'var(--color-text-muted)' }}>
                                from {log.trigger_source}
                              </span>
                            )}
                          </div>
                          <span
                            className={`px-2 py-0.5 rounded ${
                              log.status === 'SUCCESS' ? 'bg-green-500/20 text-green-400' :
                              log.status === 'FAILED' ? 'bg-red-500/20 text-red-400' :
                              log.status === 'RUNNING' ? 'bg-blue-500/20 text-blue-400' :
                              'bg-gray-500/20 text-gray-400'
                            }`}
                          >
                            {log.status}
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
                  onClick={handleTest}
                  className="px-3 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2 hover:bg-white/10"
                  style={{ border: '1px solid var(--color-border-dark)', color: 'var(--color-text-primary)' }}
                >
                  <Play size={14} />
                  {tr('tr_test')}
                </button>
                <button
                  onClick={handleDelete}
                  className="px-3 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2 hover:bg-red-500/20"
                  style={{ color: '#ef4444' }}
                >
                  <Trash2 size={14} />
                  Delete
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
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saving || (triggerType === 'file_watch' && (!pathValidation?.valid || !watchPath.trim()))}
              className="px-4 py-2 rounded-lg text-sm font-medium transition-colors bg-primary text-white hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            >
              {saving && <Loader2 size={14} className="animate-spin" />}
              {isEditing ? tr('tr_save_changes') : tr('tr_create')}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
});

export default TriggerDialog;
