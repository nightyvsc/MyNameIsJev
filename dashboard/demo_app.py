from __future__ import annotations

import streamlit as st


SCENARIOS = {
    "Dry-run de bajo riesgo": {
        "action": {
            "schema_version": "2.0",
            "action_id": "98d9e6e8-8979-4f0e-8a20-0d37f35d6e01",
            "action_class": "email_bulk",
            "tool": "mailer.send_campaign",
            "actor": "demo-agent",
            "args": {"campaign_id": "demo-campaign-01"},
            "recipients": [f"demo-recipient-{number}" for number in range(1, 6)],
            "payload": {"subject": "Mensaje de ejemplo"},
            "risk_level": "low",
            "dry_run": True,
            "created_at": "2026-01-01T00:00:00Z",
        },
        "status": "decided",
        "verdict": "allow",
        "reason": "La política demo permite las acciones dry-run.",
        "basis": "Regla determinista configurada; Jev no se consulta en esta demo.",
    },
    "Publicación social": {
        "action": {
            "schema_version": "2.0",
            "action_id": "84e62fdb-885e-474d-9f94-1ee14e8c43c4",
            "action_class": "social_post",
            "tool": "social.publish",
            "actor": "demo-agent",
            "args": {},
            "recipients": [],
            "payload": {"text": "Publicación ficticia para revisar el flujo de aprobación."},
            "risk_level": "medium",
            "dry_run": False,
            "created_at": "2026-01-01T00:00:00Z",
        },
        "status": "decided",
        "verdict": "ask",
        "reason": "Las publicaciones sociales requieren revisión humana.",
        "basis": "Regla de política del proyecto; no se publica contenido.",
    },
    "Push directo a main": {
        "action": {
            "schema_version": "2.0",
            "action_id": "0dc23048-24d2-4ccd-9bf9-7a73a88f9eb4",
            "action_class": "pr_action",
            "subtype": "push_main",
            "tool": "github.push",
            "actor": "demo-agent",
            "args": {"branch": "main"},
            "recipients": [],
            "payload": {},
            "risk_level": "high",
            "dry_run": False,
            "created_at": "2026-01-01T00:00:00Z",
        },
        "status": "decided",
        "verdict": "deny",
        "reason": "Los pushes directos a main se deniegan.",
        "basis": "Regla dura local; no se conecta a GitHub.",
    },
    "Jev no disponible": {
        "action": {
            "schema_version": "2.0",
            "action_id": "1f4147e8-2233-46e2-bda4-9af1a1c47da2",
            "action_class": "crm_write",
            "tool": "crm.bulk_upsert",
            "actor": "demo-agent",
            "args": {"operation": "upsert"},
            "recipients": [f"demo-record-{number:03}" for number in range(1, 13)],
            "payload": {"source": "synthetic-demo"},
            "risk_level": "medium",
            "dry_run": False,
            "created_at": "2026-01-01T00:00:00Z",
        },
        "status": "pending",
        "verdict": "no verdict",
        "reason": "Sin respuesta del evaluador, la acción queda pendiente.",
        "basis": "Política do-nothing; esta demo no simula una llamada o fallo real de Jev.",
    },
}

TEST_SNAPSHOT = {
    "actions": 20,
    "sequential": 10,
    "concurrent": 10,
    "cost": 0.000691446,
    "jev_p95_ms": 389.4,
    "gateway_p95_ms": 416.9,
}


def main() -> None:
    st.set_page_config(
        page_title="Jev Safety Gate — Demo",
        page_icon="🛡️",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.title("Jev Safety Gate")
    st.caption("Demo pública · solo lectura · datos sintéticos")
    st.info(
        "Esta página es una demostración estática e interactiva de reglas del proyecto. "
        "No se conecta al gateway, no llama a Jev, no usa credenciales y no ejecuta "
        "acciones externas.",
        icon="ℹ️",
    )

    overview, explore, architecture = st.tabs(
        ["Resumen de pruebas", "Explorar una acción", "Cómo funciona"]
    )

    with overview:
        st.subheader("Integración de prueba observada")
        st.caption(
            "Instantánea de pruebas con acciones sintéticas; no es actividad en vivo "
            "ni una medición de capacidad sostenida."
        )
        columns = st.columns(4)
        columns[0].metric("Acciones evaluadas", TEST_SNAPSHOT["actions"])
        columns[1].metric("Coste estimado Jev", f"${TEST_SNAPSHOT['cost']:.6f}")
        columns[2].metric("Jev p95 secuencial", f"{TEST_SNAPSHOT['jev_p95_ms']:.1f} ms")
        columns[3].metric("Gateway p95 secuencial", f"{TEST_SNAPSHOT['gateway_p95_ms']:.1f} ms")

        st.bar_chart(
            {
                "Solicitudes": {
                    "Secuencial": TEST_SNAPSHOT["sequential"],
                    "Concurrencia máxima 5": TEST_SNAPSHOT["concurrent"],
                }
            },
            x_label="Tipo de prueba",
            y_label="Acciones",
        )
        st.caption(
            "Las 20 solicitudes de esta instantánea fueron dry-run y obtuvieron allow. "
            "Los p95 mostrados corresponden a la tanda secuencial de 10 solicitudes; "
            "la otra tanda fue de 10 con concurrencia máxima de 5. El modo dry-run tiene "
            "una regla propia; estos resultados no demuestran precisión ante acciones reales."
        )
        st.subheader("Capacidades demostradas")
        st.markdown(
            "- Contrato compartido Action/Decision v2.\n"
            "- Evaluación con Jev real en el entorno privado de pruebas.\n"
            "- Política determinista y estados `allow`, `ask`, `deny` y `pending`.\n"
            "- Auditoría SQLite y cola de aprobación en el dashboard operativo.\n"
            "- Adaptadores externos aún en simulación; no se ejecutan efectos reales."
        )

    with explore:
        st.subheader("Explorador de escenarios")
        st.caption(
            "Selecciona un ejemplo para ver cómo una regla definida en el proyecto "
            "trata la acción. Es una ilustración local, no una evaluación de Jev."
        )
        scenario_name = st.selectbox("Escenario", list(SCENARIOS))
        scenario = SCENARIOS[scenario_name]
        action_column, decision_column = st.columns(2)
        with action_column:
            st.markdown("#### Acción ficticia")
            st.json(scenario["action"])
        with decision_column:
            st.markdown("#### Resultado ilustrativo")
            st.metric("Estado", scenario["status"])
            st.metric("Veredicto", scenario["verdict"])
            st.write(scenario["reason"])
            st.caption(scenario["basis"])

    with architecture:
        st.subheader("Flujo del sistema")
        st.code(
            "Agente / conector\n"
            "       ↓ Action v2\n"
            "Gateway → señales deterministas + Jev → política\n"
            "       ↓ Decision + auditoría\n"
            "allow: el conector puede continuar\n"
            "ask: espera resolución humana\n"
            "deny / pending / expired: no ejecutar",
            language="text",
        )
        st.warning(
            "GitHub no está conectado a esta demo. No se reciben webhooks ni se publican "
            "reviews, comentarios, merges, correos o cambios en CRM/redes sociales."
        )
        st.markdown(
            "MCP es opcional: una integración puede usar una API/SDK directamente o "
            "exponer herramientas MCP, pero siempre debe consultar el gate antes de "
            "ejecutar el efecto."
        )

    st.divider()
    st.caption(
        "Proyecto de código abierto para demostración. No introduzcas datos personales, "
        "secretos ni credenciales en esta página."
    )


if __name__ == "__main__":
    main()
