# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Base mixin for ToolFactory: tool dispatch, validation, Pydantic schema
building, auth headers, error formatting, and SSRF protection.

The concrete ``ToolFactory`` class (defined in the package ``__init__``)
subclasses this mixin. Staticmethod bodies reference ``ToolFactory`` by its
bare name, which is late-bound into this module's globals by
``_bind_runtime`` (see below).
"""

import json
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from langchain_core.tools import BaseTool
from pydantic import create_model as create_pydantic_model, Field as PydanticField

from .models import LangChainRequirements, ToolTypes, ValidationResult
from .shared import logger


class _ToolFactoryBaseMixin:

    @staticmethod
    async def create_tool(
        tool_config: Dict[str, Any],
        project_id: Optional[int] = None
    ) -> BaseTool:
        """
        Create a LangChain tool from configuration.

        Args:
            tool_config: Tool configuration dictionary
            project_id: Optional project ID for scoping

        Returns:
            Configured LangChain BaseTool instance

        Raises:
            ValueError: If configuration is invalid
            NotImplementedError: If tool type is not supported
        """
        # Validate configuration
        validation_result = ToolFactory.validate_tool_config(tool_config)
        if not validation_result.is_valid:
            raise ValueError(f"Invalid tool configuration: {', '.join(validation_result.errors)}")

        # Validate implementation-specific configuration
        impl_config = tool_config.get("implementation_config", {})
        impl_errors = ToolFactory._validate_tool_implementation(tool_config, impl_config)
        if impl_errors:
            raise ValueError(f"Invalid implementation config: {', '.join(impl_errors)}")

        # Extract tool type
        tool_type = tool_config.get("tool_type", "api")
        template_type = tool_config.get("template_type", "custom")

        logger.info(f"Creating custom tool: {tool_config['name']} (type: {tool_type})")

        # Route to appropriate tool creator based on type
        if tool_type == ToolTypes.API:
            return await ToolFactory._create_api_tool(tool_config, project_id)
        elif tool_type == ToolTypes.NOTIFICATION:
            return await ToolFactory._create_notification_tool(tool_config, project_id)
        elif tool_type == ToolTypes.IMAGE_VIDEO:
            return await ToolFactory._create_image_video_tool(tool_config, project_id)
        elif tool_type == ToolTypes.DATABASE:
            return await ToolFactory._create_database_tool(tool_config, project_id)
        elif tool_type == ToolTypes.DATA_TRANSFORM:
            return await ToolFactory._create_data_transform_tool(tool_config, project_id)
        elif tool_type == ToolTypes.PYTHON_FUNCTION or tool_type == "python_function":
            return await ToolFactory._create_python_function_tool(tool_config, project_id)
        else:
            raise NotImplementedError(f"Tool type '{tool_type}' is not yet implemented")

    @staticmethod
    def validate_tool_config(tool_config: Dict[str, Any]) -> ValidationResult:
        """
        Validate tool configuration.

        Args:
            tool_config: Tool configuration to validate

        Returns:
            ValidationResult with details
        """
        # Use LangChain requirements validator
        return LangChainRequirements.validate(tool_config)

    @staticmethod
    def get_langchain_requirements() -> Dict[str, Any]:
        """
        Get LangChain compatibility requirements.

        Returns:
            Dictionary of required and recommended fields
        """
        return {
            "required_fields": LangChainRequirements.REQUIRED_FIELDS,
            "recommended_fields": LangChainRequirements.RECOMMENDED_FIELDS,
            "description": "Fields required for LangChain tool compatibility"
        }

    @staticmethod
    def _create_pydantic_args_schema(input_schema: Dict[str, Any], tool_name: str) -> type:
        """
        Create a Pydantic model from JSON Schema for tool arguments.

        Uses caching to avoid recreating the same schema multiple times.

        Args:
            input_schema: JSON Schema definition
            tool_name: Name of the tool (for model naming)

        Returns:
            Pydantic model class (cached if possible)
        """
        # Generate cache key from tool_name and input_schema
        import hashlib
        schema_str = json.dumps(input_schema, sort_keys=True)
        cache_key = f"{tool_name}:{hashlib.md5(schema_str.encode()).hexdigest()}"

        # Check cache first
        if cache_key in ToolFactory._schema_cache:
            logger.debug(f"Using cached Pydantic schema for {tool_name}")
            return ToolFactory._schema_cache[cache_key]

        # Extract properties from JSON Schema
        properties = input_schema.get("properties", {})
        required_fields = input_schema.get("required", [])

        # Build Pydantic field definitions
        field_definitions = {}
        for field_name, field_spec in properties.items():
            field_type = field_spec.get("type", "string")
            description = field_spec.get("description", "")

            # Map JSON Schema types to Python types
            python_type = {
                "string": str,
                "integer": int,
                "number": float,
                "boolean": bool,
                "array": list,
                "object": dict
            }.get(field_type, str)

            # Determine if field is optional
            is_required = field_name in required_fields

            if is_required:
                field_definitions[field_name] = (python_type, PydanticField(..., description=description))
            else:
                default_value = field_spec.get("default", None)
                field_definitions[field_name] = (python_type, PydanticField(default=default_value, description=description))

        # Create Pydantic model dynamically
        model_name = f"{tool_name.title().replace('_', '')}Args"
        try:
            # Create Pydantic model using create_model helper
            args_model = create_pydantic_model(model_name, **field_definitions)

            # Store in cache for future use
            ToolFactory._schema_cache[cache_key] = args_model
            logger.debug(f"Cached Pydantic schema for {tool_name} (cache size: {len(ToolFactory._schema_cache)})")

            return args_model
        except Exception as e:
            logger.warning(f"Failed to create Pydantic model for {tool_name}: {e}. Using generic args.")
            # Fallback: create a simple model (don't cache fallback schemas)
            fallback_model = create_pydantic_model(model_name, **{"input": (str, PydanticField(..., description="Tool input"))})
            return fallback_model

    @staticmethod
    def _build_auth_headers(auth_config: Dict[str, Any]) -> Dict[str, str]:
        """
        Build authorization headers from authentication configuration.

        Supports:
        - API Key (header or query string)
        - Bearer token
        - Basic authentication

        Args:
            auth_config: Authentication configuration dict

        Returns:
            Dictionary of headers with authentication
        """
        import base64

        headers = {"Content-Type": "application/json"}

        auth_type = auth_config.get("type", "")

        if auth_type == "api_key":
            if auth_config.get("location") == "header":
                key_name = auth_config.get("key", "Authorization")
                key_value = auth_config.get("value", "")
                headers[key_name] = key_value
        elif auth_type == "bearer":
            token = auth_config.get("token", "")
            headers["Authorization"] = f"Bearer {token}"
        elif auth_type == "basic":
            username = auth_config.get("username", "")
            password = auth_config.get("password", "")
            credentials = f"{username}:{password}"
            encoded = base64.b64encode(credentials.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"

        return headers

    @staticmethod
    def _format_error(error: Exception, context: str = "") -> str:
        """
        Format error messages consistently across all tools.

        Args:
            error: The exception that occurred
            context: Optional context about where/why the error occurred

        Returns:
            Formatted error string
        """
        error_msg = str(error)
        if context:
            return f"Error: {error_msg} ({context})"
        return f"Error: {error_msg}"

    @staticmethod
    def _validate_tool_implementation(tool_config: Dict[str, Any], impl_config: Dict[str, Any]) -> List[str]:
        """
        Validate implementation configuration before tool creation.

        Performs tool-type-specific validation to catch configuration errors early.

        Args:
            tool_config: Tool configuration dictionary
            impl_config: Implementation-specific configuration

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []
        tool_type = tool_config.get("tool_type", "")

        if tool_type == ToolTypes.API:
            if not impl_config.get("url"):
                errors.append("API tool requires 'url' in implementation_config")
            if not impl_config.get("method"):
                errors.append("API tool requires 'method' in implementation_config")

        elif tool_type == ToolTypes.NOTIFICATION:
            provider = impl_config.get("provider", "")
            if provider == "slack":
                if not impl_config.get("webhook_url"):
                    errors.append("Slack notification requires 'webhook_url'")
            elif provider == "discord":
                if not impl_config.get("webhook_url") and not impl_config.get("webhooks"):
                    errors.append("Discord notification requires 'webhook_url' or 'webhooks' dict")
            elif provider == "wordpress":
                if not impl_config.get("site_url") or not impl_config.get("username") or not impl_config.get("app_password"):
                    errors.append("WordPress tool requires 'site_url', 'username', and 'app_password'")

        elif tool_type == ToolTypes.DATABASE:
            if not impl_config.get("connection_string"):
                errors.append("Database tool requires 'connection_string'")
            db_type = impl_config.get("db_type", "")
            if db_type not in ["postgres", "postgresql", "mysql", "mongodb"]:
                errors.append(f"Unsupported database type: {db_type}")

        elif tool_type == ToolTypes.IMAGE_VIDEO:
            if not impl_config.get("provider"):
                errors.append("Image/video tool requires 'provider' (openai, google)")
            if not impl_config.get("model"):
                errors.append("Image/video tool requires 'model'")

        elif tool_type == ToolTypes.DATA_TRANSFORM:
            if not impl_config.get("input_format") or not impl_config.get("output_format"):
                errors.append("Data transform tool requires 'input_format' and 'output_format'")

        return errors

    @staticmethod
    def _validate_url_ssrf(url: str) -> bool:
        """
        Validate URL to prevent Server-Side Request Forgery (SSRF) attacks.

        Blocks requests to:
        - Private IP ranges (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
        - Localhost (127.0.0.0/8, ::1)
        - Cloud metadata endpoints (169.254.169.254, metadata.google.internal)

        Args:
            url: URL to validate

        Returns:
            True if URL is safe, False if it should be blocked

        Raises:
            ValueError: If URL targets internal/private resources
        """
        import ipaddress
        import socket

        try:
            parsed = urlparse(url)
            hostname = parsed.hostname

            if not hostname:
                raise ValueError("Invalid URL: No hostname found")

            # Block cloud metadata endpoints
            if hostname in ["169.254.169.254", "metadata.google.internal", "metadata", "169.254.169.254"]:
                raise ValueError(f"SSRF Protection: Access to cloud metadata endpoint blocked: {hostname}")

            # Resolve hostname to IP
            try:
                ip = socket.gethostbyname(hostname)
                ip_obj = ipaddress.ip_address(ip)

                # Block private IP ranges
                if ip_obj.is_private:
                    raise ValueError(f"SSRF Protection: Access to private IP address blocked: {ip}")

                # Block localhost
                if ip_obj.is_loopback:
                    raise ValueError(f"SSRF Protection: Access to localhost blocked: {ip}")

                # Block link-local addresses
                if ip_obj.is_link_local:
                    raise ValueError(f"SSRF Protection: Access to link-local address blocked: {ip}")

            except socket.gaierror:
                # If DNS resolution fails, allow it (might be valid external domain with temporary DNS issues)
                logger.warning(f"Could not resolve hostname for SSRF check: {hostname}")

            return True

        except ValueError as e:
            logger.error(f"SSRF validation failed for URL {url}: {e}")
            raise


def _bind_runtime() -> None:
    """Bind the concrete ToolFactory class into this module's globals.

    The staticmethod bodies reference the concrete class by its bare name
    (e.g. ``ToolFactory._schema_cache``, ``ToolFactory._create_api_tool``),
    which must resolve in this module's globals at call time. The concrete
    class is defined in the package ``__init__``, which imports this module
    first — hence this late binding avoids a circular import.
    """
    from core.tools.factory import ToolFactory
    globals()["ToolFactory"] = ToolFactory
