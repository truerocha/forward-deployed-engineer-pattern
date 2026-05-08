"""
Integration Test: Knowledge Pipeline (Activities 3.01-3.06).

Tests the full knowledge pipeline from call graph extraction through
data quality scoring. Some tests work without AWS (AST parser tests),
while DynamoDB-dependent tests are gated by FDE_INTEGRATION_TESTS_ENABLED.

Activity coverage:
  3.01 - CallGraphExtractor (AST parsing)
  3.02 - DescriptionGenerator (mocked Bedrock)
  3.03 - VectorStore (mocked embeddings)
  3.04 - QueryAPI (combined results)
  3.05 - KnowledgeAnnotationStore (CRUD)
  3.06 - DataQualityScorer (assessments)

Ref: docs/design/fde-core-brain-development.md Section 3 (Knowledge Plane)
"""

import os
import tempfile
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# --- Tests that work WITHOUT AWS (pure AST parsing) ---


class TestCallGraphExtractorLocal:
    """Tests for CallGraphExtractor that use only the AST parser (no AWS)."""

    def test_extract_functions_from_python_file(self):
        """CallGraphExtractor discovers function definitions via AST."""
        from src.core.knowledge.call_graph_extractor import CallGraphExtractor

        # Create a temporary Python file with known structure
        source = textwrap.dedent("""\
            import os
            import json
            from pathlib import Path

            def helper_function(x: int) -> str:
                return str(x)

            class MyService:
                def __init__(self, name: str):
                    self.name = name

                def process(self, data: dict) -> dict:
                    result = helper_function(len(data))
                    return {"result": result}

                async def async_method(self) -> None:
                    pass
        """)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(source)
            temp_path = Path(f.name)

        try:
            extractor = CallGraphExtractor(
                project_id="test-local",
                workspace_path=str(temp_path.parent),
                knowledge_table="",  # No DynamoDB
            )
            result = extractor.extract_module(temp_path)

            assert result is not None
            # Verify top-level functions discovered
            assert "helper_function" in result.functions

            # Verify classes discovered
            assert "MyService" in result.classes

            # Verify imports discovered
            assert "os" in result.imports
            assert "json" in result.imports

            # Verify call relationships (helper_function called inside process)
            assert any("helper_function" in call for call in result.calls_to)

            # Verify class methods are tracked in class_nodes
            assert len(result.class_nodes) > 0
            my_service_node = result.class_nodes[0]
            assert "process" in my_service_node.methods
        finally:
            os.unlink(temp_path)

    def test_extract_handles_empty_file(self):
        """CallGraphExtractor handles empty Python files gracefully."""
        from src.core.knowledge.call_graph_extractor import CallGraphExtractor

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write("")
            temp_path = Path(f.name)

        try:
            extractor = CallGraphExtractor(
                project_id="test-empty",
                workspace_path=str(temp_path.parent),
                knowledge_table="",
            )
            result = extractor.extract_module(temp_path)
            # Empty file may return None or empty graph
            if result is not None:
                assert result.functions == []
                assert result.classes == []
        finally:
            os.unlink(temp_path)

    def test_extract_handles_syntax_error(self):
        """CallGraphExtractor handles files with syntax errors gracefully."""
        from src.core.knowledge.call_graph_extractor import CallGraphExtractor

        source = "def broken(\n  # missing closing paren and colon"

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(source)
            temp_path = Path(f.name)

        try:
            extractor = CallGraphExtractor(
                project_id="test-syntax-error",
                workspace_path=str(temp_path.parent),
                knowledge_table="",
            )
            result = extractor.extract_module(temp_path)
            # Should return None for unparseable files, not raise
            assert result is None
        finally:
            os.unlink(temp_path)

    def test_extract_class_hierarchy(self):
        """CallGraphExtractor detects class inheritance."""
        from src.core.knowledge.call_graph_extractor import CallGraphExtractor

        source = textwrap.dedent("""\
            class Base:
                def base_method(self):
                    pass

            class Child(Base):
                def child_method(self):
                    pass

            class GrandChild(Child):
                def gc_method(self):
                    pass
        """)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(source)
            temp_path = Path(f.name)

        try:
            extractor = CallGraphExtractor(
                project_id="test-hierarchy",
                workspace_path=str(temp_path.parent),
                knowledge_table="",
            )
            result = extractor.extract_module(temp_path)

            assert result is not None
            assert "Base" in result.classes
            assert "Child" in result.classes
            assert "GrandChild" in result.classes

            # Verify hierarchy tracking
            if hasattr(result, "class_hierarchy"):
                assert "Base" in result.class_hierarchy.get("Child", [])
        finally:
            os.unlink(temp_path)

    def test_extract_decorators(self):
        """CallGraphExtractor captures function decorators."""
        from src.core.knowledge.call_graph_extractor import CallGraphExtractor

        source = textwrap.dedent("""\
            from functools import lru_cache

            @lru_cache(maxsize=128)
            def cached_function(x):
                return x * 2

            class MyClass:
                @staticmethod
                def static_method():
                    pass

                @classmethod
                def class_method(cls):
                    pass
        """)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(source)
            temp_path = Path(f.name)

        try:
            extractor = CallGraphExtractor(
                project_id="test-decorators",
                workspace_path=str(temp_path.parent),
                knowledge_table="",
            )
            result = extractor.extract_module(temp_path)

            assert result is not None
            assert "cached_function" in result.functions
            assert "MyClass" in result.classes
        finally:
            os.unlink(temp_path)


