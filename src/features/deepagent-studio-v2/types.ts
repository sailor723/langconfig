export interface SubAgent {
  id?: string | number;
  name: string;
  description?: string;
  skill_type?: string;
  prompt?: string;
}

export interface AgentStructure {
  id?: number;
  name: string;
  description?: string;
  model: string;
  system_prompt?: string;
  native_tools?: string[];
  custom_tools?: string[];
  tools?: string[];
  subagents?: SubAgent[];
  skills?: string[];
}
