# Contrato del gate (v2.0)

Contrato compartido v2.0 para `gate/`, los simuladores, agentes y adaptadores. Los
esquemas fuente están en `contracts/schemas/`; las copias publicadas en
`docs/schemas/` deben mantenerse idénticas. `python docs/validate_contract.py` valida
ejemplos y comprueba esa igualdad. Los ejemplos de prueba usan datos ficticios; los
adaptadores productivos deben minimizar y clasificar cualquier dato enviado a JEV.

## Flujo

```text
Agente/webhook -> Action -> extractor determinista -> JEV (preguntas tipadas en un lote)
  -> motor de política con umbrales configurados -> allow | ask | deny
  -> auditoría append-only -> cola humana si ask
```

El código cuenta, compara y detecta patrones (PII, diff, destinatarios, registros,
flags). JEV evalúa juicios semánticos. El motor aplica umbrales deterministas a sus
respuestas; no hay árbitro de modelo local ni explicación en el camino crítico. El
adaptador GitHub genera una Action v2 y remite su decisión; las escrituras a GitHub
siguen desactivadas por defecto. El contrato no autoriza ni ejecuta un merge.

## Action

`contracts/schemas/action.schema.json` define `schema_version: "2.0"`, `action_id`
(UUID), `action_class`, `tool`, `args`, `actor`, `recipients`, `payload`, `risk_level`,
`dry_run` y `created_at`. `subtype` es obligatorio solo para `pr_action`: `merge`,
`approve`, `push_main`, `touch_ci`, `touch_secrets`, `add_dependency`, `delete_files`.
`payload` contiene el contexto necesario para la evaluación; `args` contiene los
argumentos/metadatos estructurados de la tool call. `risk_level` es una etiqueta de
entrada por compatibilidad: no se confía en ella; el extractor calcula el riesgo
(`low|medium|high|critical`). `recipients` es una lista de destinatarios o
identificadores afectados; el extractor cuenta los elementos relevantes.

Para GitHub, el relay mapea cada PR a `action_class: pr_action`, `subtype: merge`,
`tool: github.evaluate_pull_request`, `actor` como texto, conteos y rutas bajo `args`,
metadatos/diff truncado bajo `payload`, y `dry_run: false` para aplicar la política
normal. `GITHUB_ENABLE_WRITES` es un control independiente: desactivado, el relay no
envía reviews ni comentarios, incluso si el gateway decide `allow`. La Action se valida
con JSON Schema y Pydantic en las pruebas locales; esto no prueba la entrega real de
webhooks o el recorrido end-to-end.

Clases: `email_bulk`, `crm_write`, `social_post`, `pr_action`.

## JEV y política

Las preguntas se definen en `docs/jev_questions.json`; se envían juntas en una solicitud por acción, de acuerdo con la clase. Tipos: `boolean`, `choice`, `score`. El resultado conserva probabilidades por pregunta. JEV no cuenta, hace aritmética ni compara fechas.

El extractor asigna clase y riesgo base y produce `features`. La política combina esas features, el subtipo y las respuestas/probabilidades de JEV para determinar `allow`, `ask` o `deny`. Reglas duras de este contrato (por ejemplo, push directo a main) prevalecen sobre una respuesta permisiva de JEV. Umbrales numéricos y N configurables están en `docs/policy.defaults.json`; se pueden editar sin redeployar.

| Acción | Low | Medium | High / regla inicial | Clase |
|---|---:|---:|---|---|
| Correo saliente | <10 destinatarios | 10–250 | >250 | Irreversible |
| Escritura CRM | <10 registros | 10–500 | >500 | Reversible con costo |
| Post social | — | — | Siempre `ask` | Reversible/visible |
| Merge a main | — | Siempre revisión (`ask`) | >50 archivos: `deny` | Irreversible |
| Push directo a main | — | — | Siempre `deny` | Irreversible |
| Cambia CI o secretos | — | Siempre `ask` | Siempre `ask` | Crítica |
| Agrega dependencia | — | Evaluar con CVE score | Política por CVE | Reversible |
| Borra archivos | — | <5 archivos: `ask` | >5 archivos: `deny` | Irreversible |

