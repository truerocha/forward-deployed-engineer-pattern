# Portal Import Plan — Code Factory Dashboard

> Date: 2026-05-07
> Target: `infra/dashboard/`
> Deploy: `bash scripts/deploy-dashboard.sh --profile profile-rocand`
> Live URL: https://d3btj6a4igoa8k.cloudfront.net
> API Base: https://4qhn5ly26e.execute-api.us-east-1.amazonaws.com

---

## 1. Context

O portal desenvolvido externamente será importado para substituir o dashboard atual do Code Factory. O destino é o diretório `infra/dashboard/` — tudo que estiver nesse diretório é sincronizado para S3 e servido via CloudFront.

### Infraestrutura existente (não muda)

| Componente | ID | Função |
|-----------|-----|--------|
| S3 Bucket | `fde-dev-artifacts-785640717688` | Armazena os arquivos do dashboard em `/dashboard/*` |
| CloudFront | `E2RBVCKZAI7R6I` | CDN que serve o portal (HTTPS, edge caching) |
| CloudFront OAC | — | Permite CloudFront ler do S3 (bucket é privado) |
| API Gateway | `4qhn5ly26e` | Serve os endpoints `/status/*` que o portal consome |
| Deploy Script | `scripts/deploy-dashboard.sh` | Injeta API URL + faz `s3 sync` + invalida cache |

---

## 2. Estrutura Atual (será substituída)

```
infra/dashboard/                    ← RAIZ DO DEPLOY
├── index.html                      ← Entry point (CloudFront default root object)
├── css/
│   └── factory.css                 ← Design system
├── js/
│   ├── api.js                      ← State management + fetch
│   └── router.js                   ← Hash routing
├── views/
│   ├── pipeline.js                 ← Pipeline Activity view
│   ├── agents.js                   ← Autonomous Units view
│   ├── reasoning.js                ← Chain of Thought view
│   ├── gates.js                    ← Gate Decisions view
│   └── health.js                   ← DORA + Health view
└── img/
    └── proserve-logo.png           ← Brand logo (header)
```

---

## 3. Requisitos Obrigatórios para Importação

### 3.1 Meta Tag da API (CRÍTICO)

O `index.html` do portal importado **DEVE** conter esta meta tag exatamente assim:

```html
<meta name="factory-api-url" content="">
```

**Por quê**: O script `deploy-dashboard.sh` executa:
```bash
sed "s|<meta name=\"factory-api-url\" content=\"\">|<meta name=\"factory-api-url\" content=\"$API_URL\">|"
```

Se essa meta tag não existir ou estiver com formato diferente, o portal não receberá a URL da API e não conseguirá buscar dados.

**Onde colocar**: Dentro do `<head>`, antes de qualquer `<script>`.

### 3.2 Paths Relativos (CRÍTICO)

Todos os caminhos de assets devem ser **relativos**, não absolutos:

| ✅ Correto | ❌ Incorreto |
|-----------|-------------|
| `src="css/style.css"` | `src="/css/style.css"` |
| `src="./js/app.js"` | `src="/js/app.js"` |
| `src="img/logo.png"` | `src="/img/logo.png"` |
| `href="css/main.css"` | `href="/dashboard/css/main.css"` |

**Por quê**: O CloudFront serve o portal de `https://domain/` como default root. Paths absolutos com `/` funcionam. Mas se no futuro o portal for servido de um subpath, paths relativos são mais resilientes.

### 3.3 Sem Dependências Externas Obrigatórias (IMPORTANTE)

| Tipo | Permitido | Não Permitido |
|------|-----------|---------------|
| Google Fonts (`fonts.googleapis.com`) | ✅ Enhancement — portal funciona sem | — |
| CDN de framework (React CDN, Vue CDN) | ❌ | Bloqueado em ambientes enterprise |
| Libs locais (bundled no próprio portal) | ✅ | — |
| Fetch para API externa (que não seja a nossa) | ⚠️ Avaliar | Pode ser bloqueado por CORS/firewall |

**Regra**: O portal deve funcionar 100% com os arquivos locais + a API do Code Factory. Fonts externas são nice-to-have.

### 3.4 Encoding e Charset

```html
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
```

Garantir que o `index.html` tem charset UTF-8 declarado.

---

## 4. O Que Copiar

### Checklist de Importação

Copie **TUDO** que compõe o portal para `infra/dashboard/`. A estrutura de pastas é livre — o deploy sincroniza o diretório inteiro.

