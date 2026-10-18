import { useEffect, useMemo, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
  RadialBar, RadialBarChart, PolarAngleAxis,
} from "recharts";
import { ShieldCheck, ShieldAlert, ShieldX, Hourglass, Github, ArrowRight } from "lucide-react";
import { TechSection } from "./components/TechSection";
import { evaluate, KIND_META, type ActionKind, type Verdict } from "./lib/policy";

const SNAPSHOT = { actions: 20, sequential: 10, concurrent: 10, cost: 0.000691446, jevP95: 389.4, gatewayP95: 416.9 };

const VERDICT_UI: Record<Verdict, { label: string; color: string; Icon: typeof ShieldCheck }> = {
  allow: { label: "ALLOW", color: "var(--allow)", Icon: ShieldCheck },
  ask: { label: "ASK", color: "var(--ask)", Icon: ShieldAlert },
  deny: { label: "DENY", color: "var(--deny)", Icon: ShieldX },
  pending: { label: "PENDING", color: "var(--pending)", Icon: Hourglass },
};

const TIER_SCORE = { low: 20, medium: 50, high: 80, critical: 100 };

const tooltipStyle = {
  background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8,
  fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--foreground)",
};

// Threshold bands derived from the policy (real config, not invented data).
const BANDS = [
  { name: "Correo", allow: 9, ask: 241, deny: 750 },
  { name: "CRM", allow: 9, ask: 491, deny: 500 },
];

