# FDE SWE Brain Simulation Ecosystem — Design Document

> Status: **Draft — Architectural Design**
> Date: 2026-05-08
> Origin: scaling-brain-simulation-study.md (research foundation)
> Applicability: CODE_FACTORY + FDE Protocol + Agentic Squad
> Constraint: No fake code. Every component produces testable, integrated functionality.
> Governance: Changes to this design require Staff SWE approval.

---

## Executive Summary

This document defines the **FDE SWE Brain Simulation Ecosystem** — a system architecture that applies brain emulation scaling principles to elevate the Forward Deployed AI Engineer from simulation (produces correct outputs) to emulation (replicates causal mechanisms of a Staff Engineer). The design is surgical: it identifies what does not exist today, what must exist, what must change, what integrations are needed for observability, and how to prevent false implementations.

---

## 1. Componentes que NÃO Existem Hoje e Falham em Brain Simulation

### 1.1 Fidelity Score Engine (Neural Activity Prediction Layer)

**O que falta**: O FDE não mede a fidelidade do próprio output. Ele sabe se testes passam (binary pass/fail), mas não sabe se o output *emula* o raciocínio de um Staff Engineer ou apenas *simula* o resultado esperado.

**Como isso falha em brain simulation**: Em WBE, um modelo que reproduz outputs sem replicar mecanismos causais internos é uma simulação, não uma emulação. Quando perturbado (input inesperado), a simulação falha catastroficamente porque não internalizou os mecanismos que produzem robustez.

**Evidência no CODE_FACTORY**: COE-052 — 20 fixes cascading. O agente produzia outputs corretos para cada fix individual (simulação), mas não replicava o mecanismo causal "entender o sistema antes de mudar" (emulação). Resultado: cada fix criava condições para o próximo bug.

**Componente ausente**: `fidelity_score.py` — engine que computa um score tridimensional (structural × behavioral × perturbation) para cada task completion.

---

### 1.2 Hierarchical Context Memory (Memory Wall Mitigation)

**O que falta**: O FDE perde modelo mental do sistema quando o contexto é compactado. Não existe hierarquia de memória — tudo é "context window ou nada."

**Como isso falha em brain simulation**: Em WBE, o memory wall é o gargalo dominante. A solução é hierarquia de memória (registers → L1 → L2 → L3 → RAM → disk). O FDE tem apenas dois níveis: "no contexto" e "perdido."

**Evidência no CODE_FACTORY**: Agente esquece module boundaries após compactação. Repete erros que já foram documentados em hindsight notes porque não os recupera proativamente.

**Componente ausente**: `context_hierarchy.py` — sistema de 5 níveis de memória com promoção/demoção automática baseada em relevância para a task atual.

---

### 1.3 Emulation vs. Simulation Classifier (Meta-Cognition Layer)

**O que falta**: O FDE não distingue quando está simulando (produzindo output correto sem entender) vs. emulando (replicando mecanismos causais). Não tem meta-cognição sobre a qualidade do próprio raciocínio.

**Como isso falha em brain simulation**: Em WBE, a distinção simulação/emulação é o critério fundamental de sucesso. Um modelo que passa em testes de output mas falha em perturbation tests é uma simulação — parece funcionar mas não é robusto.

**Evidência no CODE_FACTORY**: O agente declara "done" quando testes passam, sem validar se entendeu *por que* a solução funciona. Pattern 1 do COE-052 (Reactive Fix Cycle).

**Componente ausente**: `emulation_classifier.py` — classifica cada task completion como SIMULATION (output-only validation) ou EMULATION (causal mechanism validated).

---

### 1.4 Organism-Model Validation Ladder (Scaling Strategy)

**O que falta**: O FDE não tem uma estratégia de escala validada. O Agentic Squad (ADR-019) foi projetado para multi-repo sem validação em single-pipeline primeiro.

**Como isso falha em brain simulation**: Em WBE, pular organismos-modelo (tentar emular mouse sem ter validado em Drosophila) produz modelos que "parecem funcionar" em demos mas falham em validação comportamental rigorosa.

**Evidência no CODE_FACTORY**: O Squad Architecture define 20 agents sem ter validado que 4 agents funcionam corretamente para o organismo-projeto atual (data pipeline com 6 stages).

**Componente ausente**: `organism_ladder.py` — define 5 classes de projeto, valida FDE capabilities em cada classe antes de permitir escala para a próxima.

---

### 1.5 Knowledge Annotation Layer (Molecular Annotation)

**O que falta**: O Repo Onboarding Agent produz um `catalog.db` estrutural (quem conecta com quem) mas não anota *qual domínio de conhecimento governa cada conexão*.

**Como isso falha em brain simulation**: Em WBE, connectomes puramente estruturais são insuficientes. Sem molecular annotation (neurotransmissores, receptores), o modelo não pode inferir função a partir de estrutura.

**Evidência no CODE_FACTORY**: O agente modifica `fact_type_question_map.yaml` sem consultar o WAF corpus que o governa. Produz mappings estruturalmente corretos mas semanticamente errados (Pattern 3 do COE-052).

**Componente ausente**: `knowledge_annotation.py` — camada que mapeia cada módulo/edge para seus knowledge artifacts governantes e domain sources of truth.

---

### 1.6 Perturbation Test Engine (Causal Perturbation Experiments)

**O que falta**: O FDE valida com testes estruturais (unit + contract) e parcialmente com behavioral tests (smoke). Não existe validação por perturbação — "o que acontece quando o input é inesperado?"

**Como isso falha em brain simulation**: Em WBE, perturbation experiments são o gold standard para distinguir simulação de emulação. Se o modelo responde corretamente a perturbações que não estavam no training data, ele internalizou mecanismos causais.

**Evidência no CODE_FACTORY**: O agente não gera edge cases automaticamente. Testa apenas o happy path e os cenários explícitos no spec.

**Componente ausente**: `perturbation_engine.py` — gera inputs perturbados automaticamente e valida que o sistema degrada gracefully.

---

## 2. Componentes que DEVEM Existir para Viabilizar o FDE Brain Simulation Ecosystem

### 2.1 Arquitetura de Componentes — Visão Completa