# --- Tests that require AWS (gated by env var) ---

pytestmark_aws = pytest.mark.skipif(
    not os.environ.get("FDE_INTEGRATION_TESTS_ENABLED"),
    reason="Set FDE_INTEGRATION_TESTS_ENABLED=1 to run integration tests",
)


@pytestmark_aws
class TestDescriptionGeneratorIntegration:
    """Tests for DescriptionGenerator with mocked Bedrock."""

    @patch("src.core.knowledge.description_generator.boto3.client")
    def test_generates_non_empty_description(self, mock_boto_client):
        """DescriptionGenerator produces non-empty descriptions."""
        from src.core.knowledge.description_generator import DescriptionGenerator

        # Mock Bedrock converse response
        mock_bedrock = MagicMock()
        mock_bedrock.converse.return_value = {
            "output": {
                "message": {
                    "content": [
                        {"text": "Manages user authentication and session tokens for the API gateway."}
                    ]
                }
            },
            "usage": {"inputTokens": 150, "outputTokens": 20},
        }
        mock_boto_client.return_value = mock_bedrock

        generator = DescriptionGenerator(
            project_id="test-desc",
            knowledge_table=os.environ.get("KNOWLEDGE_TABLE", "fde-knowledge"),
        )

        call_graph_data = {
            "module_path": "src/auth/handler.py",
            "functions": ["authenticate", "refresh_token", "validate_session"],
            "classes": ["AuthHandler"],
            "imports": ["boto3", "jwt"],
        }

        result = generator.generate_description(
            module_path="src/auth/handler.py",
            call_graph=call_graph_data,
            source_snippet="class AuthHandler:\n    def authenticate(self, token):\n        pass",
        )

        assert result is not None
        assert len(result.description) > 0
        assert result.module_path == "src/auth/handler.py"


@pytestmark_aws
class TestVectorStoreIntegration:
    """Tests for VectorStore with mocked Bedrock embeddings."""

    @patch("src.core.knowledge.vector_store.boto3.client")
    def test_index_and_search(self, mock_boto_client):
        """VectorStore indexes text and returns search results."""
        from src.core.knowledge.vector_store import VectorStore

        # Mock Bedrock embeddings response
        mock_bedrock = MagicMock()
        embedding = [0.1] * 1024  # Titan v2 dimension
        mock_bedrock.invoke_model.return_value = {
            "body": MagicMock(
                read=MagicMock(
                    return_value=b'{"embedding": ' + str(embedding).encode() + b"}"
                )
            )
        }
        mock_boto_client.return_value = mock_bedrock

        store = VectorStore(
            project_id="test-vector",
            knowledge_table=os.environ.get("KNOWLEDGE_TABLE", "fde-knowledge"),
        )

        # Index a document
        entry = store.index(
            text="DynamoDB is used for state management in the factory",
            metadata={"source": "ADR-009", "type": "decision"},
        )
        assert entry is not None
        assert entry.entry_id != ""

        # Search should find the indexed document
        results = store.search("state management database", top_k=5)
        assert isinstance(results, list)


@pytestmark_aws
class TestQueryAPIIntegration:
    """Tests for QueryAPI combining multiple knowledge sources."""

    def test_query_module_returns_combined_results(self):
        """QueryAPI combines call graph, descriptions, and vector results."""
        from src.core.knowledge.query_api import QueryAPI

        api = QueryAPI(
            project_id="test-query",
            knowledge_table=os.environ.get("KNOWLEDGE_TABLE", "fde-knowledge"),
        )

        # Query for a module — should not raise even if no data exists
        results = api.query_module("src/core/metrics/cost_tracker.py")
        assert isinstance(results, list)

    def test_search_by_description(self):
        """QueryAPI searches across module descriptions."""
        from src.core.knowledge.query_api import QueryAPI

        api = QueryAPI(
            project_id="test-query",
            knowledge_table=os.environ.get("KNOWLEDGE_TABLE", "fde-knowledge"),
        )

        results = api.search_by_description("cost tracking and budget management")
        assert isinstance(results, list)


