# MyNameIsJev

> Guía del runtime actual v2.0. El [README.md](README.md) conserva la propuesta original v0.1 y enlaza a esta guía.

> **AI Safety Gate** — intercepta acciones de agentes y aplica una política de seguridad con JEV.

MyNameIsJev se coloca entre agentes y herramientas de alto impacto: envíos de correo, escrituras en CRM, publicaciones sociales y operaciones sobre pull requests. Antes de ejecutar una tool call, el agente la envía al gateway. El gateway extrae hechos deterministas, evalúa preguntas semánticas tipadas, aplica umbrales configurables y registra el resultado.

El contrato vigente es la versión 2.0. Su fuente de verdad es [docs/contract.md](docs/contract.md), los esquemas están en [docs/schemas/](docs/schemas/) y la API se describe en [contracts/openapi.yaml](contracts/openapi.yaml). El [plan de implementación](implementation_plan.md) contiene la visión y las decisiones de producto; las secciones que describen infraestructura futura no implican que esa infraestructura ya esté desplegada.

El contenido previo no compatible se conservó como referencia: [README v0.1](docs/history/README.v0.1.md), [OpenAPI v0.1](contracts/history/v0.1/openapi.yaml), [thresholds v0.1](config/thresholds.v0.1.yaml), [env v0.1](docs/history/.env.example.v0.1) y los esquemas/ejemplos versionados en `contracts/history/` y `contracts/examples/v0.1/`. Los documentos activos de v2.0 añaden la implementación actual sin presentar las interfaces antiguas como runtime vigente.

## Tabla de contenido