| # | Item | Obrigatório | Notas |
|---|------|-------------|-------|
| 1 | `index.html` | ✅ SIM | Entry point. Deve ter a meta tag `factory-api-url`. |
| 2 | Todos os `.css` | ✅ SIM | Qualquer pasta (css/, styles/, assets/css/) |
| 3 | Todos os `.js` | ✅ SIM | Qualquer pasta (js/, src/, dist/, assets/js/) |
| 4 | Imagens (`.png`, `.jpg`, `.svg`, `.gif`, `.ico`) | ✅ SIM | Qualquer pasta (img/, images/, assets/) |
| 5 | Fontes locais (`.woff`, `.woff2`, `.ttf`) | ✅ se referenciadas | Se o CSS faz `@font-face` com path local |
| 6 | `favicon.ico` ou `favicon.svg` | Recomendado | Fica na raiz do portal |
| 7 | `manifest.json` / `site.webmanifest` | Opcional | Se for PWA |
| 8 | Subpáginas HTML adicionais | Se existirem | Se o portal tem múltiplos `.html` |
| 9 | Dados estáticos (`.json` fixtures) | Se referenciados | Mock data para demo mode |
| 10 | `robots.txt` | Opcional | Se quiser controlar indexação |

### O Que NÃO Copiar

| Item | Motivo |
|------|--------|
| `node_modules/` | Não vai para produção |
| `package.json`, `package-lock.json` | Build artifacts, não runtime |
| `.git/` | Controle de versão do portal fonte |
| `src/` (se houver build step) | Copiar apenas o output (`dist/` ou `build/`) |
| `.env`, `.env.local` | Secrets — nunca no S3 |
| `vite.config.*`, `webpack.config.*` | Build config, não runtime |
| `tsconfig.json` | TypeScript config, não runtime |
| `README.md` do portal | Documentação interna do portal |

---

## 5. Procedimento de Importação

### Passo 1: Limpar o destino

```bash
# Remove tudo exceto a pasta img/ (preserva o logo se quiser)
rm -rf infra/dashboard/css
rm -rf infra/dashboard/js
rm -rf infra/dashboard/views
rm -f  infra/dashboard/index.html

# Se quiser limpar TUDO (inclusive logo):
# rm -rf infra/dashboard/*
```

### Passo 2: Copiar o portal

```bash
# Se o portal tem build step (React, Vue, Vite):
cp -r /path/to/seu-portal/dist/* infra/dashboard/

# Se o portal é estático (sem build):
cp -r /path/to/seu-portal/* infra/dashboard/

# Se veio de um zip:
unzip portal.zip -d infra/dashboard/
```

### Passo 3: Validar requisitos

```bash
# 1. Meta tag existe?
grep -q 'factory-api-url' infra/dashboard/index.html && echo "✅ Meta tag OK" || echo "❌ FALTA meta tag"

# 2. Paths absolutos?
ABSOLUTE=$(grep -rn 'src="/' infra/dashboard/ --include="*.html" | wc -l)
echo "Paths absolutos em src: $ABSOLUTE (deve ser 0)"

ABSOLUTE_HREF=$(grep -rn 'href="/' infra/dashboard/ --include="*.html" | grep -v '#' | wc -l)
echo "Paths absolutos em href: $ABSOLUTE_HREF (deve ser 0)"

# 3. Arquivos JS referenciados existem?
grep -oP 'src="[^"]+\.js"' infra/dashboard/index.html | sed 's/src="//;s/"//' | while read f; do
  [ -f "infra/dashboard/$f" ] && echo "✅ $f" || echo "❌ FALTA: $f"
done

# 4. Arquivos CSS referenciados existem?
grep -oP 'href="[^"]+\.css"' infra/dashboard/index.html | sed 's/href="//;s/"//' | while read f; do
  [ -f "infra/dashboard/$f" ] && echo "✅ $f" || echo "❌ FALTA: $f"
done
```

### Passo 4: Adicionar meta tag (se não existir)

Se o portal não tem a meta tag, adicione logo após `<meta charset="utf-8">`:

```bash
sed -i '' 's|<meta charset="utf-8">|<meta charset="utf-8">\n<meta name="factory-api-url" content="">|' infra/dashboard/index.html
```

### Passo 5: Deploy

```bash
bash scripts/deploy-dashboard.sh --profile profile-rocand
```

Output esperado:
```
━━━ Deploy Dashboard ━━━
  → Reading terraform outputs...
  ✅ Account: 785640717688
  ✅ API URL: https://4qhn5ly26e.execute-api.us-east-1.amazonaws.com
  ✅ Bucket: fde-dev-artifacts-785640717688
  → Injecting API URL into dashboard...
  → Syncing dashboard to s3://fde-dev-artifacts-785640717688/dashboard/ (SSE-S3)...
  → Invalidating CloudFront cache (E2RBVCKZAI7R6I)...
  ✅ Cache invalidation in progress

═══════════════════════════════════════════════════════════
  🟢 Dashboard deployed: https://d3btj6a4igoa8k.cloudfront.net
  📊 Status API: https://4qhn5ly26e.execute-api.us-east-1.amazonaws.com/status/tasks
═══════════════════════════════════════════════════════════
```

### Passo 6: Verificar no browser