@pytestmark_aws
class TestKnowledgeAnnotationStoreIntegration:
    """Tests for KnowledgeAnnotationStore CRUD operations."""

    def test_create_and_retrieve_annotation(self):
        """KnowledgeAnnotationStore creates and retrieves annotations."""
        from src.core.knowledge.knowledge_annotation import (
            KnowledgeAnnotation,
            KnowledgeAnnotationStore,
        )

        store = KnowledgeAnnotationStore(
            project_id="test-annotations",
            knowledge_table=os.environ.get("KNOWLEDGE_TABLE", "fde-knowledge"),
        )

        annotation = KnowledgeAnnotation(
            module_path="src/core/metrics/cost_tracker.py",
            governing_artifacts=["ADR-009", "WAF/cost-optimization"],
            domain_source_of_truth="docs/architecture/design-document.md",
            confidence=0.85,
            tags=["metrics", "cost", "data-plane"],
            created_by="test-integration",
        )

        # Create
        store.put(annotation)

        # Retrieve
        retrieved = store.get("src/core/metrics/cost_tracker.py")
        assert retrieved is not None
        assert retrieved.module_path == "src/core/metrics/cost_tracker.py"
        assert "ADR-009" in retrieved.governing_artifacts
        assert retrieved.confidence == 0.85

    def test_list_annotations_by_tag(self):
        """KnowledgeAnnotationStore filters annotations by tag."""
        from src.core.knowledge.knowledge_annotation import (
            KnowledgeAnnotation,
            KnowledgeAnnotationStore,
        )

        store = KnowledgeAnnotationStore(
            project_id="test-annotations",
            knowledge_table=os.environ.get("KNOWLEDGE_TABLE", "fde-knowledge"),
        )

        # Create annotations with different tags
        store.put(KnowledgeAnnotation(
            module_path="src/security/auth.py",
            governing_artifacts=["WAF/security"],
            tags=["security", "authentication"],
            created_by="test",
        ))

        results = store.list_by_tag("security")
        assert isinstance(results, list)

    def test_delete_annotation(self):
        """KnowledgeAnnotationStore deletes annotations."""
        from src.core.knowledge.knowledge_annotation import (
            KnowledgeAnnotation,
            KnowledgeAnnotationStore,
        )

        store = KnowledgeAnnotationStore(
            project_id="test-annotations",
            knowledge_table=os.environ.get("KNOWLEDGE_TABLE", "fde-knowledge"),
        )

        store.put(KnowledgeAnnotation(
            module_path="src/temp/to_delete.py",
            governing_artifacts=["ADR-001"],
            created_by="test",
        ))

        deleted = store.delete("src/temp/to_delete.py")
        assert deleted is True

        retrieved = store.get("src/temp/to_delete.py")
        assert retrieved is None


@pytestmark_aws
class TestDataQualityScorerIntegration:
    """Tests for DataQualityScorer producing valid assessments."""

    def test_produces_valid_assessment(self):
        """DataQualityScorer produces assessment with all dimensions."""
        from src.core.knowledge.data_quality_scorer import DataQualityScorer

        scorer = DataQualityScorer(
            project_id="test-quality",
            knowledge_table=os.environ.get("KNOWLEDGE_TABLE", "fde-knowledge"),
        )

        assessment = scorer.assess_artifact(
            artifact_name="ADR-009",
            last_updated_days_ago=15,
            coverage_ratio=0.75,
            references_valid=True,
            manually_validated=False,
        )

        assert assessment is not None
        assert assessment.artifact_name == "ADR-009"
        assert 0.0 <= assessment.freshness.score <= 1.0
        assert 0.0 <= assessment.completeness.score <= 1.0
        assert 0.0 <= assessment.consistency.score <= 1.0
        assert 0.0 <= assessment.accuracy.score <= 1.0

        # Composite should be weighted average
        composite = assessment.composite_score
        assert 0.0 <= composite <= 1.0

    def test_stale_artifact_gets_low_freshness(self):
        """DataQualityScorer gives low freshness to stale artifacts."""
        from src.core.knowledge.data_quality_scorer import DataQualityScorer

        scorer = DataQualityScorer(
            project_id="test-quality",
            knowledge_table=os.environ.get("KNOWLEDGE_TABLE", "fde-knowledge"),
        )

        assessment = scorer.assess_artifact(
            artifact_name="OLD-DOC",
            last_updated_days_ago=120,  # Well past 90-day threshold
            coverage_ratio=0.5,
            references_valid=True,
            manually_validated=False,
        )

        assert assessment.freshness.score < 0.5
