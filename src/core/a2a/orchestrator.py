"""
A2A Squad Orchestrator — Production Entrypoint for the AI Squad Pipeline.

Wires together all A2A components into a single cohesive execution path:
  - GrafoResiliente (workflow graph with DynamoDB checkpointing)
  - ResilientStateManager (retry + DLQ circuit breaker)
  - OpenTelemetry tracing (distributed traces via ADOT → X-Ray)
  - Agent Cards (explicit contract enforcement)
  - Squad Bridge (connects A2A protocol to Conductor squad composition)

This is the entrypoint invoked by:
  - ECS Task (production): via `python -m src.core.a2a.orchestrator`
  - EventBridge Rule → ECS RunTask (cloud-native trigger)
  - Local development: via `make a2a-run`

The orchestrator does NOT contain agent logic — it only routes tasks
between A2A servers and manages the workflow lifecycle.

Ref: ADR-034 (A2A Protocol), ADR-019 (Agentic Squad Architecture),
     ADR-020 (Conductor Orchestration Pattern)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, Optional

from src.core.a2a.agent_cards import AGENT_CARD_REGISTRY, list_cards
from src.core.a2a.contracts import (
    ConteudoBruto,
    ContextoWorkflow,
    FeedbackRevisao,
    QualityVerdict,
    RelatorioFinal,
    TaskPayload,
)
from src.core.a2a.observability import (
    inicializar_tracing,
    trace_a2a_invocation,
    trace_workflow_node,
)
from src.core.a2a.resilience import ResilientStateManager, classify_error
from src.core.a2a.workflow_graph import A2AWorkflowGraph

logger = logging.getLogger(__name__)


class SquadOrchestrator:
    """Production-grade A2A orchestrator with full observability and resilience.

    Combines the workflow graph execution with:
      - Contract validation (input/output against Pydantic schemas)
      - Distributed tracing (OTel spans per node + per invocation)
      - Resilient state management (atomic retries + DLQ)
      - Squad metadata emission (for Conductor integration)

    This is the class that ECS tasks instantiate to run A2A workflows.
    """

    def __init__(
        self,
        pesquisa_endpoint: str | None = None,
        escrita_endpoint: str | None = None,
        revisao_endpoint: str | None = None,
        state_manager: ResilientStateManager | None = None,
        timeout: int = 120,
        max_tentativas: int = 3,
        enable_tracing: bool = True,
    ):
        """Initialize the squad orchestrator.

        Args:
            pesquisa_endpoint: Research agent A2A endpoint.
            escrita_endpoint: Engineering agent A2A endpoint.
            revisao_endpoint: Review agent A2A endpoint.
            state_manager: Resilient state manager (DynamoDB + SQS DLQ).
            timeout: Default A2A invocation timeout in seconds.
            max_tentativas: Maximum review feedback loops.
            enable_tracing: Whether to initialize OTel tracing.
        """
        self._pesquisa_endpoint = pesquisa_endpoint or os.environ.get(
            "A2A_PESQUISA_ENDPOINT", "http://pesquisa.fde.local:9001"
        )
        self._escrita_endpoint = escrita_endpoint or os.environ.get(
            "A2A_ESCRITA_ENDPOINT", "http://escrita.fde.local:9002"
        )
        self._revisao_endpoint = revisao_endpoint or os.environ.get(
            "A2A_REVISAO_ENDPOINT", "http://revisao.fde.local:9003"
        )
        self._timeout = timeout
        self._max_tentativas = max_tentativas

        # State management with resilience (retry + DLQ)
        self._state = state_manager or ResilientStateManager()

        # Initialize distributed tracing
        if enable_tracing:
            inicializar_tracing(
                nome_servico="fde-a2a-orchestrator",
                environment=os.environ.get("ENVIRONMENT", "dev"),
            )

        # Workflow graph (lazy — connects to agents on first use)
        self._graph = A2AWorkflowGraph(
            pesquisa_endpoint=self._pesquisa_endpoint,
            escrita_endpoint=self._escrita_endpoint,
            revisao_endpoint=self._revisao_endpoint,
            timeout=self._timeout,
        )

        logger.info(
            "SquadOrchestrator initialized: pesquisa=%s escrita=%s revisao=%s",
            self._pesquisa_endpoint,
            self._escrita_endpoint,
            self._revisao_endpoint,
        )

    async def executar(
        self,
        prompt: str,
        workflow_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a full A2A squad workflow with resilience and observability.

        This is the primary entry point for production execution.
        Handles the complete lifecycle: research → engineering → review → approval.

        Args:
            prompt: User task description / spec content.
            workflow_id: Optional workflow ID (for recovery). Generated if not provided.
            metadata: Optional metadata (task_id, spec_path, source platform, etc.).

        Returns:
            Execution result dict containing:
              - workflow_id: Unique execution ID
              - status: "completed" | "failed" | "dlq"
              - relatorio: Final RelatorioFinal (if completed)
              - metricas: Execution metrics (durations, tokens, attempts)
              - erros: Accumulated errors (if any)
        """
        wf_id = workflow_id or f"wf-{uuid.uuid4().hex[:12]}"
        start_time = time.time()

        logger.info("[%s] Starting squad workflow: %s...", wf_id, prompt[:80])

        # ─── Recovery Check ──────────────────────────────────────────────
        contexto = self._state.recuperar_checkpoint(wf_id)

        if contexto:
            logger.info(
                "[%s] Recovering from checkpoint at node: %s (attempt %d)",
                wf_id, contexto.no_atual, contexto.tentativas_revisao,
            )
        else:
            contexto = ContextoWorkflow(
                workflow_id=wf_id,
                input_usuario=prompt,
                max_tentativas=self._max_tentativas,
            )

        try:
            # ─── Node: PESQUISA ──────────────────────────────────────────
            if contexto.no_atual in ("PESQUISA", ""):
                contexto = await self._executar_pesquisa(wf_id, contexto)

            # ─── Node: ESCRITA ───────────────────────────────────────────
            if contexto.no_atual == "ESCRITA":
                contexto = await self._executar_escrita(wf_id, contexto)

            # ─── Node: REVISAO (feedback loop) ───────────────────────────
            if contexto.no_atual == "REVISAO":
                contexto = await self._executar_revisao_loop(wf_id, contexto)

            # ─── Terminal: CONCLUIDO ─────────────────────────────────────
            total_duration = round(time.time() - start_time, 2)
            contexto.metricas_execucao["total_duration_s"] = total_duration
            contexto.metricas_execucao["metadata"] = metadata or {}

            self._state.marcar_concluido(wf_id, contexto)

            logger.info(
                "[%s] Workflow COMPLETED in %.1fs (attempts=%d)",
                wf_id, total_duration, contexto.tentativas_revisao,
            )

            return {
                "workflow_id": wf_id,
                "status": "completed",
                "relatorio": contexto.relatorio.model_dump() if contexto.relatorio else None,
                "metricas": contexto.metricas_execucao,
                "erros": contexto.erros,
                "tentativas_revisao": contexto.tentativas_revisao,
            }

        except Exception as e:
            # ─── Resilient Failure Handling ───────────────────────────────
            should_retry = self._state.registrar_falha_com_retry(
                workflow_id=wf_id,
                no_atual=contexto.no_atual,
                contexto=contexto,
                erro=e,
            )

            total_duration = round(time.time() - start_time, 2)

            if should_retry:
                logger.warning(
                    "[%s] Workflow failed at %s — retry allowed (%.1fs)",
                    wf_id, contexto.no_atual, total_duration,
                )
                return {
                    "workflow_id": wf_id,
                    "status": "retryable",
                    "no_falho": contexto.no_atual,
                    "erro": str(e)[:300],
                    "metricas": contexto.metricas_execucao,
                }
            else:
                logger.error(
                    "[%s] Workflow sent to DLQ after exhausting retries (%.1fs)",
                    wf_id, total_duration,
                )
                return {
                    "workflow_id": wf_id,
                    "status": "dlq",
                    "no_falho": contexto.no_atual,
                    "erro": str(e)[:300],
                    "classificacao": classify_error(e).value,
                    "metricas": contexto.metricas_execucao,
                    "erros": contexto.erros,
                }

    async def _executar_pesquisa(
        self, wf_id: str, contexto: ContextoWorkflow
    ) -> ContextoWorkflow:
        """Execute the PESQUISA (research) node with tracing and validation."""
        with trace_workflow_node(wf_id, "PESQUISA", {"query": contexto.input_usuario[:100]}):
            logger.info("[%s] → PESQUISA: collecting research data...", wf_id)
            start = time.time()

            with trace_a2a_invocation("pesquisa", "research", self._pesquisa_endpoint):
                resposta = await self._graph.agente_pesquisa.invoke(
                    task="Coleta de dados detalhada e estruturada sobre o tópico solicitado",
                    payload={"query": contexto.input_usuario},
                )

            # Contract validation — enforce ConteudoBruto schema
            contexto.dados_pesquisa = ConteudoBruto.model_validate(resposta)
            contexto.no_atual = "ESCRITA"
            contexto.metricas_execucao["pesquisa_duration_s"] = round(time.time() - start, 2)

            # Checkpoint after successful research
            self._state.salvar_checkpoint(wf_id, "ESCRITA", contexto)

            logger.info(
                "[%s] ✓ PESQUISA complete: %d facts, confidence=%.2f (%.1fs)",
                wf_id,
                len(contexto.dados_pesquisa.fatos_encontrados),
                contexto.dados_pesquisa.confianca,
                contexto.metricas_execucao["pesquisa_duration_s"],
            )

        return contexto

    async def _executar_escrita(
        self, wf_id: str, contexto: ContextoWorkflow
    ) -> ContextoWorkflow:
        """Execute the ESCRITA (engineering) node with tracing and validation."""
        with trace_workflow_node(wf_id, "ESCRITA"):
            logger.info("[%s] → ESCRITA: generating deliverable...", wf_id)
            start = time.time()

            with trace_a2a_invocation("escrita", "engineering", self._escrita_endpoint):
                resposta = await self._graph.agente_escrita.invoke(
                    task="Produzir documento técnico estruturado com base nos dados de pesquisa",
                    payload=contexto.dados_pesquisa.model_dump(),
                )

            # Contract validation — enforce RelatorioFinal schema
            contexto.relatorio = RelatorioFinal.model_validate(resposta)
            contexto.no_atual = "REVISAO"
            contexto.metricas_execucao["escrita_duration_s"] = round(time.time() - start, 2)

            # Checkpoint after successful engineering
            self._state.salvar_checkpoint(wf_id, "REVISAO", contexto)

            logger.info(
                "[%s] ✓ ESCRITA complete: %d artifacts (%.1fs)",
                wf_id,
                len(contexto.relatorio.artefatos),
                contexto.metricas_execucao["escrita_duration_s"],
            )

        return contexto

    async def _executar_revisao_loop(
        self, wf_id: str, contexto: ContextoWorkflow
    ) -> ContextoWorkflow:
        """Execute the REVISAO node with feedback loop back to ESCRITA."""
        remaining = contexto.max_tentativas - contexto.tentativas_revisao

        for ciclo in range(1, remaining + 1):
            tentativa_atual = contexto.tentativas_revisao + 1

            with trace_workflow_node(
                wf_id, "REVISAO", {"attempt": tentativa_atual}
            ):
                logger.info(
                    "[%s] → REVISAO: review attempt %d/%d...",
                    wf_id, tentativa_atual, contexto.max_tentativas,
                )
                start = time.time()

                with trace_a2a_invocation("revisao", "review", self._revisao_endpoint):
                    resultado = await self._graph.agente_revisao.invoke(
                        task="Avaliar qualidade técnica do relatório produzido",
                        payload=contexto.relatorio.model_dump(),
                    )

                # Contract validation — enforce FeedbackRevisao schema
                feedback = FeedbackRevisao.model_validate(resultado)
                feedback.tentativa = tentativa_atual
                contexto.feedback = feedback
                contexto.tentativas_revisao = tentativa_atual

                duration = round(time.time() - start, 2)
                contexto.metricas_execucao[f"revisao_{tentativa_atual}_duration_s"] = duration

                logger.info(
                    "[%s] REVISAO result: verdict=%s score=%.2f criticas=%d (%.1fs)",
                    wf_id,
                    feedback.veredicto.value,
                    feedback.score_qualidade,
                    len(feedback.criticas),
                    duration,
                )

            # ─── Routing Decision ────────────────────────────────────────
            if feedback.veredicto == QualityVerdict.APPROVED or feedback.aprovado:
                contexto.relatorio.aprovado = True
                logger.info("[%s] ✓ APPROVED on attempt %d", wf_id, tentativa_atual)
                break

            if tentativa_atual >= contexto.max_tentativas:
                contexto.relatorio.aprovado = True
                logger.warning(
                    "[%s] Max review attempts reached — force-approving", wf_id
                )
                break

            # ─── Feedback Loop: Route back to ESCRITA ────────────────────
            with trace_workflow_node(wf_id, "ESCRITA_REWORK", {"attempt": tentativa_atual}):
                logger.info(
                    "[%s] → ESCRITA (rework): addressing %d criticisms...",
                    wf_id, len(feedback.criticas),
                )
                start = time.time()

                with trace_a2a_invocation("escrita", "rework", self._escrita_endpoint):
                    resposta = await self._graph.agente_escrita.invoke(
                        task="Corrigir relatório com base no feedback da revisão",
                        payload={
                            "dados_originais": contexto.dados_pesquisa.model_dump(),
                            "relatorio_anterior": contexto.relatorio.model_dump(),
                            "feedback": feedback.model_dump(),
                        },
                    )

                contexto.relatorio = RelatorioFinal.model_validate(resposta)
                contexto.metricas_execucao[f"rework_{tentativa_atual}_duration_s"] = round(
                    time.time() - start, 2
                )

                # Checkpoint after each rework cycle
                self._state.salvar_checkpoint(wf_id, "REVISAO", contexto)

        return contexto

    def get_status(self, workflow_id: str) -> dict[str, Any]:
        """Get current status of a workflow (for monitoring/portal).

        Args:
            workflow_id: The workflow to check.

        Returns:
            Status dict with node, attempts, and last update time.
        """
        contexto = self._state.recuperar_checkpoint(workflow_id)
        if not contexto:
            return {"workflow_id": workflow_id, "status": "not_found"}

        return {
            "workflow_id": workflow_id,
            "status": "in_progress" if "FALHA" not in contexto.no_atual else "failed",
            "no_atual": contexto.no_atual,
            "tentativas_revisao": contexto.tentativas_revisao,
            "updated_at": contexto.updated_at,
            "erros": contexto.erros,
        }

    def list_active_workflows(self) -> list[dict[str, Any]]:
        """List all active (non-terminal) workflows.

        Returns:
            List of workflow summaries from DynamoDB.
        """
        return self._state.listar_workflows_ativos()

    @staticmethod
    def available_agents() -> list[dict[str, Any]]:
        """List all A2A agents available for squad composition.

        Used by the Conductor to understand what agents are available
        in the A2A microservice layer.

        Returns:
            List of agent cards with capabilities and schemas.
        """
        return list_cards()


