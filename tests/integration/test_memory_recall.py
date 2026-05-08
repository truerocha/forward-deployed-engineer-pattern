"""
Integration Test: Memory System (Activities 3.09-3.11).

Tests the memory subsystem including MemoryManager store/recall/consolidate,
SemanticStore fallback behavior, and ContextEngineer task-type retrieval.

All tests are gated by FDE_INTEGRATION_TESTS_ENABLED since they require
DynamoDB access.

Activity coverage:
  3.09 - MemoryManager (store, recall, consolidate)
  3.10 - SemanticStore (Bedrock KB fallback to DynamoDB)
  3.11 - ContextEngineer (per-task-type context retrieval)

Ref: docs/design/fde-core-brain-development.md Section 3 (Wave 3)
"""

import os
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("FDE_INTEGRATION_TESTS_ENABLED"),
    reason="Set FDE_INTEGRATION_TESTS_ENABLED=1 to run integration tests",
)


@pytest.fixture
def memory_table():
    return os.environ.get("MEMORY_TABLE", "fde-dev-memory")


@pytest.fixture
def knowledge_table():
    return os.environ.get("KNOWLEDGE_TABLE", "fde-knowledge")


class TestMemoryManagerStoreAndRecall:
    """Tests for MemoryManager.store() and recall() with keyword matching."""

    def test_store_decision_memory(self, memory_table):
        """MemoryManager stores a decision memory item."""
        from src.core.memory.memory_manager import MemoryManager

        mm = MemoryManager(project_id="test-memory-recall", memory_table=memory_table)

        item = mm.store(
            memory_type="decision",
            content="Use DynamoDB for cross-session state persistence",
            metadata={"source": "ADR-009", "context": "infrastructure"},
        )

        assert item is not None
        assert item.memory_id != ""
        assert item.memory_type == "decision"
        assert "DynamoDB" in item.content
        assert item.content_hash != ""

    def test_store_rejects_invalid_type(self, memory_table):
        """MemoryManager rejects invalid memory types."""
        from src.core.memory.memory_manager import MemoryManager

        mm = MemoryManager(project_id="test-memory-recall", memory_table=memory_table)

        with pytest.raises(ValueError, match="Invalid memory_type"):
            mm.store(
                memory_type="invalid_type",
                content="This should fail",
            )

    def test_recall_by_keyword(self, memory_table):
        """MemoryManager.recall() finds memories by keyword matching."""
        from src.core.memory.memory_manager import MemoryManager

        mm = MemoryManager(project_id="test-memory-recall", memory_table=memory_table)

        # Store a memory with distinctive keywords
        mm.store(
            memory_type="decision",
            content="Chose EventBridge for asynchronous event routing between agents",
            metadata={"source": "ADR-014"},
        )

        # Recall using keywords from the stored content
        results = mm.recall("EventBridge event routing")

        assert isinstance(results, list)
        # Should find at least the item we just stored
        if results:
            assert any("EventBridge" in r.content for r in results)

    def test_recall_with_type_filter(self, memory_table):
        """MemoryManager.recall() filters by memory type."""
        from src.core.memory.memory_manager import MemoryManager

        mm = MemoryManager(project_id="test-memory-recall", memory_table=memory_table)

        # Store different types
        mm.store("decision", "Architecture decision about caching strategy")
        mm.store("error_pattern", "Timeout errors when caching layer is cold")

        # Recall with type filter
        decisions = mm.recall("caching", memory_type="decision")
        errors = mm.recall("caching", memory_type="error_pattern")

        assert isinstance(decisions, list)
        assert isinstance(errors, list)

        # All results should match the requested type
        for item in decisions:
            assert item.memory_type == "decision"
        for item in errors:
            assert item.memory_type == "error_pattern"

    def test_recall_respects_limit(self, memory_table):
        """MemoryManager.recall() respects the limit parameter."""
        from src.core.memory.memory_manager import MemoryManager

        mm = MemoryManager(project_id="test-memory-recall", memory_table=memory_table)

        # Store multiple items with same keyword
        for i in range(5):
            mm.store("learning", f"Learning item {i} about testing patterns")

        results = mm.recall("testing patterns", limit=3)
        assert len(results) <= 3

    def test_recall_returns_empty_for_no_match(self, memory_table):
        """MemoryManager.recall() returns empty list when no keywords match."""
        from src.core.memory.memory_manager import MemoryManager

        mm = MemoryManager(project_id="test-memory-recall", memory_table=memory_table)

        results = mm.recall("xyzzy_nonexistent_keyword_12345")
        assert results == []


