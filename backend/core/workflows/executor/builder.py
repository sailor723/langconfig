# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Workflow graph builder mixin: builds the LangGraph StateGraph from a workflow.

Extracted from the former monolithic executor.py.
"""

from langgraph.graph import StateGraph, START, END

# Task 3: Node-level caching support
from core.workflows.cache_config import build_cache_policy

from models.workflow import WorkflowProfile

from .shared import SimpleWorkflowState, logger


class _WorkflowBuilderMixin:
    async def _build_graph_from_workflow(
        self,
        workflow: WorkflowProfile
    ) -> StateGraph:
        """
        Build a LangGraph StateGraph from a WorkflowProfile.

        The WorkflowProfile.configuration contains the workflow data:
        {
            "nodes": [{"id": "node-1", "type": "agent", "config": {...}}],
            "edges": [{"id": "e1-2", "source": "node-1", "target": "node-2"}]
        }
        """
        logger.info(f"Building graph from workflow configuration with {len(workflow.configuration.get('nodes', []))} nodes")

        # Create StateGraph with SimpleWorkflowState
        graph = StateGraph(SimpleWorkflowState)

        # Get nodes and edges from configuration
        nodes = workflow.configuration.get("nodes", [])
        edges = workflow.configuration.get("edges", [])

        # DEBUG: Log what we're loading from database
        logger.info(f"[LOAD] ========== WORKFLOW CONFIGURATION DEBUG ==========")
        logger.info(f"[LOAD] Workflow configuration has {len(nodes)} nodes")
        logger.info(f"[LOAD] Raw nodes data: {nodes}")
        for node in nodes:
            logger.info(f"[LOAD] Processing node: {node}")
            node_id = node.get("id", "unknown")
            # Database stores config at TOP LEVEL: node["config"]
            # NOT nested in node["data"]["config"] (that's ReactFlow UI structure)
            node_config = node.get("config", {})
            logger.info(f"[LOAD] Node {node_id} - node_config keys: {list(node_config.keys())}")
            mcp_tools = node_config.get("mcp_tools", [])
            cli_tools = node_config.get("cli_tools", [])
            custom_tools = node_config.get("custom_tools", [])
            logger.info(f"[LOAD] Node {node_id} - Loaded from DB - mcp_tools: {mcp_tools}, cli_tools: {cli_tools}, custom_tools: {custom_tools}")

            # WARNING: If mcp_tools is empty but we expect tools, alert!
            if not mcp_tools and node_config.get("enable_memory") or node_config.get("enable_rag"):
                logger.warning(f"[LOAD] Node {node_id} - No MCP tools but memory/RAG enabled! Check frontend save logic.")
        logger.info(f"[LOAD] ==================================================")

        if not nodes:
            raise ValueError(f"Workflow '{workflow.name}' has no nodes defined")

        # Track special control nodes
        entry_point_override = None  # Track if user specified START_NODE
        terminal_nodes = []  # Track END_NODEs for special handling

        # Build node metadata map for callback handler (for proper event labeling)
        node_metadata = {}

        for node in nodes:
            node_id = node["id"]
            # Database stores config at top level: node["config"]
            node_type = node.get("type", "default")

            # CRITICAL: Also check node.data.agentType as fallback (same as main loop below)
            node_data = node.get("data", {})
            data_agent_type = node_data.get("agentType", "")
            agent_type = node_type if node_type != "default" else (data_agent_type or "default")

            # Get the actual display label:
            # 1. Try node data label (saved by frontend when user creates node)
            # 2. Fallback to type with underscores replaced by spaces and title cased
            agent_label = node_data.get("label") or agent_type.replace('_', ' ').title()

            # Skip non-executable control nodes (START and END are handled specially)
            if agent_type not in ['START_NODE', 'END_NODE']:
                # Normalize config to ensure backward compatibility with V1/V2 schemas
                raw_config = node.get("config", {})
                # Store config as-is (AgentFactory will normalize when needed)
                node_metadata[node_id] = {
                    "label": agent_label,
                    "agent_type": agent_type,
                    "config": raw_config
                }

        # Store in executor instance for callback access
        self.node_metadata = node_metadata
        logger.debug(f"Built node metadata for {len(node_metadata)} nodes")

        # DEBUG: Log extracted labels to verify they match canvas
        for node_id, metadata in node_metadata.items():
            logger.info(f"[NODE LABEL DEBUG] Node {node_id}: label='{metadata.get('label')}', type='{metadata.get('agent_type')}'")

        # Add nodes to graph
        for node in nodes:
            node_id = node["id"]
            # Database stores config at top level: node["config"]
            # NOT nested in node["data"]["config"]
            node_type = node.get("type", "default")

            # CRITICAL FIX: Also check node.data.agentType as fallback
            # Frontend saves agentType in node.data.agentType, and type at top level
            # But some edge cases may only have one or the other
            node_data = node.get("data", {})
            data_agent_type = node_data.get("agentType", "")

            # Use the first valid: node.type (if not default), then node.data.agentType
            agent_type = node_type if node_type != "default" else (data_agent_type or "default")

            # DEBUG: Log ALL node type info to diagnose END_NODE detection
            data_label = node_data.get("label", "NO_LABEL")
            logger.info(f"[NODE TYPE DEBUG] {node_id}: type={node_type}, data.agentType={data_agent_type}, resolved_type={agent_type}, label={data_label}")

            # Handle special START_NODE - don't add as node, use as entry point
            if agent_type == 'START_NODE':
                logger.info(f"Detected START_NODE: {node_id} - will determine entry point from connections")
                # Find the actual first node (what START_NODE points to)
                next_nodes = [e["target"] for e in edges if e["source"] == node_id]
                if next_nodes:
                    entry_point_override = next_nodes[0]
                    logger.debug(f"Entry point resolved from START_NODE to: {entry_point_override}")
                continue  # Skip adding START_NODE as actual node

            # Handle special END_NODE - don't add as node, LangGraph END is sufficient
            if agent_type == 'END_NODE':
                terminal_nodes.append(node_id)
                logger.info(f"✓ Detected END_NODE: {node_id} - will redirect connections to LangGraph END")
                continue  # Skip adding END_NODE as actual node

            # Create node executor function for all other node types
            node_executor = self._create_node_executor(node_id, agent_type, node)

            # Task 3 + Task 6: Build add_node kwargs for caching and deferred support
            node_config = node.get("config", {})
            add_node_kwargs = {}

            # Task 3: Cache policy
            node_cache_policy = build_cache_policy(node_config) if node_config else None
            if node_cache_policy:
                add_node_kwargs["cache_policy"] = node_cache_policy
                logger.info(f"[CACHE] Node '{node_id}' caching enabled (TTL={node_config.get('cache_ttl', 300)}s)")

            # Task 6: Deferred flag
            is_deferred = node_config.get("deferred", False) if node_config else False
            if is_deferred:
                add_node_kwargs["defer"] = True
                logger.info(f"[DEFERRED] Node '{node_id}' marked as deferred")

            graph.add_node(node_id, node_executor, **add_node_kwargs)

            logger.info(f"Added node to graph: {node_id} (type: {agent_type})")

        # Set entry point (use START_NODE if specified, otherwise find node with no incoming edges)
        if nodes:
            if entry_point_override:
                first_node_id = entry_point_override
                logger.info(f"Using user-specified entry point: {first_node_id}")
            else:
                # Build a map of node_id -> agent_type for proper filtering
                node_type_map = {}
                for n in nodes:
                    nid = n["id"]
                    n_type = n.get("type", "default")
                    n_data = n.get("data", {})
                    n_data_type = n_data.get("agentType", "")
                    # Resolve type: prefer explicit type, fallback to data.agentType
                    resolved_type = n_type if n_type not in ["default", ""] else (n_data_type or "default")
                    node_type_map[nid] = resolved_type

                # Find regular nodes (non-control nodes)
                regular_nodes = [n for n in nodes
                                if node_type_map.get(n["id"], "default")
                                not in ['START_NODE', 'END_NODE', 'CHECKPOINT_NODE']]

                if not regular_nodes:
                    raise ValueError("Workflow must have at least one regular (non-control) node")

                # Get all START_NODE ids for proper edge filtering
                start_node_ids = {nid for nid, ntype in node_type_map.items() if ntype == 'START_NODE'}

                # Get all target nodes (nodes that have incoming edges from non-START nodes)
                target_node_ids = {e["target"] for e in edges if e["source"] not in start_node_ids}

                # Find nodes with NO incoming edges from regular nodes - these are potential entry points
                entry_candidates = [n["id"] for n in regular_nodes if n["id"] not in target_node_ids]

                if entry_candidates:
                    # Use the first node with no incoming edges
                    first_node_id = entry_candidates[0]
                    logger.info(f"✓ Auto-detected entry point (no incoming edges): {first_node_id}")

                    if len(entry_candidates) > 1:
                        logger.warning(f"⚠️  Multiple entry points detected: {entry_candidates}")
                        logger.warning(f"   Using {first_node_id}. Consider adding a START_NODE for clarity.")
                else:
                    # Fallback: If all nodes have incoming edges (cycle), use first node
                    first_node_id = regular_nodes[0]["id"]
                    logger.warning(f"⚠️  All nodes have incoming edges (possible cycle)")
                    logger.warning(f"   Using first node as fallback: {first_node_id}")

            graph.add_edge(START, first_node_id)
            logger.info(f"✓ Workflow entry point: START -> {first_node_id}")

        # Build set of regular node IDs for validation
        regular_node_ids = {n["id"] for n in nodes
                          if n.get("type", n.get("data", {}).get("label", "default"))
                          not in ['START_NODE', 'END_NODE']}

        # Group edges by source node to build routing maps for control nodes
        edges_by_source = {}
        for edge in edges:
            source = edge["source"]
            if source not in edges_by_source:
                edges_by_source[source] = []
            edges_by_source[source].append(edge)

        # Add edges to graph
        for source_id, source_edges in edges_by_source.items():
            # Get source node data
            source_node_data = next((n for n in nodes if n["id"] == source_id), {})
            source_type = source_node_data.get("type", source_node_data.get("data", {}).get("label", "default"))

            # Skip edges FROM START_NODE (already handled in entry point)
            if source_type == 'START_NODE':
                logger.debug(f"Skipping edges from START_NODE: {source_id}")
                continue

            # Check if source is a CONDITIONAL_NODE or LOOP_NODE
            if source_type == 'CONDITIONAL_NODE':
                # Build routing map for conditional edges
                routing_map = {}
                for edge in source_edges:
                    target = edge["target"]
                    # Get edge label/condition from edge data
                    edge_data = edge.get("data", {})
                    edge_label = edge_data.get("label", "default")

                    # Handle END_NODE targets
                    target_node_data = next((n for n in nodes if n["id"] == target), {})
                    target_type = target_node_data.get("type", target_node_data.get("data", {}).get("label", "default"))

                    if target_type == 'END_NODE' or target == "__END__":
                        routing_map[edge_label] = END
                    else:
                        routing_map[edge_label] = target

                    logger.debug(f"CONDITIONAL_NODE {source_id}: route '{edge_label}' -> {target}")

                # Create routing function for this conditional node
                def create_conditional_router(node_id_capture, route_map):
                    def route_conditional(state: SimpleWorkflowState) -> str:
                        # Get the route from state (set by CONDITIONAL_NODE executor)
                        route_key = state.get("conditional_route", "default")
                        target = route_map.get(route_key, route_map.get("default", END))
                        logger.debug(f"[Router] CONDITIONAL_NODE {node_id_capture} routing '{route_key}' to {target}")
                        return target
                    return route_conditional

                # Add conditional edges
                router_func = create_conditional_router(source_id, routing_map)
                graph.add_conditional_edges(source_id, router_func)
                logger.info(f"Added conditional edges for {source_id} with {len(routing_map)} routes")

            elif source_type == 'LOOP_NODE':
                # Build routing map for loop edges
                routing_map = {}
                for edge in source_edges:
                    target = edge["target"]
                    edge_data = edge.get("data", {})
                    edge_label = edge_data.get("label", "continue")

                    # Handle END_NODE targets
                    target_node_data = next((n for n in nodes if n["id"] == target), {})
                    target_type = target_node_data.get("type", target_node_data.get("data", {}).get("label", "default"))

                    if target_type == 'END_NODE' or target == "__END__":
                        routing_map[edge_label] = END
                    else:
                        routing_map[edge_label] = target

                    logger.debug(f"LOOP_NODE {source_id}: route '{edge_label}' -> {target}")

                # Create routing function for loop node
                def create_loop_router(node_id_capture, route_map):
                    def route_loop(state: SimpleWorkflowState) -> str:
                        # Get the route from state (set by LOOP_NODE executor)
                        route_key = state.get("loop_route", "continue")
                        target = route_map.get(route_key, route_map.get("continue", END))
                        logger.debug(f"[Router] LOOP_NODE {node_id_capture} routing '{route_key}' to {target}")
                        return target
                    return route_loop

                # Add conditional edges
                router_func = create_loop_router(source_id, routing_map)
                graph.add_conditional_edges(source_id, router_func)
                logger.info(f"Added loop edges for {source_id} with {len(routing_map)} routes")

            else:
                # Regular nodes: add direct edges
                for edge in source_edges:
                    target = edge["target"]

                    # Handle edges TO END_NODE
                    target_node_data = next((n for n in nodes if n["id"] == target), {})

                    # Check both node.type and node.data.agentType for END_NODE
                    target_node_type = target_node_data.get("type", "default")
                    target_data_agent_type = target_node_data.get("data", {}).get("agentType", "")
                    target_type = target_node_type if target_node_type != "default" else (target_data_agent_type or "default")

                    # DEBUG: Log target resolution for END_NODE detection
                    logger.info(f"[EDGE DEBUG] source={source_id}, target={target}, target_type={target_type}, node.type={target_node_type}, data.agentType={target_data_agent_type}")

                    if target_type == 'END_NODE' or target == "__END__":
                        target_node = END
                        logger.info(f"✓ Edge redirected to LangGraph END: {source_id} -> END")
                    else:
                        target_node = target

                    graph.add_edge(source_id, target_node)
                    logger.info(f"Added edge: {source_id} -> {target_node}")

        # Validate workflow structure - check for nodes with no outgoing edges
        # This is CRITICAL for catching workflow configuration issues
        if edges:
            # REMOVED AUTO-CONNECT LOGIC - IT WAS BREAKING WORKFLOWS
            # The graph already has all edges added correctly above.
            # Auto-connecting was creating duplicate/conflicting paths to END.
            # If a workflow needs an END_NODE, the user should add it explicitly.

            # Just log for diagnostics
            logger.debug(f"📊 EDGE VALIDATION: {len(edges)} edges processed")
        else:
            # No edges defined - this is also an error for multi-node workflows
            if len(regular_nodes) > 1:
                logger.error("❌ WORKFLOW ERROR: Multiple nodes but no edges defined!")
                logger.error("   Workflows need edges connecting nodes.")
                logger.error("   Please connect your nodes in the workflow canvas.")
                raise ValueError(
                    f"Workflow has {len(regular_nodes)} nodes but no edges. "
                    f"Please connect your nodes in the canvas."
                )
            elif len(regular_nodes) == 1:
                # Single node workflow - auto-connect to END is acceptable
                single_node_id = regular_nodes[0]["id"]
                graph.add_edge(single_node_id, END)
                logger.info(f"✓ Single-node workflow: {single_node_id} → END")

        return graph
