/**
 * DeepAgent Studio — shared types
 *
 * Phase 8: read-only visualization of any DeepAgent's structure.
 */

export type ExecutionStatus = 'idle' | 'running' | 'success' | 'error';

export interface SubAgent {
  id: string;
  name: string;            // skill-id or user-defined name
  description: string;
  source: 'skill' | 'user' | 'generated';
  model?: string;
  tools: string[];
  instructions_preview?: string;
  status: ExecutionStatus;
}

export interface MainAgentInfo {
  id: string;
  name: string;
  description: string;
  model: string;
  system_prompt_preview: string;
  temperature: number;
  max_tokens: number;
  tools: string[];
  middleware: string[];
  subagents_config: Array<{ name: string; description: string }>;
  use_deepagents?: boolean;
  enable_compiled_subagents?: boolean;
  use_local_sandbox?: boolean;
}

export interface Capability {
  type: 'tool' | 'memory' | 'sandbox' | 'router' | 'prompt';
  label: string;
  value: string;
  enabled: boolean;
}

export interface AgentStructure {
  main_agent: MainAgentInfo;
  sub_agents: SubAgent[];
  capabilities: Capability[];
  meta: {
    fetched_at: string;
    skill_count: number;
    tool_count: number;
    is_valid: boolean;
  };
}

export interface NodeExecutionEvent {
  type: 'node_start' | 'node_end' | 'token' | 'tool_start' | 'tool_end' | 'done' | 'error';
  node_id?: string;        // sub-agent id or 'main'
  node_kind?: 'main' | 'sub';
  skill_name?: string;
  tool_name?: string;
  content?: string;
  usage?: { input_tokens: number; output_tokens: number; total_tokens: number };
  cost?: number;
  error?: string;
}