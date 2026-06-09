import { useState, useEffect } from "react";
import {
  AreaChart, Area, LineChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, Legend,
} from "recharts";

const API = "http://localhost:5000";

// ── Design tokens ─────────────────────────────────────────────────────────────
const C = {
  bg:       "#050810",
  card:     "#0d1117",
  elevated: "#141b24",
  border:   "rgba(255,255,255,0.06)",
  teal:     "#00e5a0",
  amber:    "#f5a623",
  red:      "#ff4d6d",
  blue:     "#4a90d9",
  arch:     "#7b8ff7",
  cont:     "#00e5a0",
  brth:     "#4a90d9",
  env:      "#f5a623",
  label:    "rgba(255,255,255,0.4)",
  body:     "rgba(255,255,255,0.7)",
  muted:    "rgba(255,255,255,0.25)",
};

const COMPONENTS = [
  { key: "architecture_score", label: "ARCHITECTURE", color: C.arch },
  { key: "continuity_score",   label: "CONTINUITY",   color: C.cont },
  { key: "breathing_score",    label: "BREATHING",    color: C.brth },
  { key: "environment_score",  label: "ENVIRONMENT",  color: C.env  },
];

const MONO = "'DM Mono', monospace";
const SANS = "'Inter', sans-serif";

// ── Utilities ─────────────────────────────────────────────────────────────────
function scoreAccent(v) {
  if (v == null) return C.muted;
  if (v >= 75) return C.teal;
  if (v >= 50) return C.amber;
  return C.red;
}

function fmtTime(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  } catch { return "—"; }
}

function fmtDateShort(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("en-GB", { month: "short", day: "numeric" });
  } catch { return iso.slice(5, 10); }
}

// Mode filter (rolling window) — smooths categorical stage classifications
// so short isolated blips are absorbed into the surrounding dominant stage
function modeFilter(arr, win) {
  const half = Math.floor(win / 2);
  return arr.map((_, i) => {
    const slice = arr.slice(Math.max(0, i - half), Math.min(arr.length, i + half + 1));
    const freq = {};
    slice.forEach(v => { freq[v] = (freq[v] || 0) + 1; });
    return Object.entries(freq).sort((a, b) => b[1] - a[1])[0][0];
  });
}

// ── Data hooks ────────────────────────────────────────────────────────────────
function useLatest() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    fetch(`${API}/latest`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => { setLoading(false); });
  }, []);
  return { data, loading };
}

function useScores() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    fetch(`${API}/scores`)
      .then(r => r.json())
      .then(d => { setData(Array.isArray(d) ? d : []); setLoading(false); })
      .catch(() => { setLoading(false); });
  }, []);
  return { data, loading };
}

function useHistory() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    fetch(`${API}/history`)
      .then(r => r.json())
      .then(d => { setData(Array.isArray(d) ? d : []); setLoading(false); })
      .catch(() => { setLoading(false); });
  }, []);
  return { data, loading };
}

// ── Shared primitives ─────────────────────────────────────────────────────────
function Skeleton({ h = 20, w = "100%", radius = 6, style = {} }) {
  return (
    <div style={{
      height: h, width: w, borderRadius: radius,
      background: "rgba(255,255,255,0.05)",
      flexShrink: 0,
      ...style,
    }} />
  );
}

function Placeholder({ children }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "center",
      height: 240, padding: "0 32px", textAlign: "center",
    }}>
      <p style={{ color: C.muted, fontFamily: SANS, fontSize: 14, lineHeight: 1.6 }}>{children}</p>
    </div>
  );
}