```
┌─────────────────────────────────────────────────────────────────────┐
│                    FDE BRAIN SIMULATION ECOSYSTEM                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌─────────────────┐    ┌──────────────────┐    ┌────────────────┐  │
│  │ Context Hierarchy│    │ Knowledge        │    │ Organism       │  │
│  │ Manager          │    │ Annotation Layer │    │ Ladder         │  │
│  │ (context_        │    │ (knowledge_      │    │ (organism_     │  │
│  │  hierarchy.py)   │    │  annotation.py)  │    │  ladder.py)    │  │
│  └────────┬─────────┘    └────────┬─────────┘    └───────┬────────┘  │
│           │                       │                       │           │
│           ▼                       ▼                       ▼           │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │              FIDELITY SCORE ENGINE (fidelity_score.py)          │  │
│  │  structural_score × 0.3 + behavioral_score × 0.4 +            │  │
│  │  perturbation_score × 0.3 = emulation_fidelity                │  │
│  └────────────────────────────────────────────────────────────────┘  │
│           │                       │                       │           │
│           ▼                       ▼                       ▼           │
│  ┌─────────────────┐    ┌──────────────────┐    ┌────────────────┐  │
│  │ Emulation       │    │ Perturbation     │    │ Behavioral     │  │
│  │ Classifier      │    │ Test Engine      │    │ Benchmark      │  │
│  │ (emulation_     │    │ (perturbation_   │    │ Runner         │  │
│  │  classifier.py) │    │  engine.py)      │    │ (behavioral_   │  │
│  │                  │    │                  │    │  benchmark.py) │  │
│  └────────┬─────────┘    └────────┬─────────┘    └───────┬────────┘  │
│           │                       │                       │           │
│           ▼                       ▼                       ▼           │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │           OBSERVABILITY LAYER (brain_sim_metrics.py)            │  │
│  │  Fidelity trends | Memory wall hits | Organism progression     │  │
│  │  Emulation ratio | Perturbation coverage | Knowledge gaps      │  │
│  └────────────────────────────────────────────────────────────────┘  │
│           │                                                           │
│           ▼                                                           │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │              PORTAL INTEGRATION (portal cards + dashboards)     │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 Componente: Context Hierarchy Manager (`context_hierarchy.py`)

**Responsabilidade**: Gerenciar 5 níveis de memória com promoção/demoção automática.

| Nível | Analogia WBE | Conteúdo | Latência | Persistência |
|---|---|---|---|---|
| L1 | Voltage imaging (real-time) | Steering file: pipeline chain, anti-patterns, current task context | 0ms (always loaded) | Session |
| L2 | Calcium imaging (event-driven) | Hook prompts: DoR/DoD gates, adversarial questions | ~100ms (hook trigger) | Session |
| L3 | Connectome (structural) | Notes: hindsight, domain knowledge, cross-session learnings | ~500ms (file read) | Persistent (S3) |
| L4 | Molecular annotation (deep) | Catalog.db: full repo structure, pattern inference, knowledge annotations | ~2s (SQLite query) | Persistent (S3) |
| L5 | Behavioral validation (E2E) | Knowledge corpus: WAF corpus, mappings, recommendation templates | ~5s (full scan) | Immutable (code) |

**Interfaces**:
```python
class ContextHierarchyManager:
    def promote(self, item: str, from_level: int, to_level: int) -> None: ...
    def demote(self, item: str, from_level: int, to_level: int) -> None: ...
    def query(self, task_context: TaskContext) -> RelevantContext: ...
    def report_memory_wall_hit(self, task_id: str, what_was_lost: str) -> None: ...
    def get_hierarchy_health(self) -> HierarchyHealth: ...
```

**Regras de promoção/demoção**:
- Item referenciado 3+ vezes em uma session → promove para L1
- Item não referenciado em 5 tasks → demove um nível
- Memory wall hit detectado → item perdido é promovido para nível mais alto na próxima session
- Knowledge annotation referenced during task → promove para L2 durante task execution

---

### 2.3 Componente: Knowledge Annotation Layer (`knowledge_annotation.py`)

**Responsabilidade**: Anotar cada módulo e edge com seus knowledge artifacts governantes.

**Schema**:
```python
@dataclass
class KnowledgeAnnotation:
    module: str                          # e.g., "publish_tree.py"
    edge: str                            # e.g., "E4"
    governing_artifacts: list[str]       # e.g., ["_FACT_CLASS_SEVERITY", "risk_engine"]
    domain_source_of_truth: list[str]    # e.g., ["waf_security_corpus.py", "WAF risk guidance"]
    last_validated: datetime             # when was this annotation last confirmed
    confidence: float                    # 0.0-1.0, decays over time without revalidation
    annotation_type: str                 # "code_logic" | "knowledge_artifact" | "hybrid"
```

**Interfaces**:
```python
class KnowledgeAnnotationLayer:
    def annotate_module(self, module: str, annotations: list[KnowledgeAnnotation]) -> None: ...
    def get_governing_knowledge(self, module: str) -> list[KnowledgeAnnotation]: ...
    def get_edge_annotations(self, edge: str) -> list[KnowledgeAnnotation]: ...
    def validate_against_source(self, annotation: KnowledgeAnnotation) -> ValidationResult: ...
    def detect_stale_annotations(self, max_age_days: int = 30) -> list[KnowledgeAnnotation]: ...
    def get_knowledge_gaps(self) -> list[str]: ...  # modules without annotations
```

**Integração com Repo Onboarding**: O `catalog.db` ganha uma tabela `knowledge_annotations` que persiste estas anotações. O onboarding agent popula automaticamente com inferência (Haiku), mas marca `confidence=0.5` até validação humana.

---

### 2.4 Componente: Fidelity Score Engine (`fidelity_score.py`)

**Responsabilidade**: Computar score tridimensional de fidelidade para cada task completion.

**Schema**:
```python
@dataclass
class FidelityScore:
    task_id: str
    structural_score: float      # 0.0-1.0: contract tests + unit tests
    behavioral_score: float      # 0.0-1.0: product smoke test with representative workload
    perturbation_score: float    # 0.0-1.0: edge case resilience
    composite_score: float       # weighted: 0.3 + 0.4 + 0.3
    classification: str          # "SIMULATION" | "EMULATION" | "PARTIAL_EMULATION"
    evidence: dict               # what tests were run, what passed/failed
    timestamp: datetime
```

**Classificação**:
- `composite_score >= 0.8` AND `perturbation_score >= 0.6` → EMULATION
- `composite_score >= 0.6` AND `perturbation_score < 0.6` → PARTIAL_EMULATION
- `composite_score < 0.6` OR `behavioral_score < 0.5` → SIMULATION

**Interfaces**:
```python
class FidelityScoreEngine:
    def compute_score(self, task_id: str, test_results: TestResults) -> FidelityScore: ...
    def get_trend(self, project_id: str, window_days: int = 30) -> list[FidelityScore]: ...
    def get_emulation_ratio(self, project_id: str) -> float: ...  # % tasks classified as EMULATION
    def identify_weak_dimension(self, project_id: str) -> str: ...  # which dimension drags score down
```

---

### 2.5 Componente: Organism Ladder (`organism_ladder.py`)

**Responsabilidade**: Classificar projetos em organismos-modelo e validar FDE capabilities antes de escalar.

**Schema**:
```python
@dataclass
class OrganismClassification:
    project_id: str
    organism: str                # "c_elegans" | "zebrafish" | "drosophila" | "mouse" | "human"
    complexity_metrics: dict     # modules, edges, async_events, services, repos
    required_fde_level: str      # "L2" | "L3" | "L4" | "L5"
    required_squad_size: int     # minimum agents needed
    validation_status: str       # "VALIDATED" | "IN_PROGRESS" | "NOT_STARTED"
    validation_evidence: list    # which benchmarks passed at this organism level