1. Abrir https://d3btj6a4igoa8k.cloudfront.net
2. Verificar que o portal carrega (sem 404 no console)
3. Verificar que a API conecta (dados aparecem, ou mensagem de "no tasks" se não houver tasks ativas)
4. Testar navegação entre seções
5. Testar tema dark/light (se aplicável)

---

## 6. Integração com a API do Code Factory

### Endpoints Disponíveis

| Método | Path | Descrição | Resposta |
|--------|------|-----------|----------|
| GET | `/status/tasks` | Lista tasks (últimas 24h) com metrics, DORA, events | JSON completo |
| GET | `/status/tasks?repo=owner/repo` | Filtrado por repositório | JSON filtrado |
| GET | `/status/tasks/{task_id}/reasoning` | Timeline completa de uma task | Events + gate summary |
| GET | `/status/health` | Health checks do sistema | Status + checks array |

### Como Consumir no Portal

```javascript
// Ler a URL da API injetada pelo deploy
const API_URL = document.querySelector('meta[name="factory-api-url"]')?.content || '';

// Fetch tasks
const response = await fetch(`${API_URL}/status/tasks`, {
  headers: { 'Accept': 'application/json' }
});
const data = await response.json();

// data.tasks — array de tasks
// data.metrics — { active, completed_24h, failed_24h, avg_duration_ms, ... }
// data.dora — { level, lead_time_avg_ms, success_rate_pct, throughput_24h, ... }
// data.projects — array de { repo, display_name, task_count, active }
```

### Schema de Eventos (para Reasoning/Gates views)

Cada task tem um array `events[]` com até 20 eventos (últimos). Para a timeline completa, use o endpoint `/reasoning`.

```javascript
// Evento básico
{ "ts": "2026-05-07T14:30:00Z", "type": "system", "msg": "Pipeline started" }

// Evento enriquecido (Phase B)
{
  "ts": "2026-05-07T14:30:05Z",
  "type": "gate",
  "msg": "Concurrency guard: 1/2 slots used — proceeding",
  "gate_name": "concurrency",      // opcional
  "gate_result": "pass",           // opcional: "pass" | "fail"
  "criteria": "max_concurrent=2",  // opcional
  "phase": "intake",              // opcional
  "context": "...",               // opcional (max 300 chars)
  "autonomy_level": "L3",        // opcional
  "confidence": "high"           // opcional
}
```

### Pipeline Stages (para progress bars)

```javascript
const STAGES = ['ingested', 'workspace', 'reconnaissance', 'intake', 'engineering', 'testing', 'review', 'completion'];

// Cada task tem:
// task.current_stage — string (e.g., "engineering")
// task.stage_progress.current — int (1-8)
// task.stage_progress.percent — int (0-100)
```

### Status Mapping

| DynamoDB Status | Dashboard Display | Cor |
|----------------|-------------------|-----|
| PENDING | `pending` | cinza |
| READY | `ready` | indigo |
| IN_PROGRESS / RUNNING | `running` | roxo |
| COMPLETED | `completed` | verde |
| FAILED / DEAD_LETTER | `failed` | vermelho |
| BLOCKED | `blocked` | amarelo |

---

## 7. Troubleshooting

| Problema | Causa | Solução |
|----------|-------|---------|
| Portal não carrega (404) | `index.html` não está na raiz de `infra/dashboard/` | Verificar que não ficou em subpasta |
| CSS/JS não carrega (404) | Paths absolutos ou arquivo faltando | Rodar validação do Passo 3 |
| "No API URL" no console | Meta tag ausente ou formato errado | Adicionar `<meta name="factory-api-url" content="">` |
| API retorna CORS error | Não deveria — API tem `Access-Control-Allow-Origin: *` | Verificar se não está fazendo request para URL errada |
| Dados não aparecem | Nenhuma task nas últimas 24h | Normal — label uma issue com `factory-ready` para testar |
| Cache antigo (portal velho aparece) | CloudFront cache não invalidou ainda | Esperar ~30s ou forçar: `aws cloudfront create-invalidation --distribution-id E2RBVCKZAI7R6I --paths "/*"` |
| Fontes não carregam | `@font-face` com path errado | Verificar que os `.woff2` estão no path referenciado |
| Imagens quebradas | Path relativo incorreto | Verificar `src="img/..."` vs onde o arquivo realmente está |

---

## 8. Rollback

Se a importação der errado e precisar voltar ao portal anterior:

```bash
# O portal anterior está no git
git checkout -- infra/dashboard/

# Re-deploy
bash scripts/deploy-dashboard.sh --profile profile-rocand
```

---

## 9. Pós-Importação (Opcional)

Após confirmar que o portal importado funciona:

1. **Atualizar `portal_design_doc.md`** com a nova arquitetura do portal importado
2. **Commit**: `git add infra/dashboard/ && git commit -m "feat: import custom portal with rail navigation"`
3. **Verificar `.gitignore`** — garantir que `node_modules/`, `.env`, `dist/` (se build local) estão ignorados
4. **Atualizar o README** se o processo de desenvolvimento do portal mudou