Los límites se interpretan literalmente como indica cada fila; N=10 pertenece a medium, email N=250 pertenece a medium, CRM N=500 pertenece a medium, borrar exactamente 5 archivos queda sujeto a revisión (`ask`). El umbral CVE se configura y no se inventa aquí.

## Decisión y fallo de JEV

`Decision` incluye `action_id`, veredicto, razones, features, respuestas JEV, modelo y tokens informados por el proveedor, fuente, latencia/costo y timestamp. El costo se calcula con los tokens de entrada reportados y la tarifa configurada. Si JEV falla o expira el timeout, se aplica **do-nothing**: la acción queda `pending` durante el TTL configurado y no se ejecuta ni se bloquea. Puede reintentarse la evaluación mientras siga vigente. Al expirar el TTL, permanece sin ejecutar y se registra como `expired`; nunca se convierte silenciosamente en allow/deny. `pending` y `expired` son estados de procesamiento, no veredictos finales.

El transporte de producción usa `POST https://api.typesafe.ai/v1/systemone` con autenticación Bearer y preguntas tipadas `noul`, `choice` y `score`. La clave `TYPESAFE_API_KEY` solo debe estar en el `.env` restringido de VM1; es distinta de `GATE_TOKEN`, que autentica las llamadas entrantes al gateway. El cliente traduce las respuestas del proveedor al mapa de probabilidades que consume la política. El mock se permite solo en tests locales y no sustituye las pruebas reales de integración.

Las acciones enviadas al proveedor incluyen contenido/argumentos de la acción y características derivadas. Hasta acordar minimización de datos y tratamiento de PII, usar únicamente datos sintéticos; no enviar payloads reales o secretos.

## Approval

Una decisión `ask` crea una entrada `Approval` con `status: pending`. Una resolución humana cambia el estado a `approved` o `rejected` y registra `resolved_by`, `resolved_at`. El TTL de aprobación se configura aparte del TTL de espera de JEV. No hay explicación por modelo local en este contrato.

## Esquemas y ejemplos

JSON Schema Draft 2020-12: fuente en `contracts/schemas/`; copias para documentación y
OpenAPI en `docs/schemas/`. Configuración: `docs/policy.defaults.json` y
`docs/jev_questions.json`. Ejemplos positivos y negativos en `docs/examples/`.
Validación: `python docs/validate_contract.py` (requiere `jsonschema`).

## Endpoints

| Método/ruta | Entrada | Respuesta |
|---|---|---|
| `POST /gate` | `Action` | `Decision`; si JEV no responde, estado `pending` conforme a do-nothing |
| `GET /decisions?limit=N` | — | decisiones recientes, incluidos estados de procesamiento |
| `GET /approvals?status=pending` | — | cola humana pendiente |
| `POST /gate/{action_id}/approve` | `{"resolution":"approved|rejected","resolved_by":"..."}` | `Approval` actualizado |
| `GET /health` | — | salud del gateway |

`422` para cuerpo inválido, `404` si no existe el identificador, `503` si el servicio no puede aceptar/guardar la acción. Un fallo de JEV no es error HTTP ni autoriza ejecución; responde estado pendiente.

## Registro de auditoría

Cada acción y resultado se registra de forma append-only con veredicto/estado, razones, probabilidades, latencia JEV, costo estimado y timestamp. SQLite en desarrollo; Postgres en producción. Las métricas incluyen p50/p95, costo acumulado y tasa de bloqueo.

## MCP y conectores

MCP no es requisito para integrar correo, CRM, redes sociales o GitHub. Un conector puede
usar directamente una API/SDK y llamar al gateway antes del efecto. Si se expone como
herramienta MCP, el servidor/cliente MCP debe conservar el mismo orden: normalizar la
tool call a `Action`, obtener una decisión válida y ejecutar el efecto solo tras una
autorización explícita. MCP por sí mismo no implementa autorización, aprobación ni
políticas del gate.

## Evolución

Los cambios se acuerdan entre Persona A y B y se versionan. Cambios incompatibles incrementan major; cambios compatibles incrementan minor. El validador de contrato debe pasar antes de integrar.