ORGANISM_CRITERIA = {
    "c_elegans": {"max_modules": 3, "max_edges": 2, "async": False, "services": 1, "repos": 1},
    "zebrafish": {"max_modules": 10, "max_edges": 8, "async": False, "services": 1, "repos": 1},
    "drosophila": {"max_modules": 20, "max_edges": 15, "async": True, "services": 1, "repos": 1},
    "mouse": {"max_modules": 50, "max_edges": 30, "async": True, "services": 5, "repos": 1},
    "human": {"max_modules": None, "max_edges": None, "async": True, "services": None, "repos": 3},
}
```

**Regra de escala**: O FDE não pode operar no nível `mouse` até que `drosophila` tenha `validation_status == "VALIDATED"` com `emulation_ratio >= 0.7`.

---

### 2.6 Componente: Perturbation Test Engine (`perturbation_engine.py`)

**Responsabilidade**: Gerar inputs perturbados automaticamente e validar degradação graceful.

**Estratégias de perturbação**:
```python
PERTURBATION_STRATEGIES = [
    "missing_field",        # remove um campo esperado do input
    "extra_field",          # adiciona campo inesperado
    "type_mismatch",       # string onde esperava int, etc.
    "boundary_value",      # 0, -1, MAX_INT, empty string, None
    "encoding_variation",  # UTF-8 edge cases, emoji, RTL text
    "scale_variation",     # 10x mais items que o normal
    "temporal_variation",  # timestamps no futuro, no passado distante
    "dependency_failure",  # upstream retorna erro/timeout
]
```

**Interfaces**:
```python
class PerturbationEngine:
    def generate_perturbations(self, input_schema: dict, strategies: list[str]) -> list[dict]: ...
    def run_perturbation_suite(self, module: str, perturbations: list[dict]) -> PerturbationResults: ...
    def classify_degradation(self, result: Any) -> str: ...  # "graceful" | "partial" | "catastrophic"
    def get_perturbation_coverage(self, project_id: str) -> float: ...  # % modules with perturbation tests
```

---

### 2.7 Componente: Emulation Classifier (`emulation_classifier.py`)

**Responsabilidade**: Meta-cognição — classificar se o agente está simulando ou emulando em cada task.

**Sinais de EMULAÇÃO** (o agente replicou mecanismos causais):
- Leu módulos upstream E downstream antes de modificar
- Identificou edge contracts afetados
- Consultou knowledge annotations relevantes
- Gerou perturbation tests além dos cenários do spec
- Explicou *por que* a solução funciona, não apenas *que* funciona

**Sinais de SIMULAÇÃO** (o agente produziu output sem entender):
- Modificou apenas o módulo reportado no bug
- Não consultou consumers downstream
- Não referenciou knowledge artifacts governantes
- Testou apenas happy path
- Declarou "done" baseado apenas em "tests pass"

**Interfaces**:
```python
class EmulationClassifier:
    def classify_task(self, task_id: str, execution_trace: ExecutionTrace) -> Classification: ...
    def get_simulation_indicators(self, task_id: str) -> list[str]: ...
    def get_emulation_indicators(self, task_id: str) -> list[str]: ...
    def suggest_elevation(self, task_id: str) -> list[str]: ...  # what would make this EMULATION
```

---

### 2.8 Componente: Behavioral Benchmark Runner (`behavioral_benchmark.py`)

**Responsabilidade**: Executar product-level behavioral tests com workloads representativos.

**Diferença de unit/contract tests**: Behavioral tests validam "dado este workload real, o output conta a história certa?" — não "esta função retorna o valor esperado?"

**Interfaces**:
```python
class BehavioralBenchmarkRunner:
    def register_workload(self, name: str, input_path: str, expected_output_path: str) -> None: ...
    def run_benchmark(self, workload_name: str) -> BenchmarkResult: ...
    def compare_with_baseline(self, current: BenchmarkResult, baseline: BenchmarkResult) -> Drift: ...
    def get_behavioral_coverage(self, project_id: str) -> float: ...
```

---

### 2.9 Componente: Brain Sim Metrics Collector (`brain_sim_metrics.py`)

**Responsabilidade**: Coletar e persistir métricas específicas do brain simulation ecosystem.

**Métricas**:
| Métrica | Tipo | O que mede |
|---|---|---|
| `fidelity_score_trend` | time_series | Evolução do composite fidelity score |
| `emulation_ratio` | gauge | % de tasks classificadas como EMULATION |
| `memory_wall_hits` | counter | Quantas vezes contexto foi perdido por compactação |
| `organism_level` | gauge | Em qual organismo-modelo o projeto está validado |
| `perturbation_coverage` | gauge | % de módulos com perturbation tests |
| `knowledge_annotation_coverage` | gauge | % de módulos com knowledge annotations |
| `knowledge_gap_count` | gauge | Módulos sem annotation |
| `stale_annotation_count` | gauge | Annotations não revalidadas em 30+ dias |
| `simulation_to_emulation_ratio` | gauge | Tendência de melhoria ao longo do tempo |
| `context_hierarchy_efficiency` | gauge | % de queries resolvidas em L1-L2 vs L4-L5 |

---

## 3. O que Precisa Mudar no Codebase do FDE (CODE_FACTORY)

### 3.1 Mudanças no Orchestrator (`infra/docker/agents/orchestrator.py`)

| Mudança | Tipo | Impacto |
|---|---|---|
| Integrar `FidelityScoreEngine.compute_score()` no pipeline completion | Adição | Cada task agora produz um fidelity score além de pass/fail |
| Integrar `EmulationClassifier.classify_task()` após score computation | Adição | Cada task é classificada como SIMULATION/EMULATION |
| Integrar `ContextHierarchyManager.query()` no pipeline start | Adição | Agent recebe contexto hierárquico relevante, não apenas steering |
| Integrar `OrganismLadder.classify_project()` no task intake | Adição | Squad composition é baseada em organismo, não apenas L-level |
| Reportar `memory_wall_hit` quando contexto é compactado | Adição | Observability sobre perda de contexto |

### 3.2 Mudanças no Agent Builder (`infra/docker/agents/agent_builder.py`)

| Mudança | Tipo | Impacto |
|---|---|---|
| Squad composition aceita `organism` como input além de `autonomy_level` | Modificação | Composição mais precisa baseada em complexidade do projeto |
| Agent prompts incluem knowledge annotations relevantes | Modificação | Agents recebem "molecular annotation" do módulo que vão modificar |

### 3.3 Mudanças no DORA Metrics (`infra/docker/agents/dora_metrics.py`)

| Mudança | Tipo | Impacto |
|---|---|---|
| Adicionar dimensão `fidelity_score` ao task metric | Adição | Correlação entre fidelity e DORA metrics |
| Adicionar dimensão `emulation_classification` | Adição | Segmentar DORA por SIMULATION vs EMULATION |
| Adicionar `brain_sim_metrics` ao Factory Health Report | Adição | Dashboard unificado |

### 3.4 Mudanças no Repo Onboarding (`infra/docker/agents/onboarding/`)

| Mudança | Tipo | Impacto |
|---|---|---|
| `catalog.db` ganha tabela `knowledge_annotations` | Adição | Persistência de molecular annotations |
| Onboarding agent infere knowledge annotations via Haiku | Adição | Annotations automáticas com confidence=0.5 |
| Onboarding agent classifica projeto em organism level | Adição | Classificação automática de complexidade |
| Steering gerado inclui knowledge annotations dos módulos críticos | Modificação | Agent recebe "molecular context" desde o início |

### 3.5 Mudanças nos Hooks (`.kiro/hooks/`)

| Hook | Tipo | Trigger | Ação |
|---|---|---|---|
| `fde-fidelity-gate.kiro.hook` | Novo | postTaskExecution | Computa fidelity score e bloqueia se < threshold |
| `fde-emulation-check.kiro.hook` | Novo | postToolUse (write) | Classifica se a write foi SIMULATION ou EMULATION |
| `fde-perturbation-reminder.kiro.hook` | Novo | preToolUse (write) | Pergunta: "Você gerou perturbation tests para esta mudança?" |
| `fde-knowledge-validation.kiro.hook` | Modificação | preToolUse (write) | Adiciona: "Qual knowledge annotation governa este módulo?" |

### 3.6 Mudanças no Steering (`.kiro/steering/`)

| Steering | Tipo | Conteúdo |
|---|---|---|
| `brain-simulation.md` | Novo | Conceitos do ecosystem, organism level atual, fidelity thresholds |
| `fde.md` | Modificação | Adicionar seção "Emulation Fidelity" com critérios de classificação |

### 3.7 Mudanças no Portal (`src/portal/`)

| Mudança | Tipo | Impacto |
|---|---|---|
| Novo card: "Emulation Fidelity" no Factory Health dashboard | Adição | Visualização do fidelity score trend |
| Novo card: "Organism Level" com progression ladder | Adição | Visualização de onde o projeto está na escada |
| Novo card: "Memory Wall" com hit frequency | Adição | Visualização de perda de contexto |
| Novo card: "Knowledge Coverage" com gap map | Adição | Visualização de módulos sem annotation |

---

## 4. Integrações para Observabilidade no Portal

### 4.1 Data Flow — Brain Sim Metrics para Portal

```
orchestrator.py (task completion)
  -> fidelity_score.py (compute score)
    -> emulation_classifier.py (classify)
      -> brain_sim_metrics.py (persist to DynamoDB)
        -> dora_metrics.py (include in Factory Health Report)
          -> Portal JS renderers (display cards)