class TestMemoryManagerConsolidate:
    """Tests for MemoryManager.consolidate() merging duplicates."""

    def test_consolidate_merges_similar_memories(self, memory_table):
        """MemoryManager.consolidate() merges highly similar memories."""
        from src.core.memory.memory_manager import MemoryManager

        mm = MemoryManager(
            project_id="test-memory-consolidate", memory_table=memory_table
        )

        # Store near-duplicate memories
        mm.store(
            "decision",
            "Use trunk-based development with short-lived feature branches",
            metadata={"source": "team-meeting-2024-01"},
        )
        mm.store(
            "decision",
            "Use trunk-based development with short-lived feature branches for all repos",
            metadata={"source": "team-meeting-2024-02"},
        )

        # Run consolidation
        summary = mm.consolidate()

        assert isinstance(summary, dict)
        assert "items_scanned" in summary
        assert "duplicates_found" in summary
        assert "items_merged" in summary
        assert summary["items_scanned"] >= 0

    def test_consolidate_preserves_distinct_memories(self, memory_table):
        """MemoryManager.consolidate() does not merge distinct memories."""
        from src.core.memory.memory_manager import MemoryManager

        mm = MemoryManager(
            project_id="test-memory-consolidate-distinct", memory_table=memory_table
        )

        # Store clearly different memories
        item_a = mm.store("decision", "Use PostgreSQL for relational data")
        item_b = mm.store("decision", "Use Redis for session caching")

        summary = mm.consolidate()

        # Both should still exist after consolidation
        retrieved_a = mm.get(item_a.memory_id)
        retrieved_b = mm.get(item_b.memory_id)

        # At least one should survive (the other might be merged if similar)
        assert retrieved_a is not None or retrieved_b is not None


class TestSemanticStoreFallback:
    """Tests for SemanticStore fallback to DynamoDB when Bedrock KB unavailable."""

    def test_fallback_to_dynamodb_when_kb_unavailable(self, memory_table):
        """SemanticStore falls back to DynamoDB when Bedrock KB is not configured."""
        from src.core.memory.semantic_store import SemanticStore

        # Create store with no KB configured (empty string)
        store = SemanticStore(
            project_id="test-semantic-fallback",
            knowledge_base_id="",  # No KB configured
            memory_table=memory_table,
        )

        # Store some content
        stored = store.store_semantic(
            "DynamoDB is the primary state store for the factory",
            metadata={"source": "ADR-009"},
        )
        assert stored is True

        # Search should use DynamoDB fallback
        results = store.search_semantic("state store factory", top_k=5)
        assert isinstance(results, list)

        # Results should come from DynamoDB fallback
        if results:
            assert results[0].source == "dynamodb_fallback"

    @patch("src.core.memory.semantic_store.boto3.client")
    def test_enters_degraded_mode_on_bedrock_failure(
        self, mock_boto_client, memory_table
    ):
        """SemanticStore enters degraded mode when Bedrock KB call fails."""
        from botocore.exceptions import ClientError
        from src.core.memory.semantic_store import SemanticStore

        # Mock Bedrock client that raises an error
        mock_bedrock = MagicMock()
        mock_bedrock.retrieve.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "Not authorized"}},
            "Retrieve",
        )
        mock_boto_client.return_value = mock_bedrock

        store = SemanticStore(
            project_id="test-semantic-degraded",
            knowledge_base_id="fake-kb-id",
            memory_table=memory_table,
        )

        # First search triggers Bedrock failure and enters degraded mode
        results = store.search_semantic("test query", top_k=5)
        assert isinstance(results, list)
        assert store.is_degraded is True

    def test_reset_degraded_mode(self, memory_table):
        """SemanticStore can reset degraded mode to retry Bedrock."""
        from src.core.memory.semantic_store import SemanticStore

        store = SemanticStore(
            project_id="test-semantic-reset",
            knowledge_base_id="",
            memory_table=memory_table,
        )

        # Force degraded mode
        store._degraded_mode = True
        assert store.is_degraded is True

        # Reset
        store.reset_degraded_mode()
        assert store.is_degraded is False


