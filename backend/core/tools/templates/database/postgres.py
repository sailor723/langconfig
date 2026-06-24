# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
DATABASE_POSTGRES_TEMPLATE - Database category tool template.

Extracted from templates.py on 2026-06-24.
"""
from typing import Any
from models.custom_tool import ToolType
from core.tools.templates import ToolTemplate, ToolTemplateRegistry


DATABASE_POSTGRES_TEMPLATE = ToolTemplate(
    template_id="database_postgres",
    name="PostgreSQL Query",
    description="Execute SQL queries on PostgreSQL databases",
    category="database",
    tool_type=ToolType.DATABASE,
    icon="💾",
    priority=65,
    is_featured=False,
    config_template={
        "tool_type": "database",
        "template_type": "database_postgres",
        "implementation_config": {
            "db_type": "postgres",
            "connection_string": "",  # USER MUST PROVIDE (encrypted)
            "query_template": "SELECT * FROM {table} WHERE id = {id}",
            "read_only": True,
            "max_rows": 100,
            "timeout": 30
        }
    },
    input_schema_template={
        "type": "object",
        "properties": {
            "table": {
                "type": "string",
                "description": "Table name to query"
            },
            "id": {
                "type": "string",
                "description": "ID to lookup"
            }
        },
        "required": ["table", "id"]
    },
    required_user_fields=["connection_string"],
    setup_instructions="""
1. Prepare your PostgreSQL connection string:
   postgresql://username:password@host:port/database

2. For security, enable read-only mode to prevent data modification

3. Use parameterized queries with {variable} placeholders to prevent SQL injection

Warning: Connection strings are encrypted but should use read-only database users when possible.
""",
    example_use_cases=[
        "Query database for user information",
        "Retrieve product data for recommendations",
        "Lookup order status and details",
        "Fetch analytics data",
        "Verify data before processing"
    ],
    tags=["database", "sql", "postgresql", "query", "data"]
)


# Register on import
ToolTemplateRegistry.register(DATABASE_POSTGRES_TEMPLATE)