// SVG circular progress ring with radial glow
function ScoreRing({ score, size = 200 }) {
  const r = size / 2 - 9;
  const circ = 2 * Math.PI * r;
  const filled = score != null ? Math.min(score / 100, 1) * circ : 0;
  const color = scoreAccent(score);
  const cx = size / 2;

  return (
    <div style={{ position: "relative", width: size, height: size, flexShrink: 0 }}>
      {/* Radial glow */}
      <div style={{
        position: "absolute", inset: 0, borderRadius: "50%",
        background: `radial-gradient(circle at center, ${color}40 0%, transparent 68%)`,
        filter: "blur(80px)",
        pointerEvents: "none",
      }} />
      <svg width={size} height={size} style={{ position: "absolute", inset: 0 }}>
        <circle cx={cx} cy={cx} r={r} fill="none" stroke={C.border} strokeWidth={3} />
        {score != null && (
          <circle
            cx={cx} cy={cx} r={r} fill="none"
            stroke={color} strokeWidth={3}
            strokeDasharray={`${filled} ${circ - filled}`}
            strokeLinecap="round"
            transform={`rotate(-90 ${cx} ${cx})`}
          />
        )}
      </svg>
      {/* Center text */}
      <div style={{
        position: "absolute", inset: 0,
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
        gap: 2,
      }}>
        <span style={{ fontFamily: MONO, fontWeight: 300, fontSize: 76, lineHeight: 1, color }}>
          {score != null ? Math.round(score) : "—"}
        </span>
      </div>
    </div>
  );
}

// Component score card — left color border, label, score, progress bar
function ComponentCard({ label, value, color }) {
  const pct = value != null ? Math.min(Math.round(value), 100) : 0;
  return (
    <div style={{
      background: C.card,
      borderLeft: `3px solid ${color}`,
      borderRadius: "0 8px 8px 0",
      padding: "12px 14px 10px",
      display: "flex", flexDirection: "column", gap: 6,
    }}>
      <span style={{
        fontFamily: SANS, fontSize: 9, fontWeight: 500,
        letterSpacing: "0.12em", color: C.label,
      }}>
        {label}
      </span>
      <span style={{
        fontFamily: MONO, fontWeight: 300, fontSize: 34, lineHeight: 1,
        color: value != null ? color : C.muted,
      }}>
        {value != null ? Math.round(value) : "—"}
      </span>
      <div style={{ height: 2, background: "rgba(255,255,255,0.06)", borderRadius: 1 }}>
        <div style={{
          height: "100%", width: `${pct}%`, background: color, borderRadius: 1,
          transition: "width 600ms ease",
        }} />
      </div>
    </div>
  );
}

// Factor list item with tinted background and left border
function FactorItem({ text, positive }) {
  const color = positive ? C.teal : C.red;
  return (
    <li style={{
      fontFamily: SANS, fontSize: 13, color: C.body, lineHeight: 1.6,
      background: positive ? "rgba(0,229,160,0.05)" : "rgba(255,77,109,0.05)",
      borderLeft: `2px solid ${color}`,
      borderRadius: "0 6px 6px 0",
      padding: "8px 12px",
      listStyle: "none",
    }}>
      {text}
    </li>
  );
}