```

### 4.2 Portal Cards — Especificação

#### Card 1: Emulation Fidelity Trend
- **Dados**: `fidelity_score_trend` (últimos 30 dias)
- **Visualização**: Line chart com 3 linhas (structural, behavioral, perturbation) + composite
- **Thresholds**: Verde (>= 0.8), Amarelo (0.6-0.8), Vermelho (< 0.6)
- **Drill-down**: Click em ponto mostra detalhes do task com evidence

#### Card 2: Emulation Ratio
- **Dados**: `emulation_ratio` (gauge)
- **Visualização**: Donut chart — EMULATION vs PARTIAL vs SIMULATION
- **Target**: >= 70% EMULATION para organism level atual
- **Drill-down**: Click em segmento mostra lista de tasks naquela classificação

#### Card 3: Organism Progression Ladder
- **Dados**: `organism_level` + `validation_evidence`
- **Visualização**: Vertical ladder com 5 degraus, current highlighted
- **Regra**: Próximo degrau só acende quando `emulation_ratio >= 0.7` no atual
- **Drill-down**: Click em degrau mostra benchmarks que validaram aquele nível

#### Card 4: Memory Wall Monitor
- **Dados**: `memory_wall_hits` (counter) + `context_hierarchy_efficiency` (gauge)
- **Visualização**: Bar chart (hits/week) + efficiency gauge
- **Alert**: Se hits > 5/week indica "Context hierarchy needs optimization"
- **Drill-down**: Click mostra lista de items perdidos e sugestão de promoção

#### Card 5: Knowledge Coverage Map
- **Dados**: `knowledge_annotation_coverage` + `knowledge_gap_count` + `stale_annotation_count`
- **Visualização**: Heatmap dos módulos — verde (annotated + fresh), amarelo (annotated + stale), vermelho (no annotation)
- **Alert**: Se gaps > 20% indica "Knowledge annotations incomplete"
- **Drill-down**: Click em módulo mostra detalhes da annotation ou "create annotation" action

#### Card 6: Perturbation Coverage
- **Dados**: `perturbation_coverage` (gauge)
- **Visualização**: Progress bar com target (>= 60% para organism level atual)
- **Alert**: Se coverage < 40% indica "Perturbation testing insufficient for current organism level"
- **Drill-down**: Click mostra lista de módulos sem perturbation tests

### 4.3 Integração com Factory Health Report

O `DORACollector.generate_factory_report()` ganha uma seção `brain_simulation`:

```json
{
  "factory_health": {
    "dora_metrics": {},
    "failure_modes": {},
    "brain_simulation": {
      "organism_level": "drosophila",
      "emulation_ratio": 0.65,
      "fidelity_score_avg": 0.72,
      "memory_wall_hits_last_7d": 3,
      "knowledge_coverage": 0.78,
      "perturbation_coverage": 0.45,
      "weak_dimension": "perturbation",
      "recommendation": "Increase perturbation test coverage to reach 0.7 emulation ratio threshold for mouse level"
    }
  }
}
```

### 4.4 OTEL Integration

Cada componente do brain sim ecosystem emite spans:

| Span | Parent | Attributes |
|---|---|---|
| `brain_sim.fidelity_compute` | `orchestrator.task_complete` | `structural_score`, `behavioral_score`, `perturbation_score`, `composite` |
| `brain_sim.emulation_classify` | `brain_sim.fidelity_compute` | `classification`, `indicators_count` |
| `brain_sim.context_query` | `orchestrator.task_start` | `level_resolved`, `items_returned`, `memory_wall_hit` |
| `brain_sim.perturbation_run` | `orchestrator.task_validate` | `strategies_used`, `graceful_count`, `catastrophic_count` |
| `brain_sim.knowledge_lookup` | `agent.tool_use` | `module`, `annotations_found`, `confidence_avg` |

---

## 5. Como Assegurar que NAO Existam Implementacoes ou Coreografias Falsas

### 5.1 Princípio: "No Fake Code" — Definição Operacional

Uma implementação é **falsa** quando:
1. Existe o módulo mas não existe teste que valida seu comportamento real
2. Existe a interface mas o corpo retorna valores hardcoded ou mock permanente
3. Existe a integração no orchestrator mas nunca é exercitada em E2E
4. Existe a métrica mas nunca é consumida por um dashboard ou alert
5. Existe o card no portal mas os dados são estáticos ou placeholder

### 5.2 Mecanismo Anti-Fake: Data Travel Validation

Para cada componente do brain sim ecosystem, deve existir um **data travel test** que prova que dados fluem end-to-end:

```python
# Pattern: test_data_travel_brain_sim.py
def test_fidelity_score_travels_to_portal():
    """Prova que um fidelity score computado pelo engine chega ao portal JSON."""
    # 1. Trigger task completion com test results conhecidos
    # 2. Verificar que fidelity_score.py computa score correto
    # 3. Verificar que brain_sim_metrics.py persiste o score
    # 4. Verificar que dora_metrics.py inclui no Factory Health Report
    # 5. Verificar que o JSON de saída contém brain_simulation section
    # Se qualquer step falha -> a integração é fake
```

### 5.3 Mecanismo Anti-Fake: Organism Ladder Gate

O organism ladder impede escala prematura:

```python
def can_scale_to_next_organism(current: str, metrics: BrainSimMetrics) -> bool:
    """Só permite escalar se o nível atual está genuinamente validado."""
    if metrics.emulation_ratio < 0.7:
        return False  # Não está emulando suficientemente no nível atual
    if metrics.perturbation_coverage < 0.5:
        return False  # Não testou robustez suficientemente
    if metrics.knowledge_coverage < 0.6:
        return False  # Não anotou conhecimento suficientemente
    if metrics.data_travel_tests_passing < 1.0:
        return False  # Alguma integração é fake
    return True
