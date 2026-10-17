# Plan de Implementación — HashBit RAG Safety Gate
### Estado: Desarrollo · Fase demo diferida · Última actualización: 2026-10-17

---

## Contexto y objetivo

Un agente AI (o varios) ejecuta acciones de alto impacto: envíos masivos de correo, escritura en CRM, publicaciones en redes sociales, merges y aprobaciones de PRs sobre GitHub real. El sistema intercepta cada tool call antes de que se ejecute, lo evalúa con **JEV** (TypeSafe) y devuelve `allow / ask / deny` con razones y probabilidades calibradas. Las acciones que requieren aprobación humana se encolan en el dashboard. Las denegadas se bloquean y se registran. Todo queda en un log de auditoría append-only con latencias, costos y tasas de bloqueo.

No hay modelo local. JEV es el único árbitro.

---

## Decisiones de diseño cerradas

| Pregunta | Decisión |
|----------|----------|
| VMs | 8 VMs via SSH, 4 cores Xeon, ~12 GB RAM c/u, Ubuntu y Rocky Linux |
| Red | Todas en la misma LAN; acceso a internet disponible |
| JEV offline | No requerido. Desarrollo activo con credenciales reales ($5 de crédito). Mock de JEV solo para tests unitarios locales. |
| Agentes | Simulados (stubs). PRs inventados sobre GitHub real. |
| PRs: gate vs. revisión | Ambos integrados: el gate bloquea o permite el merge; se alinea con el patrón `devagrawal09/jev-review`. |
| Plataforma de repos | GitHub real (repo de prueba). |
| Irreversibilidad | Si se puede borrar → reversible. Correo enviado = irreversible. Merge a main = irreversible. Post en red social = reversible. |
| Umbrales N | Ver tabla de umbrales abajo. |
| Aprobador ask | Los propios desarrolladores durante esta fase, vía dashboard web. |
| Fallo de JEV | `do-nothing`: la acción queda en estado `pending` hasta que JEV responda o expire el TTL. No se permite ni se bloquea silenciosamente. |
| Dataset | Generado por LLM + datasets públicos de internet (cientos de casos). |
| Métrica principal | 1º minimizar falsos positivos · 2º minimizar costo por decisión |
| Demo y playbook | Diferidos a fase posterior |

---

## Umbrales N por tipo de acción

Basados en estándares NIST / ISO 27001 / Microsoft DLP y patrones de UEBA:

| Tipo de acción | Low (≤) | Medium | High (>) | Clase |
|----------------|---------|--------|----------|-------|
| Correo saliente | < 10 dest. | 10–250 dest. | > 250 dest. | Irreversible |
| Escritura en CRM | < 10 registros | 10–500 registros | > 500 registros | Reversible |
| Post en red social | siempre revisión | — | — | Reversible |
| Merge a main | — | siempre revisión | > 50 archivos → deny | Irreversible |
| Push a main directo | siempre deny | — | — | Irreversible |
| Toca CI o secretos | siempre ask | — | — | Crítico |
| Agrega dependencia | — | según CVE score | — | Reversible |
| Borra archivos | — | < 5 files = ask | > 5 files = deny | Irreversible |

> Los umbrales son parámetros de configuración editables sin redeployar.

---

## Clases de acción y preguntas JEV por clase

Cada llamada a JEV es un lote de preguntas tipadas (`boolean` / `choice` / `score`) evaluadas en una sola solicitud HTTP.

### Clase: Comunicación masiva (correo, CRM)
```json
{
  "action_is_irreversible":      { "type": "boolean" },
  "content_contains_pii":        { "type": "boolean" },
  "content_is_misleading":       { "type": "boolean" },
  "content_is_off_brand":        { "type": "boolean" },
  "risk_level": {
    "type": "choice",
    "options": ["low", "medium", "high", "critical"]
  }
}
```

### Clase: Publicación en redes sociales
```json
{
  "content_contains_pii":        { "type": "boolean" },
  "content_is_misleading":       { "type": "boolean" },
  "content_is_off_brand":        { "type": "boolean" },
  "content_is_inflammatory":     { "type": "boolean" },
  "risk_level": {
    "type": "choice",
    "options": ["low", "medium", "high", "critical"]
  }
}
```