- [Problema y alcance](#problema-y-alcance)
- [Arquitectura](#arquitectura)
- [Estado actual](#estado-actual)
- [Estructura del repositorio](#estructura-del-repositorio)
- [Contrato y decisiones](#contrato-y-decisiones)
- [Clases, umbrales y preguntas](#clases-umbrales-y-preguntas)
- [API](#api)
- [Instalación y ejecución](#instalación-y-ejecución)
- [Configuración](#configuración)
- [Dataset y evaluación](#dataset-y-evaluación)
- [Infraestructura objetivo](#infraestructura-objetivo)
- [Desarrollo y validación](#desarrollo-y-validación)
- [Métricas](#métricas)
- [Licencia](#licencia)

## Problema y alcance

Los agentes autónomos pueden ejecutar acciones equivocadas: enviar una campaña a demasiados destinatarios, alterar muchos registros, publicar contenido engañoso o subir cambios peligrosos a `main`. El gate intercepta estas acciones y devuelve uno de tres veredictos: `allow`, `ask` o `deny`.

JEV se usa para juicios semánticos con preguntas tipadas (`boolean`, `choice`, `score`). El código local realiza las tareas deterministas que no se delegan al modelo: conteos, comparación con umbrales, detección de patrones PII y lectura de metadatos del diff. La política combina ambas señales.

El contrato define datos sintéticos. El adaptador de JEV no presupone un formato HTTP que todavía no se ha documentado; la integración real requiere la documentación oficial o un ejemplo válido de request y response.

## Arquitectura

```text
Agente simulado o webhook
  │
  └── POST /gate
        │
        ├── Interceptor: normaliza tool call como Action
        ├── Extractor determinista: conteos, PII, diff y riesgo calculado
        ├── Cliente JEV: preguntas tipadas por clase en lote
        ├── Motor de política: reglas duras + umbrales configurables
        ├── Auditoría SQLite: acción, decisiones y eventos
        └── Cola humana: se crea cuando el veredicto es ask
```

| Estado/resultado | Significado | Acción del consumidor |
|---|---|---|
| `allow` | El gate permite continuar. | Ejecutar la tool. |
| `ask` | Se requiere revisión humana. | Esperar resolución; no ejecutar mientras esté pendiente. |
| `deny` | Acción rechazada. | No ejecutar. |
| `pending` | JEV no respondió; política do-nothing. | No ejecutar y esperar hasta resolver o vencer el TTL. |
| `expired` | Venció el TTL de evaluación. | Mantener sin ejecutar; nunca convertirlo automáticamente en `allow`. |

Una resolución humana de `ask` cambia la decisión a `allow` o `deny` y genera eventos de auditoría. Una aprobación vencida se rechaza automáticamente según el TTL configurado.

## Estado actual

- **A1–A7:** interceptor, extractor, interfaz/cliente JEV con transporte inyectable, preguntas por clase, política, cola de aprobación y auditoría/métricas implementados.
- **A8:** dataset sintético JSONL generado y validable en `eval/data/actions.jsonl`.
- **A9:** evaluación reproducible en `eval/run_eval.py`; el reporte guardado es `eval/report.json`.
- La implementación HTTP real de JEV no está conectada. Si no se inyecta un transporte, el gateway devuelve `pending` al fallar JEV y no autoriza ejecución.
- `MockJev` sirve para pruebas y evaluación local. Los resultados con el mock miden coherencia entre las etiquetas sintéticas y las reglas, no la calidad de JEV ni la generalización a tráfico real.
- El dashboard, las VMs, los simuladores de mundo y el despliegue con GitHub real aparecen como trabajo de integración/infraestructura en el plan, pero no forman parte del runtime presente en este repositorio.

## Estructura del repositorio

```text
MyNameIsJev/
├── contracts/
│   ├── examples/              # Ejemplos v0.1 conservados y algunos agregados v2.0
│   ├── history/v0.1/          # Contratos anteriores conservados
│   ├── schemas/               # Copias de contrato; OpenAPI referencia docs/schemas/
│   └── openapi.yaml           # API OpenAPI 3.1
├── config/
│   ├── thresholds.yaml        # Propuesta original con enlace a v2.0
│   ├── thresholds.v2.yaml     # Espejo YAML v2.0; runtime usa docs/policy.defaults.json
│   └── questions/             # Preguntas anteriores conservadas como referencia
├── docs/
│   ├── contract.md            # Fuente de verdad del contrato v2.0
│   ├── history/               # README y env anteriores conservados
│   ├── schemas/               # JSON Schema Draft 2020-12
│   ├── examples/              # Casos válidos e inválidos
│   ├── policy.defaults.json   # Umbrales y opciones de runtime
│   ├── jev_questions.json     # Preguntas tipadas por clase
│   └── validate_contract.py   # Validador de ejemplos del contrato
├── eval/
│   ├── data/actions.jsonl     # Dataset sintético etiquetado
│   ├── generate_dataset.py
│   ├── validate_dataset.py
│   ├── run_eval.py
│   └── review_notes.md
├── src/jev_gate/
│   ├── audit/                 # Persistencia SQLite y métricas
│   ├── client/                # Abstracción JEV, cliente y preguntas
│   ├── extractor/             # Extracción determinista
│   ├── gateway/               # FastAPI e interceptor de tool calls
│   ├── models/                # Modelos Pydantic del contrato
│   └── policy/                # Motor de política
├── tests/                     # Pruebas unitarias
├── implementation_plan.md
└── pyproject.toml
```

## Contrato y decisiones

### `Action`

Cada tool call se normaliza a una acción v2.0. Los campos requeridos son `schema_version`, `action_id` (UUID), `action_class`, `tool`, `actor`, `args`, `recipients`, `payload`, `risk_level`, `dry_run` y `created_at`. `subtype` solo se incluye para `pr_action` y es obligatorio en esa clase. Los campos desconocidos se rechazan.

`risk_level` viene en la estructura de entrada por compatibilidad, pero el extractor calcula el riesgo usado por la política. `args` y `payload` son objetos JSON; el contenido para evaluación semántica se transporta en `payload`.

### `Decision`

La respuesta incluye `schema_version`, `action_id`, `status`, `verdict` cuando ya hay una decisión, `reasons`, `features`, `jev_answers`, `source`, `latency_ms`, `cost_usd` y `decided_at`. `status` puede ser `decided`, `pending` o `expired`. `verdict` es `allow`, `ask` o `deny` y se omite mientras el estado no sea `decided`.

Cada entrada de `jev_answers` conserva `type` y un mapa `probs` de probabilidades. `source` puede ser `jev` o `mock`. Los códigos de `reasons` explican qué regla o señal determinó el resultado.

### `Approval`

La aprobación contiene `action_id`, `status` (`pending`, `approved`, `rejected`) y, cuando se resuelve, `resolved_by` y `resolved_at`. Una resolución se envía como `{"resolution":"approved|rejected","resolved_by":"..."}`.

### Semántica de la política

Las reglas duras configuradas prevalecen sobre una respuesta permisiva de JEV. Las señales de denegación producen `deny`; reglas de revisión o señales de incertidumbre producen `ask`; en ausencia de señales de riesgo se permite `allow`. La evaluación usa características deterministas junto con las probabilidades de JEV.

Cuando JEV falla, el comportamiento configurado es do-nothing: estado `pending`, sin veredicto y sin ejecución. El vencimiento lo deja `expired`, tampoco lo autoriza. `dry_run` usa el veredicto por defecto configurado (`allow`).

## Clases, umbrales y preguntas

Umbrales iniciales definidos en [docs/policy.defaults.json](docs/policy.defaults.json). [config/thresholds.v2.yaml](config/thresholds.v2.yaml) es un espejo legible v2.0, pero el runtime carga el JSON. [config/thresholds.yaml](config/thresholds.yaml) conserva la propuesta previa y enlaza al espejo v2.0. Los YAML originales de `config/questions/` se conservan como referencias históricas; las preguntas activas se cargan desde `docs/jev_questions.json`.

| Clase/acción | Regla inicial |
|---|---|
| `email_bulk` | Menos de 10 destinatarios: bajo; 10–250: medio; más de 250: alto. |
| `crm_write` | Menos de 10 registros: bajo; 10–500: medio; más de 500: alto. |
| `social_post` | Siempre requiere revisión humana. |
| `pr_action: merge` | Requiere revisión; más de 50 archivos se deniega. |
| `pr_action: push_main` | Siempre se deniega. |
| `pr_action: touch_ci` o `touch_secrets` | Requiere revisión. |
| `pr_action: add_dependency` | Se evalúa con CVE score; el umbral no está fijado aún. |
| `pr_action: delete_files` | Menos de 5: revisión; exactamente 5: revisión; más de 5: denegación. |
| `pr_action: approve` | Revisión por defecto. |

Los límites son literales: 10 destinatarios/registros pertenecen a la banda media; 250 correos y 500 registros siguen en la banda media; exactamente 5 archivos borrados requiere `ask`. Los umbrales probabilísticos para juicios de JEV también se configuran en `docs/policy.defaults.json`.

Preguntas semánticas en [docs/jev_questions.json](docs/jev_questions.json):

| Clase | Preguntas (IDs) |
|---|---|
| `email_bulk` | `action_is_irreversible`, `content_contains_pii`, `content_is_misleading`, `content_is_off_brand`, `risk_level` |
| `crm_write` | `action_is_irreversible`, `content_contains_pii`, `content_is_misleading`, `content_is_off_brand`, `risk_level` |
| `social_post` | `content_contains_pii`, `content_is_misleading`, `content_is_off_brand`, `content_is_inflammatory`, `risk_level` |
| `pr_action` | `introduces_security_vulnerability`, `contains_secret_leak`, `has_breaking_api_change`, `adds_unreviewed_dependency`, `code_quality_tier`, `review_action`, `severity_score` |

Las preguntas se agrupan según clase de acción. Los tipos disponibles son `boolean`, `choice` y `score`. JEV no cuenta destinatarios, registros o archivos, ni realiza aritmética o comparación de fechas; esas operaciones corresponden al extractor y la política.

## API

La especificación completa está en [contracts/openapi.yaml](contracts/openapi.yaml). El servicio FastAPI actual expone:

| Método | Ruta | Función |
|---|---|---|
| `POST` | `/gate` | Valida y evalúa una `Action`; persiste el resultado. |
| `GET` | `/decisions?limit=N` | Lista decisiones recientes; `limit` acepta 1–1000, default 100. |
| `GET` | `/approvals?status=pending` | Lista aprobaciones por estado. |
| `POST` | `/gate/{action_id}/approve` | Resuelve la aprobación como `approved` o `rejected`. |
| `GET` | `/metrics` | Devuelve latencia, costo, tasas y conteos por clase en JSON. |
| `GET` | `/health` | Informa estado del proceso, versión y si JEV tiene transporte configurado. |

Respuestas relevantes: `422` para entradas inválidas, `404` para acción/aprobación inexistente, `409` si la aprobación ya está resuelta, y `503` si no se puede persistir en auditoría. Un fallo de JEV se representa como `200` con estado `pending`, no como error HTTP. `/health` no comprueba conectividad remota con JEV. El gateway actual no aplica autenticación y no expone rutas antiguas como `/queue`, `/audit/log` o `/audit/metrics`.

## Instalación y ejecución

Requiere Python 3.11 o posterior.

```bash
python -m pip install -e ".[dev]"
python -m uvicorn jev_gate.gateway.main:app --app-dir src --reload --port 8000
```

El gateway queda en `http://localhost:8000`. Comprueba `GET /health`. Sin un transporte de JEV inyectado, `jev_configured` es `false`; las solicitudes al gate quedarán `pending` cuando el cliente no pueda evaluar.

Ejemplo mínimo de `POST /gate`:

```bash
curl -X POST http://localhost:8000/gate \
  -H "Content-Type: application/json" \
  -d @contracts/examples/action_email_bulk.json
```

No se requiere una credencial para la implementación actual del gateway. La variable de API key en `.env.example` es un marcador para una futura integración basada en la documentación oficial; no agregues credenciales reales al repositorio.

## Configuración

La política canónica de runtime vive en [docs/policy.defaults.json](docs/policy.defaults.json). Incluye umbrales numéricos, umbrales probabilísticos, TTL, timeout, reintentos, backoff y precio de entrada usado para estimar costo. [config/thresholds.v2.yaml](config/thresholds.v2.yaml) vuelve a incluir estas reglas en YAML legible; es un espejo documental, no una fuente cargada por el gateway. Las preguntas canónicas viven en [docs/jev_questions.json](docs/jev_questions.json); los YAML previos se preservan en `config/questions/` y no se cargan en runtime.

Valores JEV por defecto: timeout 500 ms, dos reintentos, backoff exponencial de 100 ms inicial, TTL de `pending` 300 s y precio de entrada de 0.042 USD por millón de tokens. El TTL de aprobación es 3600 s. Todos son configurables; el costo es estimado y no se factura desde el gateway.

Variables de entorno disponibles:

| Variable | Default | Uso |
|---|---|---|
| `PORT` | `8000` | Puerto HTTP de FastAPI. |
| `JEV_GATE_DB` | `jev_gate.sqlite3` | Archivo SQLite de auditoría. |
| `TYPESAFE_API_KEY` | marcador en `.env.example` | Reservada para el adaptador oficial de JEV; todavía no conecta un transporte. |

## Dataset y evaluación

El dataset se genera con:

```bash
python eval/generate_dataset.py
python eval/validate_dataset.py
python eval/run_eval.py --json-out eval/report.json
```

Los casos son sintéticos, JSONL y se validan contra el contrato. Revisa [eval/review_notes.md](eval/review_notes.md) antes de cambiar etiquetas o calibrar umbrales. El comando de evaluación reporta métricas de clasificación y guarda salida JSON.

El reporte actual se basa en reglas y `MockJev`; su concordancia con las etiquetas del dataset no mide el desempeño del JEV real. Las metas del plan —falsos positivos ≤10%, costo medio ≤$0.001, recall de peligrosas ≥85% y latencia p95 <800 ms— son objetivos por medir, no resultados garantizados por este README.

## Infraestructura objetivo

El plan contempla ocho VMs en una LAN con acceso a internet. Es una topología objetivo, no un despliegue contenido en este repositorio:

| VM | Rol planeado | Sistema sugerido |
|---|---|---|
| VM1 | Gateway y política | Ubuntu |
| VM2 | Dashboard y observabilidad | Ubuntu |
| VM3 | CRM/mail/social simulados y relay de webhook | Ubuntu |
| VM4 | Agentes simulados | Ubuntu o Rocky Linux |
| VM5 | Base de auditoría para producción | Rocky Linux |
| VM6–VM8 | Reserva para escala, CI y desarrollo | — |

La persistencia implementada actualmente es SQLite. No hay scripts de aprovisionamiento, dashboard ni mundo simulado desplegable en este repo. El plan difiere la demo y el playbook a una fase posterior.

## Desarrollo y validación

```bash
python docs/validate_contract.py
python eval/validate_dataset.py
python -m pytest
```

El validador de contrato requiere `jsonschema`; las pruebas requieren el extra `dev`. Para revisión estática se puede usar:

```bash
ruff check src/ tests/
mypy src/
```

El transporte de JEV puede sustituirse por un objeto que implemente la interfaz `DecisionModel`. Los tests usan dobles locales y no requieren API key.

## Métricas

`GET /metrics` calcula sobre las decisiones persistidas:

- Latencia p50 y p95 en milisegundos (se excluyen latencias cero).
- Costo total y promedio estimado por decisión.
- Conteos de `allow`, `ask`, `deny`, `pending` y `expired`.
- `block_rate` como toda decisión distinta de `allow`; `deny_rate` cuenta solo `deny`.
- Conteos de `allow`, `ask` y `deny` por clase de acción.

El endpoint no calcula tasa de falsos positivos porque necesita etiquetas de referencia. Tampoco expone actualmente métricas Prometheus.

## Licencia

MIT