export default function App() {
  const t = useTokens();
  const [kind, setKind] = useState<ActionKind>("email_bulk");
  const [count, setCount] = useState(42);
  const [dryRun, setDryRun] = useState(false);
  const [jevAvailable, setJevAvailable] = useState(true);
  const meta = KIND_META[kind];
  const clamped = Math.min(count, meta.max);
  const result = useMemo(() => evaluate({ kind, count: clamped, dryRun, jevAvailable }), [kind, clamped, dryRun, jevAvailable]);
  const v = VERDICT_UI[result.verdict];

  const sweep = useMemo(() => {
    const steps = 24;
    return Array.from({ length: steps }, (_, i) => {
      const c = Math.max(1, Math.round(((i + 1) / steps) * meta.max));
      const r = evaluate({ kind, count: c, dryRun, jevAvailable });
      return { c, verdict: r.verdict, h: TIER_SCORE[r.tier] };
    });
  }, [kind, meta.max, dryRun, jevAvailable]);

  const latency = [
    { name: "Jev p95", ms: SNAPSHOT.jevP95 },
    { name: "Overhead gateway", ms: +(SNAPSHOT.gatewayP95 - SNAPSHOT.jevP95).toFixed(1) },
    { name: "Gateway p95", ms: SNAPSHOT.gatewayP95 },
  ];

  return (
    <div className="min-h-screen">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-6">
        <div className="flex items-center gap-2 font-mono text-sm">
          <span className="inline-block h-2.5 w-2.5 rounded-full bg-primary glow" />
          jev<span className="text-muted-foreground">/</span>safety-gate
        </div>
        <a href="https://github.com/nightyvsc/MyNameIsJev" target="_blank" rel="noreferrer"
          className="flex items-center gap-2 rounded-md border px-3 py-1.5 font-mono text-xs text-muted-foreground transition-colors hover:text-foreground">
          <Github className="h-3.5 w-3.5" /> código fuente
        </a>
      </header>

      <main className="mx-auto max-w-6xl px-6 pb-20">
        <section className="py-10">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-primary">Demo pública · datos sintéticos</p>
          <h1 className="mt-4 max-w-3xl text-4xl font-bold leading-[1.05] tracking-tight md:text-6xl">
            Ningún agente ejecuta una acción sin pasar por el gate.
          </h1>
          <p className="mt-5 max-w-2xl text-lg text-muted-foreground">
            Cada tool call se intercepta, se evalúa con Jev y recibe <V c="allow" />, <V c="ask" /> o <V c="deny" />.
            Mueve los controles y mira la política decidir en tiempo real.
          </p>
        </section>

        {/* Simulator */}
        <section className="grid gap-4 lg:grid-cols-5">
          <div className="panel p-6 lg:col-span-3">
            <h2 className="font-mono text-xs uppercase tracking-widest text-muted-foreground">01 · Acción del agente</h2>
            <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
              {(Object.keys(KIND_META) as ActionKind[]).map((k) => (
                <button key={k} onClick={() => setKind(k)}
                  className={`rounded-md border px-3 py-2 text-left text-sm transition-all ${k === kind ? "border-primary bg-primary/10 text-foreground" : "text-muted-foreground hover:border-muted-foreground"}`}>
                  {KIND_META[k].label}
                </button>
              ))}
            </div>

            <div className="mt-6">
              <div className="flex items-baseline justify-between">
                <label htmlFor="count" className="text-sm text-muted-foreground">Volumen</label>
                <span className="font-mono text-2xl font-semibold">{clamped} <span className="text-sm text-muted-foreground">{meta.unit}</span></span>
              </div>
              <input id="count" type="range" min={1} max={meta.max} value={clamped}
                onChange={(e) => setCount(Number(e.target.value))}
                className="mt-3 w-full accent-[var(--primary)]" />
            </div>

            <div className="mt-6 flex flex-wrap gap-3">
              <Toggle on={dryRun} set={setDryRun} label="Dry-run" />
              <Toggle on={jevAvailable} set={setJevAvailable} label="Jev disponible" />
            </div>

            <div className="mt-6 h-32">
              <p className="mb-1 font-mono text-[11px] text-muted-foreground">Veredicto a lo largo del rango de volumen</p>
              <ResponsiveContainer>
                <BarChart data={sweep} barCategoryGap={2}>
                  <XAxis dataKey="c" hide />
                  <Tooltip cursor={{ fill: t["muted"] }} contentStyle={tooltipStyle}
                    formatter={(_v, _n, p) => [VERDICT_UI[(p.payload as { verdict: Verdict }).verdict].label, `${(p.payload as { c: number }).c} ${meta.unit}`]} labelFormatter={() => ""} />
                  <Bar dataKey="h" radius={[3, 3, 0, 0]}>
                    {sweep.map((s, i) => (
                      <Cell key={i} fill={t[s.verdict]} fillOpacity={s.c <= clamped ? 1 : 0.3} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="panel relative overflow-hidden p-6 lg:col-span-2" style={{ boxShadow: `0 0 0 1px ${v.color}, 0 20px 60px -20px ${v.color}` }}>
            <h2 className="font-mono text-xs uppercase tracking-widest text-muted-foreground">02 · Decisión</h2>
            <div className="mt-2 h-44">
              <ResponsiveContainer>
                <RadialBarChart innerRadius="72%" outerRadius="100%" startAngle={210} endAngle={-30} data={[{ v: TIER_SCORE[result.tier] }]}>
                  <PolarAngleAxis type="number" domain={[0, 100]} tick={false} />
                  <RadialBar dataKey="v" cornerRadius={8} fill={t[result.verdict]} background={{ fill: t["muted"] }} isAnimationActive />
                </RadialBarChart>
              </ResponsiveContainer>
            </div>
            <div className="-mt-28 flex flex-col items-center">
              <v.Icon className="h-7 w-7" style={{ color: v.color }} />
              <p className="mt-1 font-mono text-3xl font-bold tracking-wider" style={{ color: v.color }}>{v.label}</p>
              <p className="font-mono text-xs text-muted-foreground">riesgo {result.tier}</p>
            </div>
            <p className="mt-10 text-sm">{result.reason}</p>
            <dl className="mt-4 grid grid-cols-2 gap-3 font-mono text-xs">
              <div className="rounded-md bg-muted p-2"><dt className="text-muted-foreground">clase</dt><dd>{result.irreversible ? "irreversible" : "reversible"}</dd></div>
              <div className="rounded-md bg-muted p-2"><dt className="text-muted-foreground">efecto externo</dt><dd>ninguno (demo)</dd></div>
            </dl>
          </div>
        </section>

        {/* Metrics */}
        <section className="mt-16">
          <h2 className="font-mono text-xs uppercase tracking-widest text-muted-foreground">03 · Prueba de integración observada</h2>
          <div className="mt-4 grid grid-cols-2 gap-4 md:grid-cols-4">
            <Stat k="Acciones evaluadas" v={String(SNAPSHOT.actions)} />
            <Stat k="Coste total Jev" v={`$${SNAPSHOT.cost.toFixed(5)}`} />
            <Stat k="Coste / decisión" v={`$${(SNAPSHOT.cost / SNAPSHOT.actions).toFixed(6)}`} />
            <Stat k="Gateway p95" v={`${SNAPSHOT.gatewayP95} ms`} />
          </div>
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            <div className="panel p-6">
              <p className="text-sm font-medium">Latencia p95 (tanda secuencial)</p>
              <div className="mt-4 h-52">
                <ResponsiveContainer>
                  <BarChart data={latency} layout="vertical" margin={{ left: 20 }}>
                    <CartesianGrid horizontal={false} stroke={t["grid"]} />
                    <XAxis type="number" unit=" ms" tick={{ fill: t["muted-foreground"], fontSize: 11, fontFamily: "JetBrains Mono" }} stroke={t["border"]} />
                    <YAxis type="category" dataKey="name" width={120} tick={{ fill: t["muted-foreground"], fontSize: 12 }} stroke={t["border"]} />
                    <Tooltip cursor={{ fill: t["muted"] }} contentStyle={tooltipStyle} />
                    <Bar dataKey="ms" radius={[0, 4, 4, 0]}>
                      {latency.map((_, i) => <Cell key={i} fill={i === 1 ? t["ask"] : t["primary"]} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
            <div className="panel p-6">
              <p className="text-sm font-medium">Bandas de política por volumen</p>
              <div className="mt-4 h-52">
                <ResponsiveContainer>
                  <BarChart data={BANDS} layout="vertical" margin={{ left: 0 }}>
                    <XAxis type="number" hide domain={[0, 1000]} />
                    <YAxis type="category" dataKey="name" width={60} tick={{ fill: t["muted-foreground"], fontSize: 12 }} stroke={t["border"]} />
                    <Tooltip cursor={{ fill: t["muted"] }} contentStyle={tooltipStyle} />
                    <Bar dataKey="allow" stackId="a" fill={t["allow"]} />
                    <Bar dataKey="ask" stackId="a" fill={t["ask"]} />
                    <Bar dataKey="deny" stackId="a" fill={t["deny"]} radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <p className="font-mono text-[11px] text-muted-foreground">Correo: &lt;10 allow · 10–250 ask · &gt;250 deny — CRM: &lt;10 · 10–500 · &gt;500</p>
            </div>
          </div>
          <p className="mt-3 text-xs text-muted-foreground">
            20 solicitudes dry-run (10 secuenciales, 10 con concurrencia máx. 5), todas allow. No demuestran precisión ante acciones reales.
          </p>
        </section>

        {/* Flow */}
        <section className="mt-16">
          <h2 className="font-mono text-xs uppercase tracking-widest text-muted-foreground">04 · Cómo funciona</h2>
          <div className="mt-4 grid gap-3 md:grid-cols-4">
            {[
              ["Agente", "Emite un Action v2: correo, CRM, post, merge…"],
              ["Extractor", "Señales deterministas: volumen, PII, dry-run, diff."],
              ["Jev", "Lote de preguntas tipadas en una sola llamada."],
              ["Política", "Umbrales → allow / ask / deny + auditoría."],
            ].map(([t, d], i, arr) => (
              <div key={t} className="panel relative p-5">
                <p className="font-mono text-xs text-primary">0{i + 1}</p>
                <p className="mt-1 font-semibold">{t}</p>
                <p className="mt-1 text-sm text-muted-foreground">{d}</p>
                {i < arr.length - 1 && <ArrowRight className="absolute -right-3 top-1/2 hidden h-5 w-5 -translate-y-1/2 text-muted-foreground md:block" />}
              </div>
            ))}
          </div>
          <p className="mt-4 text-sm text-muted-foreground">
            Si Jev no responde, la acción queda <V c="pending" /> hasta expirar: nunca se permite ni se bloquea en silencio.
          </p>
        </section>
        <TechSection t={t} input={{ kind, count: clamped, dryRun, jevAvailable }} result={result} tooltipStyle={tooltipStyle} />
      </main>

      <footer className="border-t py-6 text-center font-mono text-xs text-muted-foreground">
        Demo de solo lectura · sin credenciales · no introduzcas datos personales
      </footer>
    </div>
  );
}

function V({ c }: { c: Verdict }) {
  return <span className="font-mono font-semibold" style={{ color: VERDICT_UI[c].color }}>{c}</span>;
}

function Stat({ k, v }: { k: string; v: string }) {
  return (
    <div className="panel p-5">
      <p className="text-xs text-muted-foreground">{k}</p>
      <p className="mt-2 font-mono text-2xl font-semibold">{v}</p>
    </div>
  );
}

function Toggle({ on, set, label }: { on: boolean; set: (b: boolean) => void; label: string }) {
  return (
    <button role="switch" aria-checked={on} onClick={() => set(!on)}
      className={`flex items-center gap-2 rounded-full border px-3 py-1.5 font-mono text-xs transition-colors ${on ? "border-primary text-foreground" : "text-muted-foreground"}`}>
      <span className={`h-2 w-2 rounded-full ${on ? "bg-primary" : "bg-muted-foreground"}`} />
      {label}
    </button>
  );
}

const TOKEN_NAMES = ["allow", "ask", "deny", "pending", "primary", "muted", "muted-foreground", "border", "grid"] as const;

// SVG fill attributes can't resolve CSS variables, so read the design tokens once mounted.
function useTokens() {
  const [tokens, setTokens] = useState<Record<string, string>>(() =>
    Object.fromEntries(TOKEN_NAMES.map((n) => [n, "currentColor"])),
  );
  useEffect(() => {
    const cs = getComputedStyle(document.documentElement);
    setTokens(Object.fromEntries(TOKEN_NAMES.map((n) => [n, cs.getPropertyValue(`--${n}`).trim()])));
  }, []);
  return tokens;
}