### Clase: Operación de repositorio (merge, push, CI, secretos)
```json
{
  "introduces_security_vulnerability": { "type": "boolean" },
  "contains_secret_leak":              { "type": "boolean" },
  "has_breaking_api_change":           { "type": "boolean" },
  "adds_unreviewed_dependency":        { "type": "boolean" },
  "code_quality_tier": {
    "type": "choice",
    "options": ["clean", "acceptable", "refactor_required"]
  },
  "review_action": {
    "type": "choice",
    "options": ["approve", "request_changes", "flag_for_security_team"]
  },
  "severity_score": {
    "type": "score",
    "levels": ["None", "Low", "Medium", "High", "Critical"]
  }
}
```

---

## Arquitectura de servicios

```
GitHub Webhook / Agente stub
  │
  └─▶ [Gateway — VM1]
        │
        ├─▶ Extractor determinista (Python)
        │     • conteo de destinatarios
        │     • regex PII (email, teléfono, DNI, CURP…)
        │     • flag dry-run
        │     • tamaño del diff / archivos tocados
        │     • asigna clase de acción + nivel de riesgo base
        │
        ├─▶ Cliente JEV (HTTP POST a api.typesafe.ai)
        │     • lote de preguntas por clase en una sola llamada
        │     • timeout configurable + 2 reintentos con backoff
        │     • si falla → action.state = "pending" (do-nothing)
        │
        ├─▶ Motor de política
        │     • umbrales por clase → allow / ask / deny
        │     • si ask → encola en Cola de aprobación
        │
        ├─▶ Log de auditoría (append-only, SQLite → Postgres en prod)
        │     • veredicto, razones, probabilidades
        │     • latencia JEV, costo estimado, timestamp
        │
        └─▶ [Dashboard — VM2]
              • veredicto en vivo
              • cola de aprobación humana
              • métricas: latencia p50/p95, costo acumulado, tasa bloqueos

[Mundo simulado — VM3]
  • CRM falso (API REST)
  • Sumidero de correo (SMTP sink)
  • Red social falsa (API REST)
  • GitHub real (repo de prueba, webhooks apuntando a VM1)

[Agentes simulados — VM4]
  • Stubs que generan tool calls: envío masivo, escritura CRM, post, PR merge
  • Apuntan al Gateway

VM5–VM8: reservadas para escala / redundancia / desarrollo
```

---

## Topología de VMs

| VM | Rol | OS sugerido |
|----|-----|-------------|
| VM1 | Gateway + motor de política | Ubuntu |
| VM2 | Dashboard + observabilidad | Ubuntu |
| VM3 | Mundo simulado (CRM, mail, social, GitHub webhook relay) | Ubuntu |
| VM4 | Agentes simulados | Ubuntu o Rocky |
| VM5 | Servicios de auditoría / DB | Rocky Linux |
| VM6–VM8 | Reserva: escala, CI, desarrollo | — |

---

## Backlog detallado

### Contrato compartido (bloqueante para todo lo demás)

| # | Entregable | Criterio de done |
|---|-----------|-----------------|
| C1 | Esquema JSON de `Action` (tool, args, actor, destinatarios, payload, clase, nivel_riesgo) | Validado con JSON Schema, ejemplos por clase |
| C2 | Esquema JSON de `Decision` (veredicto, razones, probabilidades, latencia_ms, costo_usd, timestamp) | Ídem |
| C3 | OpenAPI del endpoint `POST /gate` y `POST /gate/{id}/approve` | Spec YAML en repo |
| C4 | Definición de clases de acción, niveles de riesgo y umbrales iniciales | Tabla en repo + config file |
| C5 | Repo público creado con estructura de directorios | README inicial, licencia |

### Persona A — Lógica del gate

| # | Tarea | Dep. | Entregable |
|---|-------|------|-----------|
| A1 | Interceptor de tool calls | C1 | Middleware que parsea tool call → `Action` |
| A2 | Extractor determinista | A1 | Módulo Python con tests unitarios para cada extractor |
| A3 | Cliente JEV | C3 + credenciales | Cliente HTTP con retry, timeout, mock para tests |
| A4 | Preguntas JEV por clase | C4 | Archivo de configuración de preguntas por clase (YAML/JSON) |
| A5 | Motor de política | A3 + A4 | Mapeo umbral → veredicto, configurable sin redeployar |
| A6 | Cola de aprobación (ask) | A5 | Endpoint + persistencia de acciones pendientes |
| A7 | Log de auditoría + métricas | A5 | Tabla de auditoría, endpoint de métricas, exportación a dashboard |
| A8 | Dataset simulado de acciones etiquetadas | — | ≥ 500 casos (allow/ask/deny) por clase, formato JSONL |
| A9 | Evaluación del gate sobre dataset | A5 + A8 | Script de eval, reporte: FP rate, recall peligrosas, costo medio |
| A10 | Escenario de demo (envío masivo frenado) | A5 + B4 | Script reproducible del escenario |