# ─── CLI Entrypoint ──────────────────────────────────────────────────────────


async def _run_from_cli():
    """Run a workflow from CLI arguments or environment variables."""
    import argparse

    parser = argparse.ArgumentParser(description="FDE A2A Squad Orchestrator")
    parser.add_argument("--prompt", "-p", type=str, help="Task prompt to execute")
    parser.add_argument("--workflow-id", "-w", type=str, help="Workflow ID (for recovery)")
    parser.add_argument("--timeout", "-t", type=int, default=120, help="A2A timeout (seconds)")
    parser.add_argument("--max-attempts", "-m", type=int, default=3, help="Max review attempts")
    parser.add_argument("--status", "-s", type=str, help="Check workflow status")
    parser.add_argument("--list-active", action="store_true", help="List active workflows")
    parser.add_argument("--list-agents", action="store_true", help="List available A2A agents")

    args = parser.parse_args()

    orchestrator = SquadOrchestrator(
        timeout=args.timeout,
        max_tentativas=args.max_attempts,
    )

    if args.list_agents:
        agents = orchestrator.available_agents()
        for agent in agents:
            print(f"  {agent['name']}: {agent['description']}")
            print(f"    Capabilities: {agent['capabilities']['tasks']}")
            print(f"    Model: {agent['x-fde']['model_tier']} (cost={agent['x-fde']['cost_weight']})")
            print()
        return

    if args.list_active:
        workflows = orchestrator.list_active_workflows()
        if not workflows:
            print("No active workflows.")
        for wf in workflows:
            print(f"  {wf['workflow_id']}: node={wf['node_name']} updated={wf['updated_at']}")
        return

    if args.status:
        status = orchestrator.get_status(args.status)
        print(json.dumps(status, indent=2, default=str))
        return

    if not args.prompt:
        # Check for prompt from stdin (EventBridge payload)
        import sys
        if not sys.stdin.isatty():
            payload = json.load(sys.stdin)
            args.prompt = payload.get("prompt", payload.get("detail", {}).get("prompt", ""))
            args.workflow_id = payload.get("workflow_id")

    if not args.prompt:
        parser.error("--prompt is required (or pipe JSON via stdin)")

    result = await orchestrator.executar(
        prompt=args.prompt,
        workflow_id=args.workflow_id,
    )

    print(json.dumps(result, indent=2, default=str))


def main():
    """Synchronous entrypoint for `python -m src.core.a2a.orchestrator`."""
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(_run_from_cli())


if __name__ == "__main__":
    main()