// ── Last Night view ───────────────────────────────────────────────────────────
function LastNight({ data, loading }) {
  if (loading) {
    return (
      <div className="fade-in" style={{ padding: 16, display: "flex", flexDirection: "column", gap: 20 }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 10, paddingTop: 16 }}>
          <Skeleton h={200} w={200} radius={100} />
          <Skeleton h={12} w={80} />
          <Skeleton h={10} w={120} />
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          {[0, 1, 2, 3].map(i => <Skeleton key={i} h={80} radius={8} />)}
        </div>
        <Skeleton h={56} radius={8} />
        <Skeleton h={56} radius={8} />
      </div>
    );
  }

  if (!data || data.error) {
    return <Placeholder>No recovery data yet.{"\n"}Run the pipeline first.</Placeholder>;
  }

  return (
    <div className="fade-in" style={{ padding: "16px 16px 8px", display: "flex", flexDirection: "column", gap: 20 }}>
      {/* Hero */}
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 16, gap: 4 }}>
        <ScoreRing score={data.total_score} />
        <span style={{
          fontFamily: SANS, fontSize: 9, fontWeight: 500,
          letterSpacing: "0.12em", color: C.label, marginTop: 2,
        }}>
          RECOVERY SCORE
        </span>
        {data.duration_hours != null && (
          <span style={{ fontFamily: MONO, fontSize: 13, color: C.body }}>
            {data.duration_hours.toFixed(1)}h sleep
          </span>
        )}
        {data.bed_entry && data.bed_exit && (
          <span style={{ fontFamily: MONO, fontSize: 11, color: C.muted }}>
            {fmtTime(data.bed_entry)} → {fmtTime(data.bed_exit)}
          </span>
        )}
      </div>

      {/* Component cards 2×2 */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        {COMPONENTS.map(({ key, label, color }) => (
          <ComponentCard key={key} label={label} value={data[key]} color={color} />
        ))}
      </div>

      {/* Positive factors */}
      {data.positives?.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span style={{
            fontFamily: SANS, fontSize: 9, fontWeight: 500,
            letterSpacing: "0.12em", color: C.label,
          }}>
            WHAT WENT WELL
          </span>
          <ul style={{ display: "flex", flexDirection: "column", gap: 4, margin: 0, padding: 0 }}>
            {data.positives.map((f, i) => <FactorItem key={i} text={f} positive />)}
          </ul>
        </div>
      )}

      {/* Negative factors */}
      {data.negatives?.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span style={{
            fontFamily: SANS, fontSize: 9, fontWeight: 500,
            letterSpacing: "0.12em", color: C.label,
          }}>
            WHAT TO IMPROVE
          </span>
          <ul style={{ display: "flex", flexDirection: "column", gap: 4, margin: 0, padding: 0 }}>
            {data.negatives.map((f, i) => <FactorItem key={i} text={f} positive={false} />)}
          </ul>
        </div>
      )}
    </div>
  );
}