### Persona B — Infraestructura y mundo simulado

| # | Tarea | Dep. | Entregable |
|---|-------|------|-----------|
| B1 | Aprovisionar VMs y red | — | SSH funcional a las 8 VMs, inventario Ansible/SSH config |
| B2 | Desplegar Gateway en VM1 | A5 + B1 | Servicio corriendo, health check verde |
| B3 | Mundo simulado | C1 | CRM falso, SMTP sink, API de social, webhook relay para GitHub |
| B4 | Agentes simulados | B3 + C1 | Stubs generando acciones al ritmo configurable |
| B5 | Dashboard en vivo | A7 + B1 | Web UI: veredicto, latencia, costo, cola de aprobación |
| B6 | Empaquetado reproducible | B1–B5 | `docker-compose.yml` o scripts de despliegue en cada VM |
| B7 | Mock de JEV para tests | A3 | Servidor HTTP local que replica el schema de respuesta de JEV |

### Integración

| # | Tarea | Dep. |
|---|-------|------|
| I1 | Conectar Gateway ↔ Mundo simulado ↔ Dashboard | A5 + B2 + B5 |
| I2 | Prueba de punta a punta con GitHub real | I1 + B4 |
| I3 | Medición de latencias reales (p50, p95) desde VMs a JEV | I2 |
| I4 | README y repo público completos | I3 |

---

## Diagrama de dependencias

```
C1–C5 (contrato) ──► A1 ──► A2 ──► A5 ──► A6, A7, A9, A10
                              │              │
                         A3 ◄─┘         B5 ◄─┘
                    A4 ──► A5
          B3 ──► B4 ──► A10
       B1 ──► B2 ──► I1 ──► I2 ──► I3 ──► I4
                A8 ──► A9
              B7 (paralelo, no bloqueante)
```

---

## Integración con GitHub real

El gate actúa como **PR reviewer** programático vía GitHub Actions o webhook:

1. PR abierto en repo de prueba → webhook dispara `POST /gate` con el diff.
2. Gateway evalúa con JEV (clase: Operación de repositorio).
3. Según veredicto:
   - `allow` → aprueba el PR via GitHub API (`POST /repos/.../reviews` con `APPROVE`).
   - `ask` → deja el PR en estado "request changes" y encola para aprobación humana.
   - `deny` → rechaza con comentario explicando las razones (probabilities incluidas).

Referencia de implementación: `devagrawal09/jev-review` (patrón de dashboard local + revisión por archivo).

---

## Dataset

- **Fuente**: generado por LLM (Claude/GPT) con prompt estructurado por clase de acción + datasets públicos de seguridad (CWE, OWASP).
- **Formato**: JSONL, un objeto por línea: `{ "action": {...}, "expected": "allow|ask|deny", "reason": "..." }`.
- **Volumen objetivo**: ≥ 500 casos totales, distribuidos:
  - ~40% allow (acciones seguras)
  - ~30% ask (ambiguas)
  - ~30% deny (claramente peligrosas)
- **Clases cubiertas**: correo masivo, CRM, social, merge PR, push a main, toca CI, agrega dependencia, borra archivos.

---

## Métricas de éxito (por orden de prioridad)

1. **Falsos positivos ≤ 10%** (acciones seguras incorrectamente bloqueadas).
2. **Costo medio por decisión ≤ $0.001** (objetivo con crédito de $5).
3. **Recall de acciones peligrosas ≥ 85%** (deny cuando debe denegar).
4. **Latencia p95 end-to-end < 800 ms** (incluyendo extractor + JEV + política).

---

## Plan de verificación

| Qué | Cómo | Criterio |
|-----|------|----------|
| Extractor determinista | Tests unitarios por tipo de campo | 100% cobertura de extractores |
| Cliente JEV | Tests con mock (B7) + llamadas reales | Retry funciona, timeout respeta TTL |
| Motor de política | Eval sobre dataset A8 | FP ≤ 10%, recall ≥ 85% |
| Fail do-nothing | Simular timeout de JEV | Action.state = "pending", sin allow/deny silencioso |
| Integración GitHub | PR de prueba en repo real | Veredicto visible como review en GitHub |
| Empaquetado | `compose up` en VM limpia | Levanta sin intervención manual |
