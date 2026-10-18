# Jev Safety Gate — Demo web interactiva

Demo interactiva del gate de seguridad: cada acción de un agente AI se evalúa
con la política (espejo determinista de `config/thresholds.yaml` y
`docs/policy.defaults.json`) y recibe un veredicto **allow / ask / deny / pending**.

Es una app 100 % frontend (React + Vite + Tailwind v4 + Recharts), sin backend
ni credenciales: todos los datos son sintéticos.

## Desarrollo

```bash
cd dashboard/web
npm install
npm run dev        # http://localhost:5173
```

## Build estático

```bash
npm run build      # genera dist/
npm run preview    # sirve dist/ en local
```

`dist/` es estático y funciona desde cualquier ruta (base `./`), así que se
puede servir con nginx, GitHub Pages, Netlify, Vercel o cualquier hosting de
archivos.

## Docker (puerto 3000, Máquina virtual 2)

```bash
cd dashboard/web
docker build -t jev-dashboard-web .
docker run -p 3000:3000 jev-dashboard-web
```

## Notas

- Sustituye a la demo anterior de Streamlit (`dashboard/app.py`).
- La política vive en `src/lib/policy.ts`; los umbrales se copian de la
  configuración real del repo, no son datos inventados.
- Nunca muestra direcciones IP reales: la topología usa etiquetas genéricas
  ("Máquina virtual N").
