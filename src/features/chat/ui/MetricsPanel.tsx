/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Activity, Zap, Users, Database, ChevronDown, ChevronRight, DollarSign, FileText, AlertTriangle } from 'lucide-react';
import type { SessionMetrics, ToolCall, SubAgentActivity } from '../types/chat';

interface MetricsPanelProps {
  metrics: SessionMetrics;
  toolCalls: ToolCall[];
  activeToolCalls?: ToolCall[];
  subagentActivity: SubAgentActivity[];
  isLoading: boolean;
  agentName?: string;
  agentDescription?: string;
  sessionId?: string | null;
}

export default function MetricsPanel({
  metrics,
  toolCalls,
  activeToolCalls = [],
  subagentActivity,
  isLoading,
  agentName,
  agentDescription,
  sessionId
}: MetricsPanelProps) {
  const [toolCallsExpanded, setToolCallsExpanded] = useState(false);
  const [subagentsExpanded, setSubagentsExpanded] = useState(false);
  const { t } = useTranslation('chat');

  return (
    <div
      className="h-full overflow-y-auto"
      style={{
        backgroundColor: 'var(--color-background-light)',
      }}
    >
      {/* Current Agent */}
      {sessionId && agentName && (
        <div
          className="p-3"
        >
          <div
            className="text-[10px] uppercase tracking-wider font-medium mb-1"
            style={{ color: 'var(--color-text-muted)' }}
          >
            {t('active_agent')}
          </div>
          <div
            className="text-sm font-semibold truncate"
            style={{ color: 'var(--color-text-primary)' }}
          >
            {agentName}
          </div>
          <div
            className="text-[11px] mt-1 leading-relaxed line-clamp-2"
            style={{ color: 'var(--color-text-muted)' }}
          >
            {agentDescription || t('chat_session_active')}
          </div>
        </div>
      )}

      {/* Session Metrics */}
      <div className="p-3">
        <div
          className="text-[10px] uppercase tracking-wider font-medium mb-2"
          style={{ color: 'var(--color-text-muted)' }}
        >
          {t('session_metrics')}
        </div>

        {isLoading ? (
          <div
            className="text-sm"
            style={{ color: 'var(--color-text-muted)' }}
          >
            {t('loading')}
          </div>
        ) : (
          <div className="space-y-1.5">
            <MetricCard
              icon={<Activity className="w-4 h-4" />}
              label={t('total_tokens')}
              value={(metrics?.total_tokens ?? 0).toLocaleString()}
            />
            <MetricCard
              icon={<DollarSign className="w-4 h-4" />}
              label={t('total_cost')}
              value={`$${(metrics?.total_cost_usd ?? 0).toFixed(4)}`}
            />
            {metrics?.rag_context_tokens ? (
              <MetricCard
                icon={<FileText className="w-4 h-4" />}
                label={t('rag_context')}
                value={`${(metrics.rag_context_tokens ?? 0).toLocaleString()} tokens`}
              />
            ) : null}
            {metrics?.context_tokens !== undefined && (
              <MetricCard
                icon={
                  (metrics.context_tokens ?? 0) > 30000 ? (
                    <AlertTriangle className="w-4 h-4" />
                  ) : (
                    <Database className="w-4 h-4" />
                  )
                }
                label={t('context_size')}
                value={`${(metrics.context_tokens ?? 0).toLocaleString()} tokens`}
                warning={(metrics.context_tokens ?? 0) > 30000}
              />
            )}
            <MetricCard
              icon={<Zap className="w-4 h-4" />}
              label={t('tool_calls')}
              value={(metrics?.tool_calls ?? 0).toString()}
            />
            <MetricCard
              icon={<Users className="w-4 h-4" />}
              label={t('subagent_spawns')}
              value={(metrics?.subagent_spawns ?? 0).toString()}
            />
            <MetricCard
              icon={<Database className="w-4 h-4" />}
              label={t('context_ops')}
              value={(metrics?.context_operations ?? 0).toString()}
            />
          </div>
        )}
      </div>

      {/* Tool Calls - show both active (streaming) and completed (from API) */}
      {(activeToolCalls.length > 0 || toolCalls.length > 0) && (
        <div
          className="border-t"
          style={{ borderColor: 'var(--color-border-dark)' }}
        >
          <button
            onClick={() => setToolCallsExpanded(!toolCallsExpanded)}
            className="w-full p-3 flex items-center justify-between hover:bg-white/50 transition-colors"
          >
            <div className="flex items-center gap-2">
              <Zap className="w-3.5 h-3.5" style={{ color: 'var(--color-primary)' }} />
              <h3
                className="text-xs font-semibold uppercase tracking-wide"
                style={{ color: 'var(--color-text-primary)' }}
              >
                Tool Calls ({toolCalls.length + activeToolCalls.filter(t => t.status === 'running').length})
              </h3>
            </div>
            {toolCallsExpanded ? (
              <ChevronDown className="w-4 h-4" style={{ color: 'var(--color-text-muted)' }} />
            ) : (
              <ChevronRight className="w-4 h-4" style={{ color: 'var(--color-text-muted)' }} />
            )}
          </button>

          {toolCallsExpanded && (
            <div className="px-3 pb-3 space-y-1.5">
              {/* Active (streaming) tool calls first */}
              {activeToolCalls.filter(t => t.status === 'running').slice(-5).reverse().map((call, index) => (
                <div
                  key={`active-${index}`}
                  className="p-2 rounded border border-blue-300"
                  style={{
                    backgroundColor: '#eff6ff',
                  }}
                >
                  <div className="flex items-center gap-2">
                    <Activity className="w-3 h-3 text-blue-500 animate-pulse" />
                    <span
                      className="font-mono text-xs font-semibold text-blue-600"
                    >
                      {call.tool_name}
                    </span>
                    {call.skill_name && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-blue-100 text-blue-700 font-medium">
                        {call.skill_name}
                      </span>
                    )}
                  </div>
                  {call.arguments && Object.keys(call.arguments).length > 0 && (
                    <div className="text-xs text-gray-500 mt-1 truncate" title={JSON.stringify(call.arguments)}>
                      {JSON.stringify(call.arguments)}
                    </div>
                  )}
                  <div
                    className="text-xs mt-0.5 text-gray-400"
                  >
                    running...
                  </div>
                </div>
              ))}
              {/* Completed tool calls from API */}
              {toolCalls.slice(-10).reverse().map((call, index) => (
                <div
                  key={index}
                  className="p-2 rounded border"
                  style={{
                    backgroundColor: 'var(--color-background-light)',
                    borderColor: 'var(--color-border-dark)',
                  }}
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-mono text-xs font-semibold"
                      style={{ color: 'var(--color-primary)' }}>
                      {call.tool_name}
                    </span>
                    {call.skill_name && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-blue-50 text-blue-600 font-medium">
                        {call.skill_name}
                      </span>
                    )}
                  </div>
                  <div
                    className="text-xs mt-0.5"
                    style={{ color: 'var(--color-text-muted)' }}
                  >
                    {new Date(call.timestamp).toLocaleTimeString()}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Subagent Activity */}
      {subagentActivity.length > 0 && (
        <div
          className="border-t"
          style={{ borderColor: 'var(--color-border-dark)' }}
        >
          <button
            onClick={() => setSubagentsExpanded(!subagentsExpanded)}
            className="w-full p-3 flex items-center justify-between hover:bg-white/50 transition-colors"
          >
            <div className="flex items-center gap-2">
              <Users className="w-3.5 h-3.5" style={{ color: 'var(--color-primary)' }} />
              <h3
                className="text-xs font-semibold uppercase tracking-wide"
                style={{ color: 'var(--color-text-primary)' }}
              >
                Subagent Activity ({subagentActivity.length})
              </h3>
            </div>
            {subagentsExpanded ? (
              <ChevronDown className="w-4 h-4" style={{ color: 'var(--color-text-muted)' }} />
            ) : (
              <ChevronRight className="w-4 h-4" style={{ color: 'var(--color-text-muted)' }} />
            )}
          </button>

          {subagentsExpanded && (
            <div className="px-3 pb-3 space-y-1.5">
              {subagentActivity.slice(-10).reverse().map((activity, index) => (
                <div
                  key={index}
                  className="p-2 rounded border"
                  style={{
                    backgroundColor: 'var(--color-background-light)',
                    borderColor: 'var(--color-border-dark)',
                  }}
                >
                  <div
                    className="font-medium text-xs"
                    style={{ color: 'var(--color-primary)' }}
                  >
                    {activity.subagent_name}
                  </div>
                  <div
                    className="text-xs mt-0.5"
                    style={{ color: 'var(--color-text-primary)' }}
                  >
                    {activity.action}
                  </div>
                  <div
                    className="text-xs mt-0.5"
                    style={{ color: 'var(--color-text-muted)' }}
                  >
                    {new Date(activity.timestamp).toLocaleTimeString()}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface MetricCardProps {
  icon: React.ReactNode;
  label: string;
  value: string;
  warning?: boolean;
}

function MetricCard({ icon, label, value, warning = false }: MetricCardProps) {
  return (
    <div
      className="p-2 rounded-lg border"
      style={{
        backgroundColor: warning ? 'rgba(245, 158, 11, 0.05)' : 'var(--color-background-light)',
        borderColor: warning ? 'rgba(245, 158, 11, 0.3)' : 'var(--color-border-dark)',
      }}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 flex items-center" style={{ color: warning ? '#f59e0b' : 'var(--color-primary)' }}>
            {icon}
          </div>
          <div>
            <div
              className="text-[10px] font-medium"
              style={{ color: 'var(--color-text-muted)' }}
            >
              {label}
            </div>
            <div
              className="text-xs font-bold"
              style={{ color: warning ? '#f59e0b' : 'var(--color-text-primary)' }}
            >
              {value}
            </div>
            {warning && (
              <div className="text-[10px] mt-0.5" style={{ color: '#f59e0b' }}>
                Context is large - consider starting a new session
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
