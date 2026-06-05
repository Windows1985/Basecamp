import { useState, useEffect } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, AreaChart, Area,
} from "recharts";

const API = "http://localhost:5000";

// ── Colour helpers ──────────────────────────────────────────────────────────
function scoreColour(v) {
  if (v == null) return "text-slate-400";
  if (v >= 80) return "text-emerald-400";
  if (v >= 60) return "text-yellow-400";
  return "text-red-400";
}
function scoreRing(v) {
  if (v == null) return "border-slate-600";
  if (v >= 80) return "border-emerald-500";
  if (v >= 60) return "border-yellow-500";
  return "border-red-500";
}

// ── Shared hooks ─────────────────────────────────────────────────────────────
function useLatest() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    fetch(`${API}/latest`)
      .then(r => r.json())
      .then(setData)
      .catch(setError);
  }, []);
  return { data, error };
}

function useHistory() {
  const [data, setData] = useState([]);
  useEffect(() => {
    fetch(`${API}/history`)
      .then(r => r.json())
      .then(setData)
      .catch(() => setData([]));
  }, []);
  return data;
}

// ── Last Night view ───────────────────────────────────────────────────────────
function LastNight({ data }) {
  if (!data) return <Placeholder>No recovery data yet. Run the pipeline first.</Placeholder>;
  if (data.error) return <Placeholder>{data.error}</Placeholder>;

  const components = [
    { label: "Architecture", key: "architecture_score" },
    { label: "Continuity",   key: "continuity_score" },
    { label: "Breathing",    key: "breathing_score" },
    { label: "Environment",  key: "environment_score" },
  ];

  return (
    <div className="p-4 space-y-6">
      {/* Big recovery number */}
      <div className="flex flex-col items-center pt-4">
        <div className={`text-8xl font-bold tabular-nums ${scoreColour(data.total_score)}`}>
          {Math.round(data.total_score)}
        </div>
        <div className="text-slate-400 text-sm mt-1 tracking-wide">RECOVERY SCORE</div>
        <div className="text-slate-500 text-xs mt-1">
          {data.duration_hours ? `${data.duration_hours.toFixed(1)}h sleep` : ""}
        </div>
      </div>

      {/* Component cards */}
      <div className="grid grid-cols-2 gap-3">
        {components.map(({ label, key }) => (
          <div key={key}
            className={`bg-slate-800 rounded-xl p-3 border-l-4 ${scoreRing(data[key])}`}>
            <div className="text-slate-400 text-xs mb-1">{label}</div>
            <div className={`text-2xl font-semibold tabular-nums ${scoreColour(data[key])}`}>
              {data[key] != null ? Math.round(data[key]) : "—"}
            </div>
          </div>
        ))}
      </div>

      {/* Factors */}
      {data.positives?.length > 0 && (
        <div>
          <h3 className="text-slate-400 text-xs uppercase tracking-widest mb-2">What went well</h3>
          <ul className="space-y-2">
            {data.positives.map((f, i) => (
              <li key={i} className="flex gap-2 text-sm text-slate-200">
                <span className="text-emerald-400 mt-0.5">+</span>
                <span>{f}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {data.negatives?.length > 0 && (
        <div>
          <h3 className="text-slate-400 text-xs uppercase tracking-widest mb-2">What to improve</h3>
          <ul className="space-y-2">
            {data.negatives.map((f, i) => (
              <li key={i} className="flex gap-2 text-sm text-slate-200">
                <span className="text-red-400 mt-0.5">−</span>
                <span>{f}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ── Trends view ───────────────────────────────────────────────────────────────
function Trends({ history }) {
  const chartData = history
    .filter(d => d.total_score != null)
    .map(d => ({
      date: d.timestamp ? d.timestamp.slice(5, 10) : "",
      score: Math.round(d.total_score),
    }))
    .reverse()
    .slice(-30);

  if (chartData.length === 0)
    return <Placeholder>No trend data yet — log more nights to see trends.</Placeholder>;

  return (
    <div className="p-4 space-y-4">
      <h2 className="text-slate-300 font-medium">Recovery — last {chartData.length} nights</h2>
      <ResponsiveContainer width="100%" height={260}>
        <AreaChart data={chartData} margin={{ top: 5, right: 8, left: -20, bottom: 0 }}>
          <defs>
            <linearGradient id="scoreGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis dataKey="date" tick={{ fill: "#64748b", fontSize: 11 }} />
          <YAxis domain={[0, 100]} tick={{ fill: "#64748b", fontSize: 11 }} />
          <Tooltip
            contentStyle={{ background: "#1e293b", border: "none", borderRadius: 8, color: "#e2e8f0" }}
            formatter={v => [`${v}/100`, "Recovery"]}
          />
          <Area
            type="monotone" dataKey="score"
            stroke="#3b82f6" strokeWidth={2}
            fill="url(#scoreGrad)" dot={{ r: 3, fill: "#3b82f6" }}
          />
        </AreaChart>
      </ResponsiveContainer>

      {/* Components trend */}
      <h2 className="text-slate-300 font-medium mt-2">Component scores</h2>
      <ResponsiveContainer width="100%" height={200}>
        <LineChart
          data={history
            .filter(d => d.architecture_score != null)
            .map(d => ({
              date: d.timestamp?.slice(5, 10),
              arch: Math.round(d.architecture_score),
              cont: Math.round(d.continuity_score),
              brth: Math.round(d.breathing_score),
              env:  Math.round(d.environment_score),
            }))
            .reverse()
            .slice(-30)
          }
          margin={{ top: 5, right: 8, left: -20, bottom: 0 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis dataKey="date" tick={{ fill: "#64748b", fontSize: 10 }} />
          <YAxis domain={[0, 100]} tick={{ fill: "#64748b", fontSize: 10 }} />
          <Tooltip contentStyle={{ background: "#1e293b", border: "none", borderRadius: 8, color: "#e2e8f0" }} />
          <Line type="monotone" dataKey="arch" stroke="#818cf8" strokeWidth={1.5} dot={false} name="Architecture" />
          <Line type="monotone" dataKey="cont" stroke="#34d399" strokeWidth={1.5} dot={false} name="Continuity" />
          <Line type="monotone" dataKey="brth" stroke="#fb923c" strokeWidth={1.5} dot={false} name="Breathing" />
          <Line type="monotone" dataKey="env"  stroke="#a78bfa" strokeWidth={1.5} dot={false} name="Environment" />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Sleep Breakdown view ──────────────────────────────────────────────────────
function SleepBreakdown({ data }) {
  if (!data || !data.csi?.length)
    return <Placeholder>No detailed sleep data available yet.</Placeholder>;

  // Approximate stages from CSI data
  const totalSamples = data.csi.length;
  const stages = data.csi.map(row => {
    const br = row.br ?? 14;
    const mp = row.mp ?? 0.1;
    if (mp > 0.3) return "awake";
    if (mp < 0.10 && br >= 10.5 && br <= 14.5) return "deep";
    if (mp < 0.08 && (br > 13.5)) return "rem";
    return "light";
  });

  const stageColours = { awake: "#475569", light: "#3b82f6", deep: "#1d4ed8", rem: "#7c3aed" };

  // CO2 sparkline data
  const co2Data = (data.sensors || []).map((s, i) => ({
    i,
    co2: Math.round(s.co2_ppm),
    temp: parseFloat(s.temperature?.toFixed(1)),
  }));

  return (
    <div className="p-4 space-y-5">
      <h2 className="text-slate-300 font-medium">Sleep stages</h2>

      {/* Stage timeline bar */}
      <div className="rounded-lg overflow-hidden h-10 flex">
        {stages.map((s, i) => (
          <div
            key={i}
            style={{ flex: 1, background: stageColours[s] ?? "#475569" }}
            title={s}
          />
        ))}
      </div>

      {/* Legend */}
      <div className="flex gap-4 text-xs text-slate-400">
        {Object.entries(stageColours).map(([label, colour]) => (
          <div key={label} className="flex items-center gap-1">
            <div className="w-3 h-3 rounded-sm" style={{ background: colour }} />
            <span className="capitalize">{label}</span>
          </div>
        ))}
      </div>

      {/* CO2 sparkline */}
      {co2Data.length > 0 && (
        <>
          <h3 className="text-slate-400 text-xs uppercase tracking-widest">CO₂ (ppm)</h3>
          <ResponsiveContainer width="100%" height={100}>
            <AreaChart data={co2Data} margin={{ top: 0, right: 0, left: -30, bottom: 0 }}>
              <defs>
                <linearGradient id="co2Grad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#f97316" stopOpacity={0.4} />
                  <stop offset="95%" stopColor="#f97316" stopOpacity={0} />
                </linearGradient>
              </defs>
              <YAxis tick={{ fill: "#64748b", fontSize: 10 }} />
              <Tooltip
                contentStyle={{ background: "#1e293b", border: "none", borderRadius: 8, color: "#e2e8f0" }}
                formatter={v => [`${v} ppm`, "CO₂"]}
              />
              <Area type="monotone" dataKey="co2" stroke="#f97316" strokeWidth={1.5} fill="url(#co2Grad)" dot={false} />
            </AreaChart>
          </ResponsiveContainer>

          <h3 className="text-slate-400 text-xs uppercase tracking-widest">Temperature (°C)</h3>
          <ResponsiveContainer width="100%" height={80}>
            <AreaChart data={co2Data} margin={{ top: 0, right: 0, left: -30, bottom: 0 }}>
              <defs>
                <linearGradient id="tempGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#06b6d4" stopOpacity={0.4} />
                  <stop offset="95%" stopColor="#06b6d4" stopOpacity={0} />
                </linearGradient>
              </defs>
              <YAxis tick={{ fill: "#64748b", fontSize: 10 }} domain={["auto", "auto"]} />
              <Tooltip
                contentStyle={{ background: "#1e293b", border: "none", borderRadius: 8, color: "#e2e8f0" }}
                formatter={v => [`${v}°C`, "Temp"]}
              />
              <Area type="monotone" dataKey="temp" stroke="#06b6d4" strokeWidth={1.5} fill="url(#tempGrad)" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </>
      )}
    </div>
  );
}

// ── Log view ──────────────────────────────────────────────────────────────────
function LogView({ history }) {
  const entries = history.filter(d => d.recovery != null);

  if (entries.length === 0)
    return <Placeholder>No morning log entries yet.</Placeholder>;

  return (
    <div className="p-4 space-y-3">
      <h2 className="text-slate-300 font-medium">Morning log history</h2>
      {entries.map(e => (
        <div key={e.id} className="bg-slate-800 rounded-xl p-4 space-y-2">
          <div className="flex justify-between items-center">
            <span className="text-slate-400 text-xs">
              {e.timestamp ? e.timestamp.slice(0, 10) : "—"}
            </span>
            {e.total_score != null && (
              <span className={`text-sm font-semibold tabular-nums ${scoreColour(e.total_score)}`}>
                {Math.round(e.total_score)}/100
              </span>
            )}
          </div>
          <div className="grid grid-cols-4 gap-2 text-center">
            {[
              ["Rec", e.recovery],
              ["Energy", e.energy],
              ["Clarity", e.clarity],
              ["Mood", e.mood],
            ].map(([label, val]) => (
              <div key={label}>
                <div className="text-lg font-semibold text-slate-200">{val ?? "—"}</div>
                <div className="text-xs text-slate-500">{label}</div>
              </div>
            ))}
          </div>
          {e.notes && (
            <p className="text-xs text-slate-400 italic border-t border-slate-700 pt-2">
              {e.notes}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Shared placeholder ────────────────────────────────────────────────────────
function Placeholder({ children }) {
  return (
    <div className="flex items-center justify-center h-64 px-8 text-center">
      <p className="text-slate-500 text-sm">{children}</p>
    </div>
  );
}

// ── Tab bar ───────────────────────────────────────────────────────────────────
const TABS = [
  { label: "Last Night", icon: "🌙" },
  { label: "Trends",     icon: "📈" },
  { label: "Sleep",      icon: "💤" },
  { label: "Log",        icon: "📋" },
];

// ── Root ──────────────────────────────────────────────────────────────────────
export default function App() {
  const [tab, setTab] = useState(0);
  const { data: latest } = useLatest();
  const history = useHistory();

  const views = [
    <LastNight key="ln" data={latest} />,
    <Trends key="tr" history={history} />,
    <SleepBreakdown key="sb" data={latest} />,
    <LogView key="lv" history={history} />,
  ];

  return (
    <div className="min-h-dvh bg-slate-950 text-slate-100 flex flex-col max-w-lg mx-auto">
      <div className="flex-1 overflow-y-auto pb-20">{views[tab]}</div>

      {/* Bottom tab bar */}
      <nav className="fixed bottom-0 left-0 right-0 max-w-lg mx-auto bg-slate-900 border-t border-slate-800 flex">
        {TABS.map((t, i) => (
          <button
            key={t.label}
            onClick={() => setTab(i)}
            className={`flex-1 flex flex-col items-center py-3 gap-0.5 text-xs transition-colors
              ${tab === i ? "text-blue-400" : "text-slate-500"}`}
          >
            <span className="text-lg leading-none">{t.icon}</span>
            {t.label}
          </button>
        ))}
      </nav>
    </div>
  );
}
