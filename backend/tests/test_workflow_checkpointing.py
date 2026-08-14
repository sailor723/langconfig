# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Regression tests for workflow checkpointing + HITL wiring.

The executor previously defaulted ``checkpointer_enabled`` to False (so live
workflow runs never checkpointed, contradicting the architecture doc §12)
and hardcoded ``interrupt_before=[]`` (so APPROVAL_NODE HITL pauses were
no-ops). These tests pin the new defaults at the source level.
"""
import inspect

from core.workflows.executor import execution as exec_module


def test_checkpointer_enabled_defaults_to_true():
    src = inspect.getsource(exec_module)
    assert (
        'input_data.get("checkpointer_enabled", True)' in src
    ), "checkpointer_enabled must default to True (durable execution by default)"


def test_no_hardcoded_empty_interrupt_before():
    src = inspect.getsource(exec_module)
    assert "interrupt_before=[]" not in src, (
        "interrupt_before must be derived from APPROVAL_NODE nodes, not []"
    )


def test_interrupt_before_derived_from_approval_nodes():
    src = inspect.getsource(exec_module)
    assert 'n.get("node_type") == "APPROVAL_NODE"' in src, (
        "interrupt_before must be populated from APPROVAL_NODE node ids"
    )
    assert "interrupt_before=interrupt_before" in src


def test_workflow_config_in_scope_for_standard_path():
    """The standard (non-official-pattern) path must define workflow_config
    before the compile block uses it (was only defined in the supervisor/
    swarm branches → NameError on the common path)."""
    src = inspect.getsource(exec_module)
    cfg_assign = src.index("workflow_config = workflow.configuration or {}")
    compile_block = src.index("if checkpointer:")
    assert cfg_assign < compile_block, (
        "workflow_config must be assigned before the compile block"
    )
