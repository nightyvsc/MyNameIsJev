// Deterministic policy mirror of the HashBit/Jev Safety Gate thresholds.
// Illustrative only: no Jev call happens in the public demo.

export type Verdict = "allow" | "ask" | "deny" | "pending";

export type ActionKind =
  | "email_bulk"
  | "crm_write"
  | "social_post"
  | "pr_merge"
  | "push_main"
  | "touches_ci"
  | "delete_files";

export interface SimInput {
  kind: ActionKind;
  count: number; // recipients, records or files depending on kind
  dryRun: boolean;
  jevAvailable: boolean;
}

export interface SimResult {
  verdict: Verdict;
  reason: string;
  tier: "low" | "medium" | "high" | "critical";
  irreversible: boolean;
}

export const KIND_META: Record<ActionKind, { label: string; unit: string; irreversible: boolean; max: number }> = {
  email_bulk: { label: "Correo saliente", unit: "destinatarios", irreversible: true, max: 1000 },
  crm_write: { label: "Escritura en CRM", unit: "registros", irreversible: false, max: 1000 },
  social_post: { label: "Post en red social", unit: "publicaciones", irreversible: false, max: 5 },
  pr_merge: { label: "Merge a main", unit: "archivos", irreversible: true, max: 120 },
  push_main: { label: "Push directo a main", unit: "commits", irreversible: true, max: 10 },
  touches_ci: { label: "Toca CI o secretos", unit: "archivos", irreversible: true, max: 20 },
  delete_files: { label: "Borra archivos", unit: "archivos", irreversible: true, max: 20 },
};

export function evaluate({ kind, count, dryRun, jevAvailable }: SimInput): SimResult {
  const irreversible = KIND_META[kind].irreversible;

  // Hard rules run before Jev.
  if (kind === "push_main") return { verdict: "deny", reason: "Los pushes directos a main siempre se deniegan.", tier: "critical", irreversible };
  if (kind === "pr_merge" && count > 50) return { verdict: "deny", reason: "Merge con más de 50 archivos: se deniega.", tier: "critical", irreversible };
  if (kind === "delete_files" && count > 5) return { verdict: "deny", reason: "Borrar más de 5 archivos se deniega.", tier: "critical", irreversible };

  if (dryRun) return { verdict: "allow", reason: "Las acciones dry-run no producen efectos y se permiten.", tier: "low", irreversible };

  if (!jevAvailable) return { verdict: "pending", reason: "Sin respuesta de Jev: la acción queda pendiente (do-nothing) hasta el TTL.", tier: "medium", irreversible };

  switch (kind) {
    case "email_bulk":
      if (count > 250) return { verdict: "deny", reason: "Más de 250 destinatarios en un envío irreversible.", tier: "high", irreversible };
      if (count >= 10) return { verdict: "ask", reason: "Entre 10 y 250 destinatarios: requiere aprobación humana.", tier: "medium", irreversible };
      return { verdict: "allow", reason: "Menos de 10 destinatarios: riesgo bajo.", tier: "low", irreversible };
    case "crm_write":
      if (count > 500) return { verdict: "deny", reason: "Más de 500 registros en una sola escritura.", tier: "high", irreversible };
      if (count >= 10) return { verdict: "ask", reason: "Entre 10 y 500 registros: requiere aprobación humana.", tier: "medium", irreversible };
      return { verdict: "allow", reason: "Menos de 10 registros: riesgo bajo.", tier: "low", irreversible };
    case "social_post":
      return { verdict: "ask", reason: "Las publicaciones sociales siempre pasan por revisión.", tier: "medium", irreversible };
    case "pr_merge":
      return { verdict: "ask", reason: "Todo merge a main requiere revisión.", tier: "medium", irreversible };
    case "touches_ci":
      return { verdict: "ask", reason: "Cambios en CI o secretos siempre requieren aprobación.", tier: "critical", irreversible };
    case "delete_files":
      return { verdict: "ask", reason: "Borrar hasta 5 archivos requiere aprobación.", tier: "medium", irreversible };
  }
}
