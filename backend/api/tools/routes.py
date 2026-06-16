# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
API endpoints for Custom Tools.

Allows users to create, manage, test, and share custom tools.
"""

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from fastapi.responses import JSONResponse
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from datetime import datetime
import json
import logging

from db.database import get_db
from models.custom_tool import CustomTool, ToolExecutionLog, ToolType, ToolTemplateType
from core.tools.factory import ToolFactory
from core.tools.templates import ToolTemplateRegistry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/custom-tools", tags=["custom-tools"])


# =============================================================================
# Pydantic Models for Request/Response
# =============================================================================

class CustomToolCreate(BaseModel):
    """Request model for creating a custom tool"""
    tool_id: str = Field(..., description="Unique tool identifier")
    name: str = Field(..., description="Display name")
    description: str = Field(..., description="Tool description (shown to LLM)")
    tool_type: str = Field(..., description="Tool type: api, notification, image_video, database, data_transform")
    template_type: Optional[str] = Field(None, description="Template type if using a template")
    implementation_config: Dict[str, Any] = Field(..., description="Tool-specific configuration")
    input_schema: Dict[str, Any] = Field(..., description="JSON Schema for inputs")
    output_format: Optional[str] = Field("string", description="Output format")
    validation_rules: Optional[Dict[str, Any]] = Field(None, description="Additional validation rules")
    is_template_based: bool = Field(True, description="Whether created from a template")
    is_advanced_mode: bool = Field(False, description="Whether in advanced mode")
    category: Optional[str] = Field(None, description="User-defined category")
    tags: List[str] = Field(default_factory=list, description="Tags for organization")
    project_id: Optional[int] = Field(None, description="Optional project scope")


class CustomToolUpdate(BaseModel):
    """Request model for updating a custom tool"""
    name: Optional[str] = None
    description: Optional[str] = None
    implementation_config: Optional[Dict[str, Any]] = None
    input_schema: Optional[Dict[str, Any]] = None
    output_format: Optional[str] = None
    validation_rules: Optional[Dict[str, Any]] = None
    is_advanced_mode: Optional[bool] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None


class ToolTestRequest(BaseModel):
    """Request model for testing a tool"""
    test_input: Dict[str, Any] = Field(..., description="Input parameters to test with")


class ToolTestResponse(BaseModel):
    """Response model for tool testing"""
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None
    execution_time_ms: Optional[int] = None


class CodeVerificationRequest(BaseModel):
    """Request model for verifying Python code"""
    code: str = Field(..., description="Python source code to verify")
    function_name: str = Field(..., description="Expected function name")
    description: Optional[str] = Field(None, description="Tool description for context")
    auto_fix: bool = Field(True, description="Whether to use AI to suggest fixes")


class CodeVerificationResponse(BaseModel):
    """Response model for code verification"""
    is_valid: bool = Field(..., description="Whether the code is valid")
    errors: List[Dict[str, Any]] = Field(default_factory=list, description="List of errors found")
    warnings: List[str] = Field(default_factory=list, description="List of warnings")
    suggested_code: Optional[str] = Field(None, description="AI-suggested fixed code")
    explanation: Optional[str] = Field(None, description="Explanation of what was fixed")
    verified_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# =============================================================================
# Tool CRUD Endpoints
# =============================================================================

@router.get("")
async def list_custom_tools(
    project_id: Optional[int] = None,
    template_type: Optional[str] = None,
    tool_type: Optional[str] = None,
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    """
    List all custom tools with optional filtering.

    Query params:
    - project_id: Filter by project
    - template_type: Filter by template type
    - tool_type: Filter by tool type
    """
    try:
        query = db.query(CustomTool)

        # Apply filters
        if project_id is not None:
            query = query.filter(CustomTool.project_id == project_id)
        if template_type:
            query = query.filter(CustomTool.template_type == template_type)
        if tool_type:
            query = query.filter(CustomTool.tool_type == tool_type)

        tools = query.order_by(CustomTool.created_at.desc()).all()

        # Convert to response format
        result = []
        for tool in tools:
            result.append({
                "id": tool.id,
                "tool_id": tool.tool_id,
                "name": tool.name,
                "description": tool.description,
                "tool_type": tool.tool_type.value,
                "template_type": tool.template_type.value if tool.template_type else None,
                "implementation_config": tool.implementation_config,  # ADDED: Include config details
                "input_schema": tool.input_schema,  # ADDED: Include input schema
                "output_format": tool.output_format,  # ADDED: Include output format
                "is_template_based": tool.is_template_based,
                "is_advanced_mode": tool.is_advanced_mode,
                "category": tool.category,
                "tags": tool.tags,
                "usage_count": tool.usage_count,
                "error_count": tool.error_count,
                "last_used_at": tool.last_used_at.isoformat() if tool.last_used_at else None,
                "created_at": tool.created_at.isoformat(),
                "version": tool.version,
                "project_id": tool.project_id
            })

        return result

    except Exception as e:
        logger.error(f"Failed to list custom tools: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list custom tools: {str(e)}")


@router.post("")
async def create_custom_tool(
    tool_data: CustomToolCreate,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Create a new custom tool."""
    try:
        # Validate configuration
        tool_config = {
            "tool_id": tool_data.tool_id,
            "name": tool_data.name,
            "description": tool_data.description,
            "tool_type": tool_data.tool_type,
            "template_type": tool_data.template_type,
            "implementation_config": tool_data.implementation_config,
            "input_schema": tool_data.input_schema,
            "output_format": tool_data.output_format
        }

        validation_result = ToolFactory.validate_tool_config(tool_config)
        if not validation_result.is_valid:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Invalid tool configuration",
                    "errors": validation_result.errors,
                    "warnings": validation_result.warnings
                }
            )

        # Check if tool_id already exists
        existing = db.query(CustomTool).filter(CustomTool.tool_id == tool_data.tool_id).first()
        if existing:
            raise HTTPException(status_code=409, detail=f"Tool with ID '{tool_data.tool_id}' already exists")

        # Create database record
        custom_tool = CustomTool(
            tool_id=tool_data.tool_id,
            name=tool_data.name,
            description=tool_data.description,
            tool_type=ToolType(tool_data.tool_type),
            template_type=ToolTemplateType(tool_data.template_type) if tool_data.template_type else None,
            implementation_config=tool_data.implementation_config,
            input_schema=tool_data.input_schema,
            output_format=tool_data.output_format,
            validation_rules=tool_data.validation_rules,
            is_template_based=tool_data.is_template_based,
            is_advanced_mode=tool_data.is_advanced_mode,
            category=tool_data.category,
            tags=tool_data.tags,
            project_id=tool_data.project_id,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )

        db.add(custom_tool)
        db.commit()
        db.refresh(custom_tool)

        logger.info(f"Created custom tool: {custom_tool.name} ({custom_tool.tool_id})")

        return {
            "id": custom_tool.id,
            "tool_id": custom_tool.tool_id,
            "name": custom_tool.name,
            "message": "Custom tool created successfully",
            "warnings": validation_result.warnings
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create custom tool: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create custom tool: {str(e)}")


@router.get("/{tool_id}")
async def get_custom_tool(
    tool_id: str,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Get a specific custom tool by ID."""
    try:
        tool = db.query(CustomTool).filter(CustomTool.tool_id == tool_id).first()

        if not tool:
            raise HTTPException(status_code=404, detail=f"Custom tool '{tool_id}' not found")

        return {
            "id": tool.id,
            "tool_id": tool.tool_id,
            "name": tool.name,
            "description": tool.description,
            "tool_type": tool.tool_type.value,
            "template_type": tool.template_type.value if tool.template_type else None,
            "implementation_config": tool.implementation_config,
            "input_schema": tool.input_schema,
            "output_format": tool.output_format,
            "validation_rules": tool.validation_rules,
            "is_template_based": tool.is_template_based,
            "is_advanced_mode": tool.is_advanced_mode,
            "category": tool.category,
            "tags": tool.tags,
            "usage_count": tool.usage_count,
            "error_count": tool.error_count,
            "last_used_at": tool.last_used_at.isoformat() if tool.last_used_at else None,
            "last_error_at": tool.last_error_at.isoformat() if tool.last_error_at else None,
            "created_at": tool.created_at.isoformat(),
            "updated_at": tool.updated_at.isoformat(),
            "version": tool.version,
            "project_id": tool.project_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get custom tool: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get custom tool: {str(e)}")


@router.put("/{tool_id}")
async def update_custom_tool(
    tool_id: str,
    tool_data: CustomToolUpdate,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Update an existing custom tool."""
    try:
        tool = db.query(CustomTool).filter(CustomTool.tool_id == tool_id).first()

        if not tool:
            raise HTTPException(status_code=404, detail=f"Custom tool '{tool_id}' not found")

        # Update fields
        if tool_data.name is not None:
            tool.name = tool_data.name
        if tool_data.description is not None:
            tool.description = tool_data.description
        if tool_data.implementation_config is not None:
            tool.implementation_config = tool_data.implementation_config
        if tool_data.input_schema is not None:
            tool.input_schema = tool_data.input_schema
        if tool_data.output_format is not None:
            tool.output_format = tool_data.output_format
        if tool_data.validation_rules is not None:
            tool.validation_rules = tool_data.validation_rules
        if tool_data.is_advanced_mode is not None:
            tool.is_advanced_mode = tool_data.is_advanced_mode
        if tool_data.category is not None:
            tool.category = tool_data.category
        if tool_data.tags is not None:
            tool.tags = tool_data.tags

        tool.updated_at = datetime.utcnow()

        # Validate updated configuration
        tool_config = {
            "tool_id": tool.tool_id,
            "name": tool.name,
            "description": tool.description,
            "tool_type": tool.tool_type.value,
            "implementation_config": tool.implementation_config,
            "input_schema": tool.input_schema
        }

        validation_result = ToolFactory.validate_tool_config(tool_config)
        if not validation_result.is_valid:
            db.rollback()
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Updated configuration is invalid",
                    "errors": validation_result.errors
                }
            )

        db.commit()
        db.refresh(tool)

        logger.info(f"Updated custom tool: {tool.name} ({tool.tool_id})")

        return {
            "tool_id": tool.tool_id,
            "message": "Custom tool updated successfully",
            "warnings": validation_result.warnings
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update custom tool: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update custom tool: {str(e)}")


@router.delete("/{tool_id}")
async def delete_custom_tool(
    tool_id: str,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Delete a custom tool."""
    try:
        tool = db.query(CustomTool).filter(CustomTool.tool_id == tool_id).first()

        if not tool:
            raise HTTPException(status_code=404, detail=f"Custom tool '{tool_id}' not found")

        tool_name = tool.name
        db.delete(tool)
        db.commit()

        logger.info(f"Deleted custom tool: {tool_name} ({tool_id})")

        return {
            "tool_id": tool_id,
            "message": f"Custom tool '{tool_name}' deleted successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete custom tool: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete custom tool: {str(e)}")


@router.post("/{tool_id}/duplicate")
async def duplicate_custom_tool(
    tool_id: str,
    new_tool_id: str,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Duplicate an existing custom tool."""
    try:
        original = db.query(CustomTool).filter(CustomTool.tool_id == tool_id).first()

        if not original:
            raise HTTPException(status_code=404, detail=f"Custom tool '{tool_id}' not found")

        # Check if new ID is available
        existing = db.query(CustomTool).filter(CustomTool.tool_id == new_tool_id).first()
        if existing:
            raise HTTPException(status_code=409, detail=f"Tool with ID '{new_tool_id}' already exists")

        # Create duplicate
        duplicate = CustomTool(
            tool_id=new_tool_id,
            name=f"{original.name} (Copy)",
            description=original.description,
            tool_type=original.tool_type,
            template_type=original.template_type,
            implementation_config=original.implementation_config.copy(),
            input_schema=original.input_schema.copy(),
            output_format=original.output_format,
            validation_rules=original.validation_rules.copy() if original.validation_rules else None,
            is_template_based=original.is_template_based,
            is_advanced_mode=original.is_advanced_mode,
            category=original.category,
            tags=original.tags.copy() if original.tags else [],
            project_id=original.project_id,
            parent_tool_id=original.id,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )

        db.add(duplicate)
        db.commit()
        db.refresh(duplicate)

        logger.info(f"Duplicated custom tool: {original.name} → {duplicate.name}")

        return {
            "id": duplicate.id,
            "tool_id": duplicate.tool_id,
            "name": duplicate.name,
            "message": "Custom tool duplicated successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to duplicate custom tool: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to duplicate custom tool: {str(e)}")


# =============================================================================
# Tool Testing Endpoints
# =============================================================================

@router.post("/{tool_id}/test")
async def test_custom_tool(
    tool_id: str,
    test_request: ToolTestRequest,
    db: Session = Depends(get_db)
) -> ToolTestResponse:
    """Test a custom tool with sample input."""
    try:
        tool = db.query(CustomTool).filter(CustomTool.tool_id == tool_id).first()

        if not tool:
            raise HTTPException(status_code=404, detail=f"Custom tool '{tool_id}' not found")

        # Build tool configuration
        tool_config = {
            "tool_id": tool.tool_id,
            "name": tool.name,
            "description": tool.description,
            "tool_type": tool.tool_type.value,
            "template_type": tool.template_type.value if tool.template_type else None,
            "implementation_config": tool.implementation_config,
            "input_schema": tool.input_schema,
            "output_format": tool.output_format
        }

        # Create the tool instance
        start_time = datetime.utcnow()
        langchain_tool = await ToolFactory.create_tool(tool_config, tool.project_id)

        # Execute the tool with test input
        try:
            result = await langchain_tool.ainvoke(test_request.test_input)
            end_time = datetime.utcnow()
            execution_time_ms = int((end_time - start_time).total_seconds() * 1000)

            # Log successful test
            log_entry = ToolExecutionLog(
                tool_id=tool.id,
                input_params=test_request.test_input,
                output_result={"output": result},
                status="success",
                execution_time_ms=execution_time_ms,
                created_at=datetime.utcnow()
            )
            db.add(log_entry)
            db.commit()

            logger.info(f"Tool test successful: {tool.name} ({execution_time_ms}ms)")

            return ToolTestResponse(
                success=True,
                output=str(result),
                execution_time_ms=execution_time_ms
            )

        except Exception as e:
            end_time = datetime.utcnow()
            execution_time_ms = int((end_time - start_time).total_seconds() * 1000)
            error_msg = str(e)

            # Log failed test
            log_entry = ToolExecutionLog(
                tool_id=tool.id,
                input_params=test_request.test_input,
                status="error",
                error_message=error_msg,
                execution_time_ms=execution_time_ms,
                created_at=datetime.utcnow()
            )
            db.add(log_entry)

            # Update error count
            tool.error_count += 1
            tool.last_error_at = datetime.utcnow()
            db.commit()

            logger.error(f"Tool test failed: {tool.name} - {error_msg}")

            return ToolTestResponse(
                success=False,
                error=error_msg,
                execution_time_ms=execution_time_ms
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to test custom tool: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to test custom tool: {str(e)}")


# =============================================================================
# Template Endpoints
# =============================================================================

@router.get("/templates/list")
async def list_tool_templates() -> List[Dict[str, Any]]:
    """Get all available tool templates."""
    try:
        templates = ToolTemplateRegistry.list_all()

        result = []
        for template in templates:
            result.append({
                "template_id": template.template_id,
                "name": template.name,
                "description": template.description,
                "category": template.category,
                "tool_type": template.tool_type.value,
                "icon": template.icon,
                "priority": template.priority,
                "is_featured": template.is_featured,
                "required_user_fields": template.required_user_fields,
                "example_use_cases": template.example_use_cases,
                "tags": template.tags
            })

        # Sort by priority (descending)
        result.sort(key=lambda x: x["priority"], reverse=True)

        return result

    except Exception as e:
        logger.error(f"Failed to list tool templates: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list tool templates: {str(e)}")


@router.get("/templates/{template_id}")
async def get_tool_template(template_id: str) -> Dict[str, Any]:
    """Get a specific tool template with full configuration."""
    try:
        template = ToolTemplateRegistry.get(template_id)

        if not template:
            raise HTTPException(status_code=404, detail=f"Tool template '{template_id}' not found")

        return {
            "template_id": template.template_id,
            "name": template.name,
            "description": template.description,
            "category": template.category,
            "tool_type": template.tool_type.value,
            "icon": template.icon,
            "priority": template.priority,
            "is_featured": template.is_featured,
            "config_template": template.config_template,
            "input_schema_template": template.input_schema_template,
            "required_user_fields": template.required_user_fields,
            "setup_instructions": template.setup_instructions,
            "example_use_cases": template.example_use_cases,
            "tags": template.tags
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get tool template: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get tool template: {str(e)}")


# =============================================================================
# Export/Import Endpoints
# =============================================================================

@router.post("/{tool_id}/export")
async def export_custom_tool(
    tool_id: str,
    db: Session = Depends(get_db)
) -> JSONResponse:
    """Export a custom tool as JSON file."""
    try:
        tool = db.query(CustomTool).filter(CustomTool.tool_id == tool_id).first()

        if not tool:
            raise HTTPException(status_code=404, detail=f"Custom tool '{tool_id}' not found")

        # Build export data (strip sensitive info like API keys)
        export_data = {
            "langconfig_tool_schema": "1.0",
            "exported_at": datetime.utcnow().isoformat(),
            "tool": {
                "tool_id": tool.tool_id,
                "name": tool.name,
                "description": tool.description,
                "tool_type": tool.tool_type.value,
                "template_type": tool.template_type.value if tool.template_type else None,
                "implementation_config": _strip_sensitive_data(tool.implementation_config),
                "input_schema": tool.input_schema,
                "output_format": tool.output_format,
                "validation_rules": tool.validation_rules,
                "is_template_based": tool.is_template_based,
                "category": tool.category,
                "tags": tool.tags,
                "version": tool.version,
                "metadata": {
                    "author": tool.created_by,
                    "usage_count": tool.usage_count,
                    "created_at": tool.created_at.isoformat()
                }
            }
        }

        # Return as downloadable JSON
        filename = f"{tool.tool_id}.json"
        return JSONResponse(
            content=export_data,
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to export custom tool: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to export custom tool: {str(e)}")


@router.post("/import")
async def import_custom_tool(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Import a custom tool from JSON file."""
    try:
        # Read file content
        content = await file.read()
        import_data = json.loads(content)

        # Validate schema version
        schema_version = import_data.get("langconfig_tool_schema")
        if schema_version != "1.0":
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported tool schema version: {schema_version}"
            )

        tool_data = import_data.get("tool")
        if not tool_data:
            raise HTTPException(status_code=400, detail="Invalid import file: missing 'tool' data")

        # Check for name conflicts
        existing = db.query(CustomTool).filter(
            CustomTool.tool_id == tool_data["tool_id"]
        ).first()

        # Auto-rename if conflict
        tool_id = tool_data["tool_id"]
        if existing:
            counter = 1
            while db.query(CustomTool).filter(CustomTool.tool_id == f"{tool_id}_{counter}").first():
                counter += 1
            tool_id = f"{tool_id}_{counter}"
            logger.info(f"Tool ID conflict resolved: {tool_data['tool_id']} → {tool_id}")

        # Create new tool
        custom_tool = CustomTool(
            tool_id=tool_id,
            name=tool_data["name"],
            description=tool_data["description"],
            tool_type=ToolType(tool_data["tool_type"]),
            template_type=ToolTemplateType(tool_data["template_type"]) if tool_data.get("template_type") else None,
            implementation_config=tool_data["implementation_config"],
            input_schema=tool_data["input_schema"],
            output_format=tool_data.get("output_format", "string"),
            validation_rules=tool_data.get("validation_rules"),
            is_template_based=tool_data.get("is_template_based", True),
            category=tool_data.get("category"),
            tags=tool_data.get("tags", []),
            version=tool_data.get("version", "1.0.0"),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )

        db.add(custom_tool)
        db.commit()
        db.refresh(custom_tool)

        logger.info(f"Imported custom tool: {custom_tool.name} ({custom_tool.tool_id})")

        return {
            "id": custom_tool.id,
            "tool_id": custom_tool.tool_id,
            "name": custom_tool.name,
            "message": "Custom tool imported successfully",
            "renamed": tool_id != tool_data["tool_id"]
        }

    except HTTPException:
        raise
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON file")
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to import custom tool: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to import custom tool: {str(e)}")


# =============================================================================
# Code Verification Endpoint
# =============================================================================

def _compile_python_code(code: str, function_name: str) -> List[Dict[str, Any]]:
    """
    Verify Python code compiles correctly.

    Checks:
    1. Valid Python syntax (compile)
    2. Function exists and is callable (exec)
    3. No undefined variable references in f-strings or expressions (AST analysis)

    Returns a list of errors, each with line number, message, and type.
    Empty list means the code is valid.
    """
    import ast
    import inspect

    errors = []

    # ── Step 1: AST-level checks (catches undefined vars, etc.) ──
    try:
        tree = ast.parse(code)

        # Find the target function definition
        target_fn = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == function_name:
                target_fn = node
                break

        if target_fn is None:
            # Function not found — will be caught by Step 2 below
            pass
        else:
            # Collect defined variables (params + assignments)
            param_names = {arg.arg for arg in target_fn.args.args}
            if target_fn.args.vararg:
                param_names.add(target_fn.args.vararg.arg)
            if target_fn.args.kwarg:
                param_names.add(target_fn.args.kwarg.arg)

            # Collect locally assigned names (a = ...)
            assigned_names = set()
            for node in ast.walk(target_fn):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            assigned_names.add(target.id)
                        elif isinstance(target, ast.Tuple) or isinstance(target, ast.List):
                            for elt in target.elts:
                                if isinstance(elt, ast.Name):
                                    assigned_names.add(elt.id)
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    assigned_names.add(node.target.id)
                elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
                    assigned_names.add(node.target.id)
                # Also catch for-loop variables
                elif isinstance(node, ast.For) and isinstance(node.target, ast.Name):
                    assigned_names.add(node.target.id)

            # Built-in names that are always available
            builtins = {
                "abs", "all", "any", "bin", "bool", "bytearray", "bytes",
                "chr", "complex", "dict", "dir", "divmod", "enumerate",
                "filter", "float", "format", "frozenset", "getattr",
                "hasattr", "hash", "hex", "id", "int", "isinstance",
                "issubclass", "iter", "len", "list", "map", "max", "min",
                "next", "object", "oct", "open", "ord", "pow", "print",
                "range", "repr", "reversed", "round", "set", "setattr",
                "slice", "sorted", "str", "sum", "tuple", "type", "vars",
                "zip", "__import__",
                # from pre-imported modules
                "math", "json", "jsonify",
            }

            # Walk the function body and find all Name nodes used in expressions
            # (but exclude function calls in decorators, defines, etc.)
            used_names = set()
            for node in ast.walk(target_fn):
                # Only look at Name nodes that are being *read* (not assigned to)
                if isinstance(node, ast.Name):
                    # Check if this is a load context (being read)
                    if isinstance(node.ctx, ast.Load):
                        used_names.add(node.id)

            # Find undefined names
            defined = param_names | assigned_names | builtins
            undefined = used_names - defined

            if undefined:
                # Group by the approximate line number for each undefined name
                for node in ast.walk(target_fn):
                    if isinstance(node, ast.Name) and node.id in undefined:
                        errors.append({
                            "line": node.lineno,
                            "message": f"Undefined variable '{node.id}'. Did you mean one of: {', '.join(sorted(param_names))}?",
                            "type": "NameError"
                        })
                        undefined.discard(node.id)
                        if not undefined:
                            break

    except SyntaxError as e:
        # Will be caught by compile() below
        pass

    # ── Step 2: Compile + exec (catches syntax and runtime errors) ──
    try:
        compiled = compile(code, "<tool_code>", "exec")

        local_ns = {}
        exec(compiled, {"math": __import__("math"), "json": __import__("json")}, local_ns)

        if function_name not in local_ns:
            errors.append({
                "line": 1,
                "message": f"Function '{function_name}' not defined in the provided code",
                "type": "DefinitionError"
            })
        else:
            fn = local_ns[function_name]
            if not inspect.iscoroutinefunction(fn) and not callable(fn):
                errors.append({
                    "line": 1,
                    "message": f"'{function_name}' is not a callable function",
                    "type": "TypeError"
                })

    except SyntaxError as e:
        errors.append({
            "line": e.lineno or 0,
            "message": str(e),
            "type": "SyntaxError",
            "text": e.text.strip() if e.text else ""
        })
    except Exception as e:
        errors.append({
            "line": 1,
            "message": str(e),
            "type": type(e).__name__
        })

    return errors


async def _fix_code_with_llm(
    code: str,
    function_name: str,
    description: Optional[str],
    errors: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Use LangChain LLM to suggest fixes for broken Python code.

    Returns dict with suggested_code and explanation.
    Falls back gracefully if no LLM is available.
    """
    try:
        from langchain.chat_models import init_chat_model
        from langchain_core.prompts import ChatPromptTemplate
        from config import settings

        # Determine which model to use (try available API keys)
        model_name = None
        model_provider = None

        if settings.OPENAI_API_KEY:
            model_name = "gpt-4o-mini"
            model_provider = "openai"
        elif settings.DEEPSEEK_API_KEY:
            model_name = "deepseek-chat"
            model_provider = "deepseek"
        elif settings.ANTHROPIC_API_KEY:
            model_name = "claude-3-haiku-20240307"
            model_provider = "anthropic"
        elif settings.GOOGLE_API_KEY:
            model_name = "gemini-2.0-flash"
            model_provider = "google"

        if not model_name or not model_provider:
            logger.warning("No LLM available for code fixing")
            return {"suggested_code": None, "explanation": None}

        error_lines = "\n".join(
            f"- Line {e.get('line', '?')} [{e.get('type', 'Error')}]: {e['message']}"
            for e in errors
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an expert Python developer. Fix the broken Python code below.
Rules:
- Only return the corrected Python code, wrapped in ```python ... ``` markers
- Do NOT change the function signature or name
- Fix syntax errors, indentation, missing imports, etc.
- Keep the logic and intent of the original code intact
- If the code has a f-string with format issues, fix the braces/quoting
- After the code block, add a brief explanation of what was fixed"""),
            ("human", """Fix this Python function `{function_name}`:

Description: {description}

Errors found:
{error_lines}

Broken code:
```python
{code}
```

Return the fixed code in ```python ... ``` markers."""),
        ])

        # Get API key based on provider
        api_key = None
        if model_provider == "openai":
            api_key = settings.OPENAI_API_KEY
        elif model_provider == "anthropic":
            api_key = settings.ANTHROPIC_API_KEY
        elif model_provider == "google":
            api_key = settings.GOOGLE_API_KEY
        elif model_provider == "deepseek":
            api_key = settings.DEEPSEEK_API_KEY

        llm = init_chat_model(
            model=model_name,
            model_provider=model_provider,
            temperature=0.1,
            api_key=api_key,
        )

        chain = prompt | llm
        result = await chain.ainvoke({
            "function_name": function_name,
            "description": description or "Custom Python tool",
            "error_lines": error_lines,
            "code": code
        })

        response_text = result.content if hasattr(result, 'content') else str(result)

        # Extract code from markdown ```python ... ``` block
        import re
        code_match = re.search(r'```(?:python)?\s*\n?(.*?)```', response_text, re.DOTALL)
        suggested_code = code_match.group(1).strip() if code_match else None

        # Extract explanation (everything after the code block)
        explanation = None
        if code_match:
            after_code = response_text[code_match.end():].strip()
            if after_code:
                explanation = after_code
        else:
            # No code block found, use whole response
            explanation = response_text

        return {"suggested_code": suggested_code, "explanation": explanation}

    except Exception as e:
        logger.error(f"LLM code fixing failed: {e}")
        return {"suggested_code": None, "explanation": None}


@router.post("/verify-code", response_model=CodeVerificationResponse)
async def verify_python_code(
    request: CodeVerificationRequest,
) -> CodeVerificationResponse:
    """
    Verify Python code for custom tools and optionally suggest fixes.

    Compiles the code, checks the function exists, and if auto_fix is enabled
    and errors are found, uses an LLM to suggest corrections.
    """
    try:
        logger.info(f"Verifying code for function: {request.function_name}")

        # Step 1: Try to compile and validate
        errors = _compile_python_code(request.code, request.function_name)
        is_valid = len(errors) == 0
        warnings = []

        if is_valid:
            # Basic style warnings
            if 'print(' in request.code and 'return' not in request.code:
                warnings.append("Function uses print() but has no return statement")
            if len(request.code) > 2000:
                warnings.append("Code is very long (>2000 chars); consider simplifying")

            logger.info(f"Code verification passed for: {request.function_name}")
            return CodeVerificationResponse(
                is_valid=True,
                errors=[],
                warnings=warnings,
                verified_at=datetime.utcnow().isoformat()
            )

        logger.warning(f"Code verification failed for {request.function_name}: {errors}")

        # Step 2: If auto_fix is enabled, try LLM fix
        suggested_code = None
        explanation = None

        if request.auto_fix:
            logger.info(f"Attempting AI fix for: {request.function_name}")
            fix_result = await _fix_code_with_llm(
                request.code,
                request.function_name,
                request.description,
                errors
            )
            suggested_code = fix_result["suggested_code"]
            explanation = fix_result["explanation"]

            # If we got a suggested fix, verify it compiles too
            if suggested_code:
                fix_errors = _compile_python_code(suggested_code, request.function_name)
                if fix_errors:
                    logger.warning(f"Suggested fix still has errors: {fix_errors}")
                    # Keep the suggestion anyway (it might be better than original)

        return CodeVerificationResponse(
            is_valid=False,
            errors=errors,
            warnings=warnings,
            suggested_code=suggested_code,
            explanation=explanation,
            verified_at=datetime.utcnow().isoformat()
        )

    except Exception as e:
        logger.error(f"Code verification failed: {e}")
        raise HTTPException(status_code=500, detail=f"Code verification failed: {str(e)}")


# =============================================================================
# Helper Functions
# =============================================================================

def _strip_sensitive_data(config: Dict[str, Any]) -> Dict[str, Any]:
    """Remove sensitive data like API keys from export."""
    import copy
    cleaned = copy.deepcopy(config)

    # List of sensitive keys to remove or redact
    sensitive_keys = ["api_key", "webhook_url", "connection_string", "token", "password", "secret"]

    def clean_dict(d):
        if isinstance(d, dict):
            for key in list(d.keys()):
                if any(sensitive in key.lower() for sensitive in sensitive_keys):
                    d[key] = "REDACTED"
                else:
                    clean_dict(d[key])
        elif isinstance(d, list):
            for item in d:
                clean_dict(item)

    clean_dict(cleaned)
    return cleaned