```

### 5.4 Mecanismo Anti-Fake: Coreografia Validation

Cada "coreografia" (sequência de componentes interagindo) deve ter um **choreography test**:

| Coreografia | Componentes | Choreography Test |
|---|---|---|
| Task -> Fidelity -> Classification | orchestrator, fidelity_score, emulation_classifier | `test_task_produces_classification()` |
| Context Query -> Hierarchy -> Agent | orchestrator, context_hierarchy, agent_builder | `test_context_reaches_agent()` |
| Perturbation -> Score -> Portal | perturbation_engine, fidelity_score, portal JSON | `test_perturbation_affects_score()` |
| Knowledge Lookup -> Annotation -> Validation | agent tool_use, knowledge_annotation, source validation | `test_knowledge_governs_change()` |
| Memory Wall -> Promotion -> Next Session | context compaction, hierarchy manager, next task | `test_memory_wall_triggers_promotion()` |

### 5.5 Mecanismo Anti-Fake: Golden Principle Extension

Adicionar ao `golden_principles.py`:

```python
BRAIN_SIM_PRINCIPLES = [
    {
        "name": "no_dead_metrics",
        "rule": "Every metric in brain_sim_metrics.py must have at least one consumer (portal card or alert)",
        "detection": "grep metric names in brain_sim_metrics.py, verify each appears in portal renderer or alert config",
    },
    {
        "name": "no_placeholder_scores",
        "rule": "FidelityScore.compute_score() must use real test results, never return hardcoded values",
        "detection": "static analysis: compute_score() must reference TestResults parameter in all code paths",
    },
    {
        "name": "no_orphan_annotations",
        "rule": "Every KnowledgeAnnotation must reference a real file that exists in the repo",
        "detection": "for each annotation.module, verify os.path.exists(module_path)",
    },
    {
        "name": "no_fake_perturbations",
        "rule": "PerturbationEngine must actually execute the module with perturbed input, not just generate inputs",
        "detection": "perturbation test must show module execution trace, not just input generation",
    },
]
```

### 5.6 Mecanismo Anti-Fake: Adversarial Review Checklist

Antes de marcar qualquer brain sim component como "done", o adversarial gate pergunta:

1. **Data Travel**: "Mostre o teste que prova que dados fluem deste componente até o portal."
2. **Real Execution**: "Mostre que este componente executa lógica real, não retorna mocks."
3. **Consumer Exists**: "Quem consome o output deste componente? Mostre o código do consumer."
4. **Perturbation Resilience**: "O que acontece quando este componente recebe input malformado?"
5. **Regression Guard**: "Qual teste quebraria se alguém removesse este componente silenciosamente?"

---

## 6. Validacao: 5W2H + Adversarial + Red Team

### 6.1 Analise 5W2H

| Dimensao | Resposta |
|---|---|
| **WHAT** | Um ecosystem de 8 componentes que eleva o FDE de simulacao (output-only) para emulacao (causal mechanism replication), inspirado pelo framework de scaling do State of Brain Emulation Report 2025. |
| **WHERE** | `infra/docker/agents/` (novos modulos Python), `.kiro/hooks/` (novos hooks), `.kiro/steering/` (novo steering), `src/portal/` (novos cards), `infra/docker/agents/onboarding/` (extensao do catalog.db). |
| **WHEN** | Sprint 1-6 (6 semanas). Cada sprint valida um organismo-modelo antes de escalar. Sprint 1 valida C. elegans (componentes core). Sprint 6 valida Drosophila (full ecosystem). |
| **WHO** | Staff SWE (design + review), FDE Squad (implementacao), Portal team (cards). O FDE Squad opera sob o protocolo FDE com todos os hooks ativos. |
| **WHY** | Porque o FDE atual simula engenharia (produz outputs corretos) mas nao emula (nao replica mecanismos causais). COE-052 provou que simulacao produz cascading failures. O brain emulation report fornece o framework teorico para escalar fidelidade de forma intencional. |
| **HOW** | Implementacao incremental por organismo-modelo. Cada componente tem data travel test + choreography test + perturbation test. Nenhum componente e "done" sem consumer real. Golden principles extended para detectar fake implementations. |
| **HOW MUCH** | 8 novos modulos Python (~2000 LOC total), 4 novos hooks, 1 novo steering, 6 portal cards, 1 tabela nova no catalog.db, extensao de 4 modulos existentes. Custo estimado: ~$0.05/task adicional (fidelity computation + classification). |

### 6.2 Adversarial Challenge — Against Lazy Analysis

| Desafio | Resposta Honesta |
|---|---|
| "Isso nao e over-engineering? O FDE ja funciona." | O FDE funciona para C. elegans (tasks simples). COE-052 provou que falha para Drosophila (pipeline tasks). Sem fidelity measurement, nao sabemos QUANDO falha — so descobrimos depois. O ecosystem nao adiciona complexidade ao agent — adiciona observabilidade sobre a qualidade do agent. |
| "Fidelity Score e apenas mais um numero. Como isso muda o comportamento do agent?" | O score alimenta o Organism Ladder gate. Se emulation_ratio < 0.7, o FDE nao pode escalar para o proximo nivel de complexidade. Isso e um circuit breaker real, nao um dashboard decorativo. |
| "Knowledge Annotations vao ficar stale em 2 semanas." | Por isso existe confidence decay e detect_stale_annotations(). Annotations com confidence < 0.3 sao flagged no portal. O doc-gardening hook pode ser extended para detectar stale annotations. Mas o ponto e: annotations stale sao melhores que zero annotations. |
| "Perturbation tests sao caros de manter." | Perturbation tests sao GERADOS automaticamente pelo engine baseado no input schema. Nao sao escritos manualmente. O custo de manutencao e zero — se o schema muda, as perturbations mudam automaticamente. |
| "O Emulation Classifier e subjetivo — como definir emulacao de forma deterministica?" | Os sinais sao deterministicos: "leu modulos upstream?" e verificavel no execution trace. "Consultou knowledge annotations?" e verificavel. "Gerou perturbation tests?" e verificavel. A classificacao e baseada em sinais observaveis, nao em julgamento. |
| "Organism Ladder e artificial — projetos nao se encaixam em 5 categorias." | Correto. A ladder e um heuristic, nao uma taxonomia rigida. O valor e impedir escala prematura (tentar multi-repo antes de validar single-pipeline), nao classificar projetos perfeitamente. Se um projeto esta entre dois niveis, usa o mais alto. |
| "Context Hierarchy Manager e reinventar caching. Use Redis." | Nao e caching de dados — e caching de CONTEXTO SEMANTICO para um LLM. Redis nao sabe que "module boundaries" e mais relevante que "import statements" para a task atual. A hierarquia e semantica, nao temporal. |
| "Isso tudo depende de ter testes bons. Se os testes sao ruins, o fidelity score e inutil." | Correto. O fidelity score e tao bom quanto os testes que o alimentam. Por isso o behavioral benchmark runner existe — para criar testes de nivel product que nao existem hoje. E por isso perturbation tests sao gerados automaticamente — para cobrir o que testes manuais nao cobrem. |

### 6.3 Red Team — Deep Reasoning sobre Modos de Falha

| Modo de Falha | Probabilidade | Impacto | Mitigacao |
|---|---|---|---|
| **Goodhart's Law**: Agent otimiza para fidelity score em vez de qualidade real | Alta | Alto | Score e tridimensional com perturbation (nao-gameable). Behavioral tests usam workloads reais, nao sinteticos. Perturbation strategies sao randomizadas. |
| **Annotation Rot**: Knowledge annotations ficam desatualizadas e misleading | Media | Medio | Confidence decay automatico. Stale detection no doc-gardening. Portal alert quando coverage < threshold. |
| **False Emulation**: Agent aprende a "parecer" que emula (le upstream mas nao usa a informacao) | Media | Alto | Emulation classifier verifica nao apenas SE leu, mas se o output REFERENCIA o que leu. Correlation entre files read e changes made. |
| **Organism Ceiling**: Projeto fica preso em um organism level sem path para escalar | Baixa | Medio | identify_weak_dimension() aponta exatamente o que precisa melhorar. Recommendation engine sugere acoes especificas. |
| **Memory Wall Amplification**: Hierarchy manager adiciona overhead que piora o memory wall | Baixa | Alto | L1-L2 sao zero-cost (ja existem como steering/hooks). L3-L5 sao lazy-loaded. Query cost e bounded (max 2s). Se overhead > benefit, disable via feature flag. |
| **Integration Complexity**: 8 novos modulos criam 28 possiveis pontos de falha entre eles | Media | Alto | Choreography tests validam cada integracao. Modulos sao loosely coupled (communicate via dataclasses, not direct calls). Feature flag per-module permite disable individual. |
| **Portal Overload**: 6 novos cards sobrecarregam o dashboard | Baixa | Baixo | Cards sao collapsible. Default view mostra apenas composite score + organism level. Drill-down e opt-in. |
| **Cost Explosion**: Fidelity computation + perturbation tests adicionam latencia/custo inaceitavel | Media | Medio | Perturbation runs sao async (nao bloqueiam task completion). Fidelity computation e deterministic (no LLM call). Custo estimado: $0.05/task. Feature flag para disable em L5 tasks. |

### 6.4 Red Team — Perguntas que um Staff Engineer Faria

1. **"Qual e o MVP minimo que prova valor antes de construir tudo?"**
   - Resposta: Fidelity Score Engine + Emulation Classifier. Apenas esses dois componentes ja transformam "tests pass" em "tests pass AND we know if we're simulating or emulating." Zero portal changes needed for MVP.

2. **"Como rollback se isso nao funcionar?"**
   - Resposta: Feature flag `BRAIN_SIM_ENABLED=false` desabilita todo o ecosystem. Modulos sao additive (nao modificam logica existente, apenas adicionam computation apos task completion). Rollback e instantaneo.

3. **"Isso escala para 3+ workspaces simultaneos?"**
   - Resposta: Cada workspace tem seu proprio organism classification e fidelity history. Brain sim metrics sao scoped por project_id. Context hierarchy e per-workspace. Nao ha shared state entre workspaces.

4. **"Quem mantem as knowledge annotations quando o projeto evolui?"**
   - Resposta: O onboarding agent re-infere annotations quando detecta structural changes (new modules, changed edges). Confidence e resetada para 0.5 em annotations afetadas. Human validation eleva para 1.0.

5. **"Como isso interage com o Agentic Squad (ADR-019)?"**
   - Resposta: O organism classification alimenta o squad composer. C. elegans tasks usam 1-2 agents. Drosophila tasks usam 4-6. O squad size e proporcional ao organism level, nao arbitrario.

---

## 7. Task Plan — Implementacao Completa do FDE SWE Brain Simulation Ecosystem

> Constraint: No fake code. Every task produces testable, integrated functionality.
> Constraint: Each sprint validates one organism level before scaling.
> Constraint: Data travel test required for every component.
> Constraint: Feature flag BRAIN_SIM_ENABLED gates all new functionality.

---

### Sprint 1: Foundation (Organism: C. elegans validation)

#### Task 1.1: Fidelity Score Engine

**Source**: Brain Emulation Report — multi-dimensional benchmarks
**Impact**: Transforms binary pass/fail into tridimensional fidelity measurement
**Effort**: Medium

**Acceptance Criteria**:
- [ ] `infra/docker/agents/fidelity_score.py` implements FidelityScoreEngine class
- [ ] compute_score() accepts TestResults and returns FidelityScore dataclass
- [ ] Score computation: structural (contract+unit pass rate) x 0.3 + behavioral (smoke test pass rate) x 0.4 + perturbation (edge case pass rate) x 0.3
- [ ] Classification logic: EMULATION (>= 0.8 AND perturbation >= 0.6), PARTIAL (>= 0.6), SIMULATION (< 0.6)
- [ ] get_trend() returns historical scores from DynamoDB
- [ ] identify_weak_dimension() returns which dimension drags composite down
- [ ] BDD test: given known test results, compute_score returns expected classification
- [ ] Data travel test: score persists to DynamoDB and appears in Factory Health Report JSON

**Files**:
- NEW: `infra/docker/agents/fidelity_score.py`
- NEW: `tests/test_fidelity_score.py`
- NEW: `tests/test_data_travel_brain_sim.py`
- MODIFY: `CHANGELOG.md`

---

#### Task 1.2: Emulation Classifier

**Source**: Brain Emulation Report — simulation vs emulation distinction
**Impact**: Meta-cognition layer that classifies agent behavior quality
**Effort**: Medium

**Acceptance Criteria**:
- [ ] `infra/docker/agents/emulation_classifier.py` implements EmulationClassifier class
- [ ] classify_task() accepts execution trace and returns Classification
- [ ] Emulation indicators: upstream_read, downstream_read, knowledge_consulted, perturbation_generated, causal_explanation_present
- [ ] Simulation indicators: single_module_only, no_downstream_check, no_knowledge_reference, happy_path_only, tests_pass_declaration
- [ ] Classification is deterministic based on indicator count (>= 3 emulation indicators = EMULATION)
- [ ] suggest_elevation() returns specific actions to convert SIMULATION to EMULATION
- [ ] BDD test: given execution trace with known indicators, classification is correct
- [ ] Choreography test: orchestrator to fidelity_score to emulation_classifier produces valid classification

**Files**:
- NEW: `infra/docker/agents/emulation_classifier.py`
- NEW: `tests/test_emulation_classifier.py`
- MODIFY: `CHANGELOG.md`

---

#### Task 1.3: Orchestrator Integration (Fidelity + Classification)

**Source**: Integration requirement
**Impact**: Every task completion now produces fidelity score + classification
**Effort**: Low

**Acceptance Criteria**:
- [ ] orchestrator.py calls FidelityScoreEngine.compute_score() after all gates pass
- [ ] orchestrator.py calls EmulationClassifier.classify_task() after score computation
- [ ] Results are included in the task completion report
- [ ] Feature flag BRAIN_SIM_ENABLED gates both calls (default: true)
- [ ] When disabled, orchestrator behavior is identical to current (no regression)
- [ ] BDD test: full pipeline run produces fidelity score in completion report
- [ ] Data travel test: fidelity score flows from orchestrator to Factory Health Report

**Files**:
- MODIFY: `infra/docker/agents/orchestrator.py`
- MODIFY: `tests/test_orchestrator.py` (add brain sim scenarios)
- MODIFY: `CHANGELOG.md`

---

### Sprint 2: Memory Architecture (Organism: C. elegans hardening)

#### Task 2.1: Context Hierarchy Manager

**Source**: Brain Emulation Report — memory wall mitigation
**Impact**: Reduces context loss during compaction, improves cross-session continuity
**Effort**: High

**Acceptance Criteria**:
- [ ] `infra/docker/agents/context_hierarchy.py` implements ContextHierarchyManager class
- [ ] 5 levels defined with promotion/demotion rules
- [ ] query() returns relevant context items ranked by level (L1 first)
- [ ] report_memory_wall_hit() records what was lost and schedules promotion
- [ ] get_hierarchy_health() returns efficiency metrics (% resolved at L1-L2 vs L4-L5)
- [ ] Promotion rule: item referenced 3+ times in session promotes to L1
- [ ] Demotion rule: item not referenced in 5 tasks demotes one level
- [ ] Persistence: L3-L5 items persist to S3 (scoped by ProjectContext)
- [ ] BDD test: promote item, verify it appears in L1 on next query
- [ ] BDD test: report memory wall hit, verify item is promoted in next session

**Files**:
- NEW: `infra/docker/agents/context_hierarchy.py`
- NEW: `tests/test_context_hierarchy.py`
- MODIFY: `CHANGELOG.md`

---

#### Task 2.2: Brain Sim Metrics Collector

**Source**: Observability requirement
**Impact**: All brain sim metrics are collected, persisted, and queryable
**Effort**: Medium

**Acceptance Criteria**:
- [ ] `infra/docker/agents/brain_sim_metrics.py` implements BrainSimMetricsCollector class
- [ ] Collects all 10 metrics defined in Section 2.9
- [ ] Persists to DynamoDB (same table as DORA metrics, different partition key)
- [ ] get_brain_sim_summary() returns current state of all metrics
- [ ] Integrates with DORACollector.generate_factory_report() to add brain_simulation section
- [ ] BDD test: record metrics, query summary, verify values match
- [ ] Data travel test: metrics flow from collector to Factory Health Report JSON

**Files**:
- NEW: `infra/docker/agents/brain_sim_metrics.py`
- NEW: `tests/test_brain_sim_metrics.py`
- MODIFY: `infra/docker/agents/dora_metrics.py` (add brain_simulation section)
- MODIFY: `CHANGELOG.md`

---

### Sprint 3: Knowledge Layer (Organism: Zebrafish validation)

#### Task 3.1: Knowledge Annotation Layer

**Source**: Brain Emulation Report — molecular annotation
**Impact**: Every module has documented knowledge governance, enabling domain-aware changes
**Effort**: High

**Acceptance Criteria**:
- [ ] `infra/docker/agents/knowledge_annotation.py` implements KnowledgeAnnotationLayer class
- [ ] KnowledgeAnnotation dataclass with module, edge, governing_artifacts, domain_source_of_truth, confidence, annotation_type
- [ ] annotate_module() persists annotation to catalog.db
- [ ] get_governing_knowledge() returns annotations for a module
- [ ] validate_against_source() checks if annotation references existing files
- [ ] detect_stale_annotations() returns annotations older than threshold
- [ ] get_knowledge_gaps() returns modules without any annotation
- [ ] Confidence decay: annotations lose 0.1 confidence per 30 days without revalidation
- [ ] catalog.db schema extended with knowledge_annotations table
- [ ] BDD test: annotate module, query it, verify annotation returned
- [ ] BDD test: age annotation 60 days, verify confidence decayed
- [ ] Choreography test: knowledge lookup during agent tool_use returns relevant annotations

**Files**:
- NEW: `infra/docker/agents/knowledge_annotation.py`
- NEW: `tests/test_knowledge_annotation.py`
- MODIFY: `infra/docker/agents/onboarding/` (add annotation inference)
- MODIFY: `CHANGELOG.md`

---

#### Task 3.2: Knowledge Annotation Onboarding Integration

**Source**: Integration requirement
**Impact**: New repos get automatic knowledge annotations during onboarding
**Effort**: Medium

**Acceptance Criteria**:
- [ ] Onboarding agent infers knowledge annotations for each module via Haiku
- [ ] Inferred annotations have confidence=0.5 (requires human validation for 1.0)
- [ ] Annotations are persisted to catalog.db knowledge_annotations table
- [ ] Generated steering file includes top-5 knowledge annotations for critical modules
- [ ] BDD test: onboard a test repo, verify annotations are created in catalog.db
- [ ] BDD test: verify generated steering references knowledge annotations

**Files**:
- MODIFY: `infra/docker/agents/onboarding/` (multiple modules)
- NEW: `tests/test_onboarding_knowledge_annotations.py`
- MODIFY: `CHANGELOG.md`

---

### Sprint 4: Perturbation and Behavioral (Organism: Zebrafish hardening)

#### Task 4.1: Perturbation Test Engine

**Source**: Brain Emulation Report — causal perturbation experiments
**Impact**: Automatic edge case generation and resilience validation
**Effort**: High

**Acceptance Criteria**:
- [ ] `infra/docker/agents/perturbation_engine.py` implements PerturbationEngine class
- [ ] 8 perturbation strategies implemented (missing_field, extra_field, type_mismatch, boundary_value, encoding_variation, scale_variation, temporal_variation, dependency_failure)
- [ ] generate_perturbations() accepts input schema and returns perturbed inputs
- [ ] run_perturbation_suite() actually executes module with perturbed inputs (no mocks)
- [ ] classify_degradation() returns "graceful" or "partial" or "catastrophic"
- [ ] get_perturbation_coverage() returns % of modules with perturbation tests
- [ ] BDD test: generate perturbations for known schema, verify all strategies produce valid inputs
- [ ] BDD test: run perturbation suite on a module, verify degradation classification
- [ ] Anti-fake: test proves module is actually executed (not just input generated)

**Files**:
- NEW: `infra/docker/agents/perturbation_engine.py`
- NEW: `tests/test_perturbation_engine.py`
- MODIFY: `CHANGELOG.md`

---

#### Task 4.2: Behavioral Benchmark Runner

**Source**: Brain Emulation Report — embodied behavioral tests
**Impact**: Product-level validation with representative workloads
**Effort**: Medium

**Acceptance Criteria**:
- [ ] `infra/docker/agents/behavioral_benchmark.py` implements BehavioralBenchmarkRunner class
- [ ] register_workload() stores workload definition (input + expected output)
- [ ] run_benchmark() executes full pipeline with workload and compares output
- [ ] compare_with_baseline() detects behavioral drift between runs
- [ ] get_behavioral_coverage() returns % of pipeline stages with behavioral tests
- [ ] At least 1 behavioral benchmark registered for the Cognitive WAFR pipeline
- [ ] BDD test: register workload, run benchmark, verify result matches expected
- [ ] BDD test: introduce drift, verify compare_with_baseline detects it

**Files**:
- NEW: `infra/docker/agents/behavioral_benchmark.py`
- NEW: `tests/test_behavioral_benchmark.py`
- MODIFY: `CHANGELOG.md`

---

### Sprint 5: Organism Ladder and Hooks (Organism: Drosophila validation)

#### Task 5.1: Organism Ladder

**Source**: Brain Emulation Report — organism-model validation strategy
**Impact**: Prevents premature scaling, ensures FDE is validated at each complexity level
**Effort**: Medium

**Acceptance Criteria**:
- [ ] `infra/docker/agents/organism_ladder.py` implements OrganismLadder class
- [ ] classify_project() returns organism classification based on complexity metrics
- [ ] can_scale_to_next() enforces gates (emulation_ratio >= 0.7, perturbation_coverage >= 0.5, knowledge_coverage >= 0.6)
- [ ] get_validation_evidence() returns which benchmarks validated current level
- [ ] Integration with squad composer: organism level influences squad size
- [ ] BDD test: classify project with known metrics, verify correct organism
- [ ] BDD test: attempt scale with insufficient metrics, verify gate blocks
- [ ] Choreography test: organism classification flows to squad composer

**Files**:
- NEW: `infra/docker/agents/organism_ladder.py`
- NEW: `tests/test_organism_ladder.py`
- MODIFY: `infra/docker/agents/agent_builder.py` (accept organism input)
- MODIFY: `CHANGELOG.md`

---

#### Task 5.2: Brain Simulation Hooks

**Source**: FDE protocol extension
**Impact**: Real-time enforcement of brain sim principles during agent execution
**Effort**: Low

**Acceptance Criteria**:
- [ ] fde-fidelity-gate.kiro.hook (postTaskExecution): computes fidelity score, warns if < 0.6
- [ ] fde-emulation-check.kiro.hook (postToolUse, write): classifies write as simulation/emulation
- [ ] fde-perturbation-reminder.kiro.hook (preToolUse, write): asks "Did you generate perturbation tests?"
- [ ] All hooks respect BRAIN_SIM_ENABLED feature flag
- [ ] Hooks are additive (do not modify existing hook behavior)
- [ ] BDD test: trigger each hook, verify prompt/action is correct

**Files**:
- NEW: `.kiro/hooks/fde-fidelity-gate.kiro.hook`
- NEW: `.kiro/hooks/fde-emulation-check.kiro.hook`
- NEW: `.kiro/hooks/fde-perturbation-reminder.kiro.hook`
- MODIFY: `.kiro/hooks/fde-adversarial-gate.kiro.hook` (add knowledge annotation question)
- MODIFY: `CHANGELOG.md`

---

### Sprint 6: Portal and Observability (Organism: Drosophila hardening)

#### Task 6.1: Portal Cards — Brain Simulation Dashboard

**Source**: Observability requirement
**Impact**: Visual feedback loop for engineering team on emulation quality
**Effort**: High

**Acceptance Criteria**:
- [ ] 6 portal cards implemented as specified in Section 4.2
- [ ] Cards consume real data from brain_sim_metrics.py (no placeholder data)
- [ ] Thresholds and alerts configured as specified
- [ ] Drill-down navigation works for each card
- [ ] Cards are collapsible (default: show composite score + organism level only)
- [ ] Data travel test: metric recorded appears in portal card within 1 render cycle
- [ ] Anti-fake: remove brain_sim_metrics.py and portal cards show "no data" not cached values

**Files**:
- NEW: `src/portal/components/brain_sim_fidelity_card.js`
- NEW: `src/portal/components/brain_sim_organism_card.js`
- NEW: `src/portal/components/brain_sim_memory_card.js`
- NEW: `src/portal/components/brain_sim_knowledge_card.js`
- NEW: `src/portal/components/brain_sim_perturbation_card.js`
- NEW: `src/portal/components/brain_sim_emulation_card.js`
- NEW: `tests/test_portal_brain_sim.py`
- MODIFY: `src/portal/pages/factory_health.js` (add brain sim section)
- MODIFY: `CHANGELOG.md`

---

#### Task 6.2: OTEL Spans Integration

**Source**: Observability requirement
**Impact**: Distributed tracing for brain sim ecosystem
**Effort**: Low

**Acceptance Criteria**:
- [ ] 5 span types emitted as specified in Section 4.4
- [ ] Spans are children of existing orchestrator spans (proper parent-child)
- [ ] Span attributes include all specified fields
- [ ] Spans are emitted only when BRAIN_SIM_ENABLED=true
- [ ] BDD test: run pipeline, verify spans appear in trace output

**Files**:
- MODIFY: `infra/docker/agents/fidelity_score.py` (add span emission)
- MODIFY: `infra/docker/agents/emulation_classifier.py` (add span emission)
- MODIFY: `infra/docker/agents/context_hierarchy.py` (add span emission)
- MODIFY: `infra/docker/agents/perturbation_engine.py` (add span emission)
- MODIFY: `infra/docker/agents/knowledge_annotation.py` (add span emission)
- NEW: `tests/test_brain_sim_otel.py`
- MODIFY: `CHANGELOG.md`

---

#### Task 6.3: Golden Principles Extension + Anti-Fake Validation

**Source**: Section 5 — No fake implementations
**Impact**: Mechanical detection of fake/dead brain sim components
**Effort**: Low

**Acceptance Criteria**:
- [ ] golden_principles.py extended with 4 BRAIN_SIM_PRINCIPLES
- [ ] no_dead_metrics: every metric has a consumer
- [ ] no_placeholder_scores: compute_score uses real TestResults
- [ ] no_orphan_annotations: every annotation references existing file
- [ ] no_fake_perturbations: perturbation tests show execution trace
- [ ] BDD test: introduce a dead metric, golden principles detects it
- [ ] BDD test: introduce orphan annotation, golden principles detects it

**Files**:
- MODIFY: `infra/docker/agents/golden_principles.py`
- MODIFY: `tests/test_golden_principles.py`
- MODIFY: `CHANGELOG.md`

---

## Execution Order Summary

| Sprint | Tasks | Organism Validated | Key Deliverable |
|--------|-------|-------------------|-----------------|
| 1 | 1.1, 1.2, 1.3 | C. elegans (core) | Fidelity Score + Classification in every task |
| 2 | 2.1, 2.2 | C. elegans (hardened) | Memory hierarchy + metrics collection |
| 3 | 3.1, 3.2 | Zebrafish (core) | Knowledge annotations in onboarding |
| 4 | 4.1, 4.2 | Zebrafish (hardened) | Perturbation + behavioral testing |
| 5 | 5.1, 5.2 | Drosophila (core) | Organism ladder + enforcement hooks |
| 6 | 6.1, 6.2, 6.3 | Drosophila (hardened) | Portal visibility + anti-fake guards |

---

## DoD Checklist (apply to each task)

Before committing any task:
- [ ] BDD tests written and passing
- [ ] Data travel test proves end-to-end flow (no fake integrations)
- [ ] Choreography test validates component interactions
- [ ] CHANGELOG updated
- [ ] Language lint passes (zero violations)
- [ ] All existing tests still pass
- [ ] Feature flag BRAIN_SIM_ENABLED gates new functionality
- [ ] Anti-fake adversarial checklist answered (5 questions from Section 5.6)
- [ ] No hardcoded values in score computation
- [ ] No placeholder data in portal cards
- [ ] Consumer exists for every metric produced

---

## References

- State of Brain Emulation Report 2025: arXiv:2510.15745 (https://arxiv.org/abs/2510.15745)
- Research Study: `docs/design/scaling-brain-simulation-study.md`
- FDE Design Pattern: `docs/design/forward-deployed-ai-engineers.md`
- Agentic Squad Architecture: `docs/adr/ADR-019-agentic-squad-architecture.md`
- COE-052 Post-Mortem: `docs/corrections-of-error.md`
- ADR-004 Circuit Breaker: `docs/adr/ADR-004-circuit-breaker-error-classification.md`
- ADR-013 Enterprise Autonomy: `docs/adr/ADR-013-enterprise-grade-autonomy-and-observability.md`

Content was rephrased for compliance with licensing restrictions. Original sources linked above.