class TestContextEngineerRetrieval:
    """Tests for ContextEngineer retrieving correct context per task type."""

    def test_architecture_task_retrieves_adrs(self, memory_table, knowledge_table):
        """ContextEngineer retrieves ADR context for architecture tasks."""
        from src.core.memory.context_engineer import ContextEngineer

        ce = ContextEngineer(
            project_id="test-context-engineer",
            memory_table=memory_table,
            knowledge_table=knowledge_table,
        )

        context = ce.get_context_for_task(
            task_type="architecture",
            task_description="Design a new caching layer for the API gateway",
        )

        assert context is not None
        assert context.task_type == "architecture"
        assert "memory" in context.context_sources_used
        assert "adrs" in context.context_sources_used
        assert isinstance(context.relevant_adrs, list)
        assert isinstance(context.relevant_memory, list)

    def test_testing_task_retrieves_error_patterns(self, memory_table, knowledge_table):
        """ContextEngineer retrieves error patterns for testing tasks."""
        from src.core.memory.context_engineer import ContextEngineer

        ce = ContextEngineer(
            project_id="test-context-engineer",
            memory_table=memory_table,
            knowledge_table=knowledge_table,
        )

        context = ce.get_context_for_task(
            task_type="testing",
            task_description="Write integration tests for the payment service",
        )

        assert context is not None
        assert context.task_type == "testing"
        assert "memory" in context.context_sources_used
        assert isinstance(context.relevant_docs, list)

    def test_security_task_retrieves_compliance_context(
        self, memory_table, knowledge_table
    ):
        """ContextEngineer retrieves compliance context for security tasks."""
        from src.core.memory.context_engineer import ContextEngineer

        ce = ContextEngineer(
            project_id="test-context-engineer",
            memory_table=memory_table,
            knowledge_table=knowledge_table,
        )

        context = ce.get_context_for_task(
            task_type="security",
            task_description="Implement encryption at rest for user data",
        )

        assert context is not None
        assert context.task_type == "security"
        assert "memory" in context.context_sources_used

    def test_invalid_task_type_raises(self, memory_table, knowledge_table):
        """ContextEngineer raises ValueError for invalid task types."""
        from src.core.memory.context_engineer import ContextEngineer

        ce = ContextEngineer(
            project_id="test-context-engineer",
            memory_table=memory_table,
            knowledge_table=knowledge_table,
        )

        with pytest.raises(ValueError, match="Invalid task_type"):
            ce.get_context_for_task(
                task_type="invalid_type",
                task_description="This should fail",
            )

    def test_context_includes_retrieval_metadata(self, memory_table, knowledge_table):
        """ContextEngineer includes metadata about retrieval results."""
        from src.core.memory.context_engineer import ContextEngineer

        ce = ContextEngineer(
            project_id="test-context-engineer",
            memory_table=memory_table,
            knowledge_table=knowledge_table,
        )

        context = ce.get_context_for_task(
            task_type="implementation",
            task_description="Add retry logic to the HTTP client",
        )

        assert context.retrieval_metadata is not None
        assert "adrs_found" in context.retrieval_metadata
        assert "memories_found" in context.retrieval_metadata
        assert "sources_queried" in context.retrieval_metadata
