# Contrato del gate (v2.0)

Fuente de verdad para `gate/`, `sim/` y `eval/`. Se sube a v2.0 porque cambia de forma incompatible el modelo de fallo, los umbrales y los campos del contrato v1.0. Los datos de prueba son sintéticos y usan `@ejemplo.test`.

## Flujo

```text
Agente/webhook -> Action -> extractor determinista -> JEV (preguntas tipadas en un lote)
  -> motor de política con umbrales configurados -> allow | ask | deny
  -> auditoría append-only -> cola humana si ask
```

El código cuenta, compara y detecta patrones (PII, diff, destinatarios, registros, flags). JEV evalúa juicios semánticos. El motor aplica umbrales deterministas a sus respuestas; no hay árbitro de modelo local ni explicación en el camino crítico. La integración con GitHub puede convertir el veredicto en review/comentario, según la acción.

## Action

`docs/schemas/action.schema.json` define `schema_version: "2.0"`, `action_id` (UUID), `action_class`, `tool`, `args`, `actor`, `recipients`, `payload`, `risk_level`, `dry_run` y `created_at`. `subtype` es obligatorio solo para `pr_action`: `merge`, `approve`, `push_main`, `touch_ci`, `touch_secrets`, `add_dependency`, `delete_files`. `payload` es objeto con el contenido a evaluar; `args` contiene parámetros de ejecución. `risk_level` es calculado por el extractor (`low|medium|high|critical`), no se confía en una etiqueta declarada por el agente. `recipients` es lista de destinatarios o identificadores afectados; el extractor cuenta los elementos relevantes.

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

`Decision` incluye `action_id`, veredicto, razones, features, respuestas JEV, fuente, latencia/costo y timestamp. Si JEV falla o expira el timeout, se aplica **do-nothing**: la acción queda `pending` durante el TTL configurado y no se ejecuta ni se bloquea. Puede reintentarse la evaluación mientras siga vigente. Al expirar el TTL, permanece sin ejecutar y se registra como `expired`; nunca se convierte silenciosamente en allow/deny. `pending` y `expired` son estados de procesamiento, no veredictos finales.

El mock de JEV se permite solo en tests locales. No simula una integración real en despliegue. El cliente real permanece detrás de una interfaz y no se inventa el formato HTTP de JEV; se fija cuando se disponga de documentación oficial/ejemplo de request y response.

## Approval

Una decisión `ask` crea una entrada `Approval` con `status: pending`. Una resolución humana cambia el estado a `approved` o `rejected` y registra `resolved_by`, `resolved_at`. El TTL de aprobación se configura aparte del TTL de espera de JEV. No hay explicación por modelo local en este contrato.

## Esquemas y ejemplos

JSON Schema Draft 2020-12: `docs/schemas/action.schema.json`, `decision.schema.json`, `approval.schema.json`. Configuración: `docs/policy.defaults.json` y `docs/jev_questions.json`. Ejemplos positivos y negativos en `docs/examples/`. Validación: `python docs/validate_contract.py` (requiere `jsonschema`).

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

## Evolución

Los cambios se acuerdan entre Persona A y B y se versionan. Cambios incompatibles incrementan major; cambios compatibles incrementan minor. El validador de contrato debe pasar antes de integrar.
