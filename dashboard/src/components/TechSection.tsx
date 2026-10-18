import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, Legend } from "recharts";
import type { CSSProperties } from "react";
import type { SimResult, SimInput } from "../lib/policy";

// Values copied from docs/policy.defaults.json and config/thresholds.yaml in the repo.
const CONFIDENCE = [
  { s: "PII · correo", ask: 0.6, deny: 0.85 },
  { s: "PII · CRM", ask: 0.65, deny: 0.9 },
  { s: "Engañoso · correo", ask: 0, deny: 0.7 },
  { s: "Off-brand · social", ask: 0.6, deny: 0 },
  { s: "Inflamatorio", ask: 0, deny: 0.75 },
  { s: "Fuga de secreto", ask: 0, deny: 0.75 },
  { s: "Riesgo crítico", ask: 0, deny: 0.8 },
];

const QUESTIONS = [
  { c: "Correo / CRM", boolean: 4, choice: 1, score: 0 },
  { c: "Social", boolean: 4, choice: 1, score: 0 },
  { c: "Repositorio", boolean: 4, choice: 2, score: 1 },
];

const RUNTIME = [
  ["endpoints", "7 (/gate, /decisions, /approvals, /metrics…)"],
  ["jev_timeout", "10 s"],
  ["jev_max_retries", "2"],
  ["retry_backoff", "1.5 s"],
  ["pending_ttl", "300 s"],
  ["fail_policy", "do_nothing"],
  ["schema_version", "2.0"],
  ["conf. irreversible", "ask ≥0.50 · deny ≥0.80"],
  ["conf. reversible", "ask ≥0.60 · deny ≥0.85"],
];

const VMS = [
  ["Máquina virtual 1", "Gateway · policy · SQLite · :8000"],
  ["Máquina virtual 2", "Dashboard · :3000"],
  ["Máquina virtual 3", "CRM/SMTP/social mock · :3001-3004"],
  ["Máquina virtual 4", "Agentes sintéticos"],
  ["Máquina virtual 5", "Backups SQLite · SFTP"],
  ["Máquina virtual 6", "Load tests · CI"],
];

export function TechSection({ t, input, result, tooltipStyle }: {
  t: Record<string, string>; input: SimInput; result: SimResult; tooltipStyle: CSSProperties;
}) {
  const tick = { fill: t["muted-foreground"], fontSize: 11 };
  const decision = {
    schema_version: "2.0",
    status: result.verdict === "pending" ? "pending" : "decided",
    verdict: result.verdict === "pending" ? null : result.verdict,
    reasons: [result.reason],
    features: { action_class: input.kind, count: input.count, dry_run: input.dryRun, irreversible: result.irreversible, risk_level: result.tier },
    source: input.jevAvailable ? "policy+jev" : "timeout",
    retries: input.jevAvailable ? 0 : 2,
    ttl_seconds: result.verdict === "pending" ? 300 : null,
  };

  return (
    <section className="mt-16">
      <h2 className="font-mono text-xs uppercase tracking-widest text-muted-foreground">05 · Detalles técnicos</h2>

      <div className="mt-4 grid gap-4 lg:grid-cols-5">
        <div className="panel p-6 lg:col-span-3">
          <p className="text-sm font-medium">Umbrales de confianza Jev por señal</p>
          <p className="font-mono text-[11px] text-muted-foreground">probabilidad del noul a partir de la cual se escala</p>
          <div className="mt-4 h-64">
            <ResponsiveContainer>
              <BarChart data={CONFIDENCE} layout="vertical" margin={{ left: 10 }}>
                <CartesianGrid horizontal={false} stroke={t["grid"]} />
                <XAxis type="number" domain={[0, 1]} tick={tick} stroke={t["border"]} />
                <YAxis type="category" dataKey="s" width={120} tick={tick} stroke={t["border"]} />
                <Tooltip cursor={{ fill: t["muted"] }} contentStyle={tooltipStyle} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="ask" name="ask_at" fill={t["ask"]} radius={[0, 3, 3, 0]} />
                <Bar dataKey="deny" name="deny_at" fill={t["deny"]} radius={[0, 3, 3, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="panel p-6 lg:col-span-2">
          <p className="text-sm font-medium">Preguntas Jev por lote</p>
          <p className="font-mono text-[11px] text-muted-foreground">1 solicitud HTTP por acción</p>
          <div className="mt-4 h-64">
            <ResponsiveContainer>
              <BarChart data={QUESTIONS}>
                <CartesianGrid vertical={false} stroke={t["grid"]} />
                <XAxis dataKey="c" tick={tick} stroke={t["border"]} />
                <YAxis allowDecimals={false} tick={tick} stroke={t["border"]} />
                <Tooltip cursor={{ fill: t["muted"] }} contentStyle={tooltipStyle} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="boolean" stackId="q" fill={t["primary"]} />
                <Bar dataKey="choice" stackId="q" fill={t["allow"]} />
                <Bar dataKey="score" stackId="q" fill={t["ask"]} radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div className="panel p-6">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium">Decision v2 (en vivo)</p>
            <span className="font-mono text-[11px] text-muted-foreground">POST /gate → 200</span>
          </div>
          <pre className="mt-3 max-h-[420px] overflow-auto rounded-md bg-muted p-4 font-mono text-xs leading-relaxed">{JSON.stringify(decision, null, 2)}</pre>
        </div>

        <div className="grid gap-4">
          <div className="panel p-6">
            <p className="text-sm font-medium">Parámetros de runtime</p>
            <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 font-mono text-xs">
              {RUNTIME.map(([k, v]) => (
                <div key={k} className="flex justify-between gap-2 border-b border-border/60 pb-1">
                  <dt className="text-muted-foreground">{k}</dt><dd className="text-right">{v}</dd>
                </div>
              ))}
            </dl>
          </div>
          <div className="panel p-6">
            <p className="text-sm font-medium">Topología · 6 máquinas virtuales · Docker Compose por máquina</p>
            <table className="mt-3 w-full font-mono text-xs">
              <tbody>
                {VMS.map(([n, r]) => (
                  <tr key={n} className="border-b border-border/60">
                    <td className="py-1 text-primary whitespace-nowrap">{n}</td><td className="py-1 text-muted-foreground text-right">{r}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </section>
  );
}