// ── Persistent trend panel ────────────────────────────────────────────────────
function TrendPanel({ latest, scoresCount }) {
  if (scoresCount < 7) {
    return (
      <div>
        <p style={{
          fontFamily: SANS, fontSize: 10, fontWeight: 500,
          letterSpacing: "0.12em", color: C.label, marginBottom: 10,
        }}>
          PERSISTENT TRENDS
        </p>
        <p style={{ fontFamily: SANS, fontSize: 13, color: C.muted, lineHeight: 1.6 }}>
          Trend analysis available after 7 nights.
        </p>
      </div>
    );
  }

  const factors = latest?.persistent_factors ?? [];
  if (factors.length === 0) return null;

  return (
    <div>
      <p style={{
        fontFamily: SANS, fontSize: 10, fontWeight: 500,
        letterSpacing: "0.12em", color: C.label, marginBottom: 10,
      }}>
        PERSISTENT TRENDS
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {factors.map((f, i) => {
          const improving = f.direction === "improving";
          const color = improving ? C.teal : C.red;
          return (
            <div key={i} style={{
              display: "flex", alignItems: "flex-start", gap: 10,
              padding: "8px 12px",
              background: improving ? "rgba(0,229,160,0.05)" : "rgba(255,77,109,0.05)",
              borderLeft: `2px solid ${color}`,
              borderRadius: "0 6px 6px 0",
            }}>
              <span style={{
                fontFamily: MONO, fontSize: 16, color, flexShrink: 0, lineHeight: 1.3,
              }}>
                {improving ? "↑" : "↓"}
              </span>
              <div>
                <span style={{ fontFamily: SANS, fontSize: 13, color: C.body }}>
                  {f.magnitude_description}
                </span>
                <span style={{
                  fontFamily: SANS, fontSize: 10, color: C.muted, display: "block",
                  marginTop: 2,
                }}>
                  {f.nights_observed} nights · {f.feature_name.replace(/_/g, " ")}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Trends view ───────────────────────────────────────────────────────────────
const TT_STYLE = {
  background: "#0d1117",
  border: "1px solid rgba(255,255,255,0.06)",
  borderRadius: 8,
  color: "rgba(255,255,255,0.8)",
  fontFamily: "'Inter', sans-serif",
  fontSize: 12,
};

function Trends({ scores, loading, latest }) {
  if (loading) {
    return (
      <div className="fade-in" style={{ padding: 16, display: "flex", flexDirection: "column", gap: 20 }}>
        <Skeleton h={12} w="50%" />
        <Skeleton h={220} radius={8} />
        <Skeleton h={12} w="50%" />
        <Skeleton h={180} radius={8} />
      </div>
    );
  }

  const chartData = scores
    .filter(d => d.total_score != null)
    .slice(-30)
    .map((d, i) => ({
      date: d.bed_entry ? d.bed_entry.slice(5, 10) : String(i),
      score: Math.round(d.total_score),
      arch: Math.round(d.architecture_score || 0),
      cont: Math.round(d.continuity_score || 0),
      brth: Math.round(d.breathing_score || 0),
      env:  Math.round(d.environment_score || 0),
    }));

  if (chartData.length === 0)
    return <Placeholder>No trend data yet — run the pipeline on a few nights.</Placeholder>;

  return (
    <div className="fade-in" style={{ padding: 16, display: "flex", flexDirection: "column", gap: 24 }}>
      {/* Recovery area chart */}
      <div>
        <p style={{
          fontFamily: SANS, fontSize: 10, fontWeight: 500, letterSpacing: "0.12em",
          color: C.label, marginBottom: 12,
        }}>
          RECOVERY — LAST {chartData.length} NIGHTS
        </p>
        <ResponsiveContainer width="100%" height={220}>
          <AreaChart data={chartData} margin={{ top: 4, right: 4, left: -24, bottom: 0 }}>
            <defs>
              <linearGradient id="tealGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor={C.teal} stopOpacity={0.25} />
                <stop offset="95%" stopColor={C.teal} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="rgba(255,255,255,0.04)" />
            <XAxis dataKey="date"
              tick={{ fill: C.muted, fontSize: 10, fontFamily: SANS }}
              tickLine={false} axisLine={false} />
            <YAxis domain={[0, 100]}
              tick={{ fill: C.muted, fontSize: 10, fontFamily: SANS }}
              tickLine={false} axisLine={false} />
            <ReferenceLine y={75} stroke={C.muted} strokeDasharray="4 4"
              label={{ value: "target", position: "insideTopRight", fill: C.muted, fontSize: 9, fontFamily: SANS }} />
            <Tooltip contentStyle={TT_STYLE} formatter={v => [`${v}/100`, "Recovery"]} />
            <Area type="basis" dataKey="score"
              stroke={C.teal} strokeWidth={2} fill="url(#tealGrad)" dot={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Component lines */}
      <div>
        <p style={{
          fontFamily: SANS, fontSize: 10, fontWeight: 500, letterSpacing: "0.12em",
          color: C.label, marginBottom: 12,
        }}>
          COMPONENT SCORES
        </p>
        <ResponsiveContainer width="100%" height={210}>
          <LineChart data={chartData} margin={{ top: 4, right: 4, left: -24, bottom: 0 }}>
            <CartesianGrid stroke="rgba(255,255,255,0.04)" />
            <XAxis dataKey="date"
              tick={{ fill: C.muted, fontSize: 10, fontFamily: SANS }}
              tickLine={false} axisLine={false} />
            <YAxis domain={[0, 100]}
              tick={{ fill: C.muted, fontSize: 10, fontFamily: SANS }}
              tickLine={false} axisLine={false} />
            <Tooltip contentStyle={TT_STYLE} />
            <Legend
              iconType="plainline"
              wrapperStyle={{ fontFamily: SANS, fontSize: 11, color: C.body, paddingTop: 10 }}
            />
            <Line type="basis" dataKey="arch" stroke={C.arch} strokeWidth={1.5} dot={false} name="Architecture" />
            <Line type="basis" dataKey="cont" stroke={C.cont} strokeWidth={1.5} dot={false} name="Continuity" />
            <Line type="basis" dataKey="brth" stroke={C.brth} strokeWidth={1.5} dot={false} name="Breathing" />
            <Line type="basis" dataKey="env"  stroke={C.env}  strokeWidth={1.5} dot={false} name="Environment" />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Persistent trends panel */}
      <TrendPanel latest={latest} scoresCount={chartData.length} />
    </div>
  );
}

// ── Sleep Breakdown view ──────────────────────────────────────────────────────
const STAGE_COLORS = {
  awake: "rgba(255,255,255,0.28)",
  light: "#4a90d9",
  deep:  "#7b8ff7",
  rem:   "#00e5a0",
};

// Classifier outputs three classes only: awake, deep, light (light/REM combined)
function classifyStage(br, mp) {
  if (mp > 0.3)                            return "awake";
  if (mp < 0.10 && br >= 10 && br < 13.8) return "deep";
  return "light";
}

// Rendering-only split: light windows with high breathing variance → rem
const BR_VAR_THRESHOLD = 2.0;
const BR_VAR_WIN = 10;
function renderingStage(classifiedStages, brValues, i) {
  if (classifiedStages[i] !== "light") return classifiedStages[i];
  const lo = Math.max(0, i - Math.floor(BR_VAR_WIN / 2));
  const hi = Math.min(brValues.length, lo + BR_VAR_WIN);
  const slice = brValues.slice(lo, hi);
  const mean = slice.reduce((a, b) => a + b, 0) / slice.length;
  const variance = slice.reduce((a, b) => a + (b - mean) ** 2, 0) / slice.length;
  return variance > BR_VAR_THRESHOLD ? "rem" : "light";
}

function SleepBreakdown({ data, loading }) {
  if (loading) {
    return (
      <div className="fade-in" style={{ padding: 16, display: "flex", flexDirection: "column", gap: 20 }}>
        <Skeleton h={12} w="40%" />
        <Skeleton h={40} radius={6} />
        <Skeleton h={130} radius={8} />
        <Skeleton h={100} radius={8} />
      </div>
    );
  }

  if (!data || !data.csi?.length)
    return <Placeholder>No detailed sleep data available yet.</Placeholder>;

  // Classify (3 classes) then smooth with 10-window mode filter
  const rawStages = data.csi.map(row => classifyStage(row.br ?? 14, row.mp ?? 0.1));
  const stages = modeFilter(rawStages, 10);

  // Split light → rem for rendering only, based on breathing irregularity
  const brValues = data.csi.map(row => row.br ?? 14);
  const renderStages = stages.map((_, i) => renderingStage(stages, brValues, i));

  // Collapse to runs for efficient rendering
  const runs = [];
  let cur = { stage: renderStages[0], count: 1 };
  for (let i = 1; i < renderStages.length; i++) {
    if (renderStages[i] === cur.stage) { cur.count++; }
    else { runs.push({ ...cur }); cur = { stage: renderStages[i], count: 1 }; }
  }
  runs.push({ ...cur });

  // Hour-mark labels along the timeline
  const bedEntry  = data.bed_entry ? new Date(data.bed_entry) : null;
  const bedExit   = data.bed_exit  ? new Date(data.bed_exit)  : null;
  const durationMs = bedEntry && bedExit ? bedExit - bedEntry : null;

  const hourMarks = [];
  if (bedEntry && durationMs) {
    for (let h = 1; h <= 12; h++) {
      const ms = h * 3_600_000;
      if (ms >= durationMs) break;
      hourMarks.push({
        pct: (ms / durationMs) * 100,
        label: new Date(bedEntry.getTime() + ms)
          .toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }),
      });
    }
  }

  // Sensor data — downsample to ~100 points for smooth rendering
  const rawSensors = data.sensors || [];
  const step = rawSensors.length > 150 ? Math.floor(rawSensors.length / 100) : 1;
  const sensorData = rawSensors
    .filter((_, i) => i % step === 0)
    .map((s, i) => ({
      i,
      co2:      Math.round(s.co2_ppm ?? 700),
      temp:     parseFloat((s.temperature ?? 20).toFixed(1)),
      humidity: parseFloat((s.humidity ?? 50).toFixed(1)),
      voc:      Math.round(s.voc_index ?? 100),
    }));
  const co2Max = sensorData.length ? Math.max(...sensorData.map(d => d.co2), 1200) : 2000;

  return (
    <div className="fade-in" style={{ padding: 16, display: "flex", flexDirection: "column", gap: 20 }}>
      {/* Hypnogram bar */}
      <div>
        <p style={{
          fontFamily: SANS, fontSize: 10, fontWeight: 500, letterSpacing: "0.12em",
          color: C.label, marginBottom: 10,
        }}>
          SLEEP STAGES
        </p>

        <div style={{
          display: "flex", height: 40, borderRadius: 6, overflow: "hidden",
          border: `1px solid ${C.border}`,
        }}>
          {runs.map((run, i) => (
            <div key={i} title={run.stage} style={{
              flex: run.count,
              background: STAGE_COLORS[run.stage] ?? C.muted,
            }} />
          ))}
        </div>

        {/* Hour marks */}
        {hourMarks.length > 0 && (
          <div style={{ position: "relative", height: 18, marginTop: 3 }}>
            {hourMarks.map((m, i) => (
              <span key={i} style={{
                position: "absolute", left: `${m.pct}%`, transform: "translateX(-50%)",
                fontFamily: MONO, fontSize: 9, color: C.muted, whiteSpace: "nowrap",
              }}>
                {m.label}
              </span>
            ))}
          </div>
        )}

        {/* Legend */}
        <div style={{ display: "flex", gap: 14, marginTop: 10, flexWrap: "wrap" }}>
          {[["awake", "Wake"], ["light", "Light"], ["deep", "Deep"], ["rem", "REM"]].map(([key, label]) => (
            <div key={key} style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <div style={{ width: 10, height: 10, background: STAGE_COLORS[key], borderRadius: 2 }} />
              <span style={{ fontFamily: SANS, fontSize: 10, color: C.muted }}>{label}</span>
            </div>
          ))}
        </div>
        {/* Transparency note */}
        <p style={{
          fontFamily: SANS, fontSize: 9, color: C.muted, marginTop: 8, lineHeight: 1.5,
          fontStyle: "italic",
        }}>
          REM estimated from breathing irregularity within light sleep classification
        </p>
      </div>

      {/* CO2 chart */}
      {sensorData.length > 0 && (
        <div style={{
          background: C.card, borderRadius: 8, border: `1px solid ${C.border}`,
          padding: "14px 4px 8px",
        }}>
          <p style={{
            fontFamily: SANS, fontSize: 10, fontWeight: 500, letterSpacing: "0.12em",
            color: C.label, marginBottom: 10, paddingLeft: 14,
          }}>
            CO₂ (PPM)
          </p>
          <ResponsiveContainer width="100%" height={140}>
            <AreaChart data={sensorData} margin={{ top: 4, right: 8, left: -18, bottom: 0 }}>
              <defs>
                <linearGradient id="co2Grad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor={C.amber} stopOpacity={0.20} />
                  <stop offset="95%" stopColor={C.amber} stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="rgba(255,255,255,0.04)" />
              <YAxis domain={[350, co2Max + 150]}
                tick={{ fill: C.muted, fontSize: 10, fontFamily: SANS }}
                tickLine={false} axisLine={false} />
              <ReferenceLine y={1000} stroke={C.amber} strokeDasharray="4 3"
                label={{ value: "safe limit", position: "insideTopLeft", fill: C.amber, fontSize: 9, fontFamily: SANS }} />
              <ReferenceLine y={1500} stroke={C.red} strokeDasharray="4 3"
                label={{ value: "poor", position: "insideTopLeft", fill: C.red, fontSize: 9, fontFamily: SANS }} />
              <Tooltip contentStyle={TT_STYLE} formatter={v => [`${v} ppm`, "CO₂"]} />
              <Area type="basis" dataKey="co2"
                stroke={C.amber} strokeWidth={1.5} fill="url(#co2Grad)" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Temperature chart */}
      {sensorData.length > 0 && (
        <div style={{
          background: C.card, borderRadius: 8, border: `1px solid ${C.border}`,
          padding: "14px 4px 8px",
        }}>
          <p style={{
            fontFamily: SANS, fontSize: 10, fontWeight: 500, letterSpacing: "0.12em",
            color: C.label, marginBottom: 10, paddingLeft: 14,
          }}>
            TEMPERATURE (°C)
          </p>
          <ResponsiveContainer width="100%" height={110}>
            <AreaChart data={sensorData} margin={{ top: 4, right: 8, left: -18, bottom: 0 }}>
              <defs>
                <linearGradient id="tempGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor={C.blue} stopOpacity={0.22} />
                  <stop offset="95%" stopColor={C.blue} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="rgba(255,255,255,0.04)" />
              <YAxis domain={["auto", "auto"]}
                tick={{ fill: C.muted, fontSize: 10, fontFamily: SANS }}
                tickLine={false} axisLine={false} />
              <Tooltip contentStyle={TT_STYLE} formatter={v => [`${v}°C`, "Temp"]} />
              <Area type="basis" dataKey="temp"
                stroke={C.blue} strokeWidth={1.5} fill="url(#tempGrad)" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Humidity chart */}
      {sensorData.length > 0 && (
        <div style={{
          background: C.card, borderRadius: 8, border: `1px solid ${C.border}`,
          padding: "14px 4px 8px",
        }}>
          <p style={{
            fontFamily: SANS, fontSize: 10, fontWeight: 500, letterSpacing: "0.12em",
            color: C.label, marginBottom: 10, paddingLeft: 14,
          }}>
            HUMIDITY (%)
          </p>
          <ResponsiveContainer width="100%" height={110}>
            <AreaChart data={sensorData} margin={{ top: 4, right: 8, left: -18, bottom: 0 }}>
              <defs>
                <linearGradient id="humGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor="#a78bfa" stopOpacity={0.22} />
                  <stop offset="95%" stopColor="#a78bfa" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="rgba(255,255,255,0.04)" />
              <YAxis domain={["auto", "auto"]}
                tick={{ fill: C.muted, fontSize: 10, fontFamily: SANS }}
                tickLine={false} axisLine={false} />
              <Tooltip contentStyle={TT_STYLE} formatter={v => [`${v}%`, "Humidity"]} />
              <Area type="basis" dataKey="humidity"
                stroke="#a78bfa" strokeWidth={1.5} fill="url(#humGrad)" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* VOC chart */}
      {sensorData.length > 0 && (
        <div style={{
          background: C.card, borderRadius: 8, border: `1px solid ${C.border}`,
          padding: "14px 4px 8px",
        }}>
          <p style={{
            fontFamily: SANS, fontSize: 10, fontWeight: 500, letterSpacing: "0.12em",
            color: C.label, marginBottom: 10, paddingLeft: 14,
          }}>
            VOC INDEX
          </p>
          <ResponsiveContainer width="100%" height={110}>
            <AreaChart data={sensorData} margin={{ top: 4, right: 8, left: -18, bottom: 0 }}>
              <defs>
                <linearGradient id="vocGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor="#34d399" stopOpacity={0.20} />
                  <stop offset="95%" stopColor="#34d399" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="rgba(255,255,255,0.04)" />
              <YAxis domain={["auto", "auto"]}
                tick={{ fill: C.muted, fontSize: 10, fontFamily: SANS }}
                tickLine={false} axisLine={false} />
              <Tooltip contentStyle={TT_STYLE} formatter={v => [`${v}`, "VOC Index"]} />
              <Area type="basis" dataKey="voc"
                stroke="#34d399" strokeWidth={1.5} fill="url(#vocGrad)" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

// ── Log history view ──────────────────────────────────────────────────────────
function LogView({ history, loading }) {
  if (loading) {
    return (
      <div className="fade-in" style={{ padding: "16px 0" }}>
        <Skeleton h={12} w="40%" style={{ margin: "0 16px 16px" }} />
        {[0, 1, 2, 3, 4].map(i => (
          <div key={i}>
            <Skeleton h={50} radius={0} style={{ margin: "0 16px" }} />
            <div style={{ height: 1, background: C.border, margin: "0 16px" }} />
          </div>
        ))}
      </div>
    );
  }

  const entries = history.filter(d => d.recovery != null);
  if (entries.length === 0) return <Placeholder>No morning log entries yet.</Placeholder>;

  return (
    <div className="fade-in" style={{ padding: "16px 0" }}>
      <p style={{
        fontFamily: SANS, fontSize: 10, fontWeight: 500, letterSpacing: "0.12em",
        color: C.label, padding: "0 16px 12px",
      }}>
        MORNING LOG
      </p>
      {entries.map((e, idx) => (
        <div key={e.id}>
          <div style={{
            display: "flex", alignItems: "center", gap: 8,
            padding: "12px 16px",
            background: idx % 2 === 1 ? "rgba(255,255,255,0.015)" : "transparent",
          }}>
            <span style={{
              fontFamily: MONO, fontSize: 12, color: C.body,
              minWidth: 72, flexShrink: 0,
            }}>
              {e.timestamp ? e.timestamp.slice(0, 10) : "—"}
            </span>

            <div style={{ flex: 1, display: "flex", gap: 10 }}>
              {[["REC", e.recovery], ["NRG", e.energy], ["CLR", e.clarity], ["MOOD", e.mood]].map(([lbl, val]) => (
                <div key={lbl} style={{ display: "flex", flexDirection: "column", alignItems: "center", minWidth: 26 }}>
                  <span style={{ fontFamily: MONO, fontSize: 13, color: "rgba(255,255,255,0.8)" }}>
                    {val ?? "—"}
                  </span>
                  <span style={{
                    fontFamily: SANS, fontSize: 8, color: C.muted,
                    letterSpacing: "0.06em",
                  }}>
                    {lbl}
                  </span>
                </div>
              ))}
            </div>

            {e.total_score != null && (
              <span style={{
                fontFamily: MONO, fontWeight: 300, fontSize: 15,
                color: scoreAccent(e.total_score),
              }}>
                {Math.round(e.total_score)}
              </span>
            )}

            {e.notes && (
              <span style={{ color: C.muted, fontSize: 10 }} title={e.notes}>·</span>
            )}
          </div>
          <div style={{ height: 1, background: C.border, margin: "0 16px" }} />
        </div>
      ))}
    </div>
  );
}

// ── Tab bar & root ────────────────────────────────────────────────────────────
const TABS = ["Last Night", "Trends", "Sleep", "Log"];

export default function App() {
  const [tab, setTab] = useState(0);
  const { data: latest,  loading: latestLoading  } = useLatest();
  const { data: scores,  loading: scoresLoading  } = useScores();
  const { data: history, loading: historyLoading } = useHistory();

  const views = [
    <LastNight    key="ln" data={latest}  loading={latestLoading}  />,
    <Trends       key="tr" scores={scores} loading={scoresLoading} latest={latest} />,
    <SleepBreakdown key="sb" data={latest} loading={latestLoading}  />,
    <LogView      key="lv" history={history} loading={historyLoading} />,
  ];

  return (
    <div style={{
      height: "100dvh",
      background: C.bg,
      color: "rgba(255,255,255,0.85)",
      display: "flex", flexDirection: "column",
      maxWidth: 430, margin: "0 auto",
      overflow: "hidden",
    }}>
      {/* Scrollable content — key forces remount + fade-in on tab switch */}
      <div key={tab} style={{ flex: 1, overflowY: "auto" }}>
        {views[tab]}
      </div>

      {/* Tab bar — 60 px, teal underline on active tab */}
      <nav style={{
        height: 60, flexShrink: 0,
        background: C.card,
        borderTop: `1px solid ${C.border}`,
        display: "flex",
      }}>
        {TABS.map((label, i) => {
          const active = tab === i;
          return (
            <button
              key={label}
              onClick={() => setTab(i)}
              style={{
                flex: 1, display: "flex", flexDirection: "column",
                alignItems: "center", justifyContent: "center",
                background: "none", border: "none", cursor: "pointer",
                padding: 0, position: "relative",
                color: active ? C.teal : "rgba(255,255,255,0.35)",
                transition: "color 150ms ease",
              }}
            >
              {active && (
                <div style={{
                  position: "absolute", top: 0, left: "20%", right: "20%",
                  height: 2, background: C.teal, borderRadius: "0 0 2px 2px",
                }} />
              )}
              <span style={{
                fontFamily: SANS,
                fontSize: 11,
                fontWeight: active ? 500 : 400,
                letterSpacing: "0.02em",
              }}>
                {label}
              </span>
            </button>
          );
        })}
      </nav>
    </div>
  );
}
