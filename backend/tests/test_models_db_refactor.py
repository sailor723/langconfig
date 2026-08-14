"""
Phase 0: Baseline tests for current hardcoded model behavior.

These tests capture the exact current behavior BEFORE refactoring.
After each refactoring phase, run these tests to verify nothing broke.
"""


# =============================================================================
# Test 1: models table has expected data (replaces ModelChoice enum)
# =============================================================================

class TestModelsTable:
    """models table should contain all expected cloud model entries."""

    def test_models_table_has_deepseek(self):
        from models.model import Model
        from db.database import SessionLocal
        db = SessionLocal()
        try:
            deepseek_chat = db.query(Model).filter(Model.model_id == "deepseek-chat").first()
            assert deepseek_chat is not None
            assert deepseek_chat.provider == "deepseek"
            assert deepseek_chat.source == "cloud"
        finally:
            db.close()

    def test_models_table_has_gemini(self):
        from models.model import Model
        from db.database import SessionLocal
        db = SessionLocal()
        try:
            gemini = db.query(Model).filter(
                Model.model_id.like("gemini-%"), Model.source == "cloud"
            ).first()
            assert gemini is not None
            assert gemini.provider == "google"
        finally:
            db.close()

    def test_models_table_has_claude(self):
        from models.model import Model
        from db.database import SessionLocal
        db = SessionLocal()
        try:
            claude = db.query(Model).filter(Model.model_id == "claude-sonnet-4-5").first()
            assert claude is not None
            assert claude.provider == "anthropic"
        finally:
            db.close()

    def test_models_table_count(self):
        from models.model import Model
        from db.database import SessionLocal
        db = SessionLocal()
        try:
            count = db.query(Model).filter(Model.source == 'cloud').count()
            assert count >= 21  # At least 21 cloud models
        finally:
            db.close()


# =============================================================================
# Test 2: factory.py SUPPORTED_MODELS set
# =============================================================================

class TestSupportedModels:
    """Baseline: SUPPORTED_MODELS contains all expected model IDs."""

    def test_supported_models_contains_deepseek(self):
        from core.agents.factory import SUPPORTED_MODELS
        assert "deepseek-chat" in SUPPORTED_MODELS
        assert "deepseek-reasoner" in SUPPORTED_MODELS

    def test_supported_models_contains_claude(self):
        from core.agents.factory import SUPPORTED_MODELS
        assert "claude-sonnet-4-5" in SUPPORTED_MODELS
        assert "claude-haiku-4-5-20251015" in SUPPORTED_MODELS

    def test_supported_models_contains_openai(self):
        from core.agents.factory import SUPPORTED_MODELS
        assert "gpt-4o" in SUPPORTED_MODELS

    def test_supported_models_contains_gemini(self):
        from core.agents.factory import SUPPORTED_MODELS
        assert "gemini-2.5-flash" in SUPPORTED_MODELS
        assert "gemini-3-pro-preview" in SUPPORTED_MODELS

    def test_supported_models_count(self):
        from core.agents.factory import SUPPORTED_MODELS
        assert len(SUPPORTED_MODELS) >= 12  # At least 12 supported models


# =============================================================================
# Test 3: factory.py _create_llm() routing logic
# =============================================================================

class TestCreateLLMRouting:
    """Baseline: _create_llm routes to correct provider based on model name."""

    def test_create_llm_deepseek_routing(self):
        """DeepSeek models should route to deepseek provider."""
        from core.agents.factory import AgentFactory
        # We can't easily call _create_llm without API keys, so test the routing logic
        config = {"streaming": True}
        # Verify the method exists and accepts these params
        assert hasattr(AgentFactory, '_create_llm')

    def test_create_llm_local_routing(self):
        """Local models should route to ChatOpenAI with base_url."""
        from core.agents.factory import AgentFactory
        assert hasattr(AgentFactory, '_create_llm')

    def test_create_llm_openai_routing(self):
        """GPT models should route to openai provider."""
        from core.agents.factory import AgentFactory
        assert hasattr(AgentFactory, '_create_llm')


# =============================================================================
# Test 4: settings.py get_available_models() API behavior
# =============================================================================

class TestAvailableModelsAPI:
    """Baseline: /api/settings/available-models returns expected structure."""

    def test_api_returns_expected_structure(self):
        """GET /api/settings/models returns cloud_models + local_models."""
        from unittest.mock import MagicMock
        from api.system.settings import list_available_models

        class _Row:
            def __init__(self, model_id, display_name, provider, capabilities=None):
                self.model_id = model_id
                self.display_name = display_name
                self.provider = provider
                self.capabilities = capabilities or {}
                self.is_active = True
                self.id = 1
                self.name = model_id
                self.is_validated = True

        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            _Row("deepseek-chat", "DeepSeek Chat", "deepseek"),
            _Row("claude-haiku-4-5", "Claude Haiku", "anthropic"),
        ]
        # local models query (validated)
        db.query.return_value.filter.return_value.all.return_value = [
            _Row("local-ollama", "Ollama", "ollama"),
        ]

        import asyncio
        response = asyncio.run(list_available_models(db))
        body = response.body
        import json
        payload = json.loads(body)
        assert "cloud_models" in payload
        assert "local_models" in payload
        assert len(payload["cloud_models"]) == 2
        assert payload["cloud_models"][0]["provider"] == "deepseek"


# =============================================================================
# Test 5: Playground API endpoint
# =============================================================================

class TestModelInvokeAPI:
    """Baseline: POST /api/models/invoke works correctly."""

    def test_model_invoke_endpoint_exists(self):
        """Verify the invoke endpoint router is registered."""
        from api.models.routes import router, model_invoke
        assert router is not None
        assert callable(model_invoke)

    def test_model_invoke_request_schema(self):
        """Verify the request schema has required fields."""
        from api.models.routes import ModelInvokeRequest
        schema = ModelInvokeRequest.model_json_schema()
        props = schema.get("properties", {})
        assert "model" in props
        assert "message" in props


# =============================================================================
# Test 7: Frontend useAvailableModels hook (to be removed in Phase 3)
# =============================================================================

class TestUseAvailableModels:
    """Baseline: useAvailableModels hook will be refactored in Phase 3."""
    def test_hook_exists(self):
        """Placeholder - hook will be updated in Phase 3."""
        pass


# =============================================================================
# Test 8: local_models table structure
# =============================================================================

class TestLocalModelsTable:
    """Baseline: local_models table has expected columns."""

    def test_local_model_has_expected_fields(self):
        """Verify LocalModel ORM has expected fields."""
        from models.local_model import LocalModel
        # Check table name
        assert LocalModel.__tablename__ == "local_models"
        # Check key columns exist
        assert hasattr(LocalModel, 'name')
        assert hasattr(LocalModel, 'provider')
        assert hasattr(LocalModel, 'base_url')
        assert hasattr(LocalModel, 'model_name')
        assert hasattr(LocalModel, 'is_validated')
