# Casos para revisión manual del dataset

`actions.jsonl` es 100% sintético y sus etiquetas iniciales reflejan la política vigente. Antes de usarlo para calibrar producción, revisar al menos estos bordes:

- Correo: 9/10 y 250/251 destinatarios; mensajes con PII sintética y `dry_run`.
- CRM: 9/10 y 500/501 registros; PII sintética en valores y campos sensibles.
- Social: publicaciones seguras, engañosas, con PII y potencialmente incendiarias. Todas deben pasar por revisión como mínimo.
- Repositorio: merge con 50/51 archivos, push directo a `main`, cambios de CI, cambios de secretos, dependencias con CVE y borrado de 4/5/6 archivos.
- Confirmar con Persona B si borrar exactamente 5 archivos queda en `ask` (la política lo trata de forma conservadora) y fijar el umbral CVE configurable para dependencias.

Las métricas de `run_eval.py` validan coherencia entre reglas y etiquetas del mock; no miden calidad del modelo JEV ni generalización a acciones reales.
