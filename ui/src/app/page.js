"use client"

import { useState, useEffect, useCallback } from "react"

const API = typeof window !== "undefined"
  ? `${window.location.protocol}//${window.location.hostname}:8100`
  : "http://localhost:8100"

// ── Light-mode Burnside Project styles ─────────────────────────────────

const s = {
  // Layout
  layout: { display: "flex", minHeight: "100vh" },
  sidebar: {
    width: 240, background: "#fff", borderRight: "1px solid #e2e8f0",
    display: "flex", flexDirection: "column", position: "fixed", top: 0, bottom: 0, left: 0, zIndex: 10,
    overflowY: "auto",
  },
  sidebarLogo: { padding: "20px 20px 4px", fontSize: 17, fontWeight: 700, color: "#1e293b" },
  sidebarSub: { padding: "0 20px 16px", fontSize: 11, color: "#94a3b8", letterSpacing: 1 },
  navSection: { padding: "12px 0 4px 20px", fontSize: 10, fontWeight: 600, color: "#94a3b8", textTransform: "uppercase", letterSpacing: 1 },
  navItem: (active) => ({
    display: "flex", alignItems: "center", gap: 10, padding: "8px 20px", fontSize: 13, fontWeight: active ? 600 : 400,
    color: active ? "#2563eb" : "#64748b", background: active ? "#eff6ff" : "transparent",
    cursor: "pointer", borderRight: active ? "3px solid #2563eb" : "3px solid transparent",
    textDecoration: "none",
  }),
  navDot: (color) => ({ width: 8, height: 8, borderRadius: "50%", background: color, flexShrink: 0 }),
  sidebarFooter: { marginTop: "auto", padding: "16px 20px", borderTop: "1px solid #e2e8f0", fontSize: 10, color: "#94a3b8" },
  main: { marginLeft: 240, flex: 1, padding: "24px 32px 64px", background: "#f8fafc", minHeight: "100vh" },

  // Header
  topBar: { display: "flex", gap: 20, padding: "16px 0", marginBottom: 24, flexWrap: "wrap", alignItems: "center" },
  stat: { textAlign: "center", minWidth: 80, background: "#fff", borderRadius: 8, padding: "12px 16px", border: "1px solid #e2e8f0", boxShadow: "0 1px 3px rgba(0,0,0,0.04)" },
  statVal: { fontSize: 20, fontWeight: 700, color: "#1e293b" },
  statLbl: { fontSize: 10, color: "#94a3b8", textTransform: "uppercase", letterSpacing: 1, marginTop: 2 },

  // Sections
  section: { marginBottom: 32 },
  sectionHead: {
    display: "flex", alignItems: "center", gap: 10, marginBottom: 16, paddingBottom: 10,
    borderBottom: "1px solid #e2e8f0",
  },
  sectionTitle: { fontSize: 15, fontWeight: 700, color: "#1e293b" },
  sectionSub: { fontSize: 11, color: "#94a3b8", fontWeight: 400, marginLeft: 4 },

  // Cards
  grid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))", gap: 16 },
  card: (accent) => ({
    background: "#fff", border: "1px solid #e2e8f0", borderLeft: `3px solid ${accent || "#e2e8f0"}`,
    borderRadius: 8, padding: 20, boxShadow: "0 1px 3px rgba(0,0,0,0.04)",
  }),
  cardTitle: { fontSize: 14, fontWeight: 600, color: "#1e293b", marginBottom: 4 },
  cardDesc: { fontSize: 12, color: "#94a3b8", marginBottom: 12 },

  // Forms
  label: { fontSize: 11, color: "#64748b", marginBottom: 3, display: "block", fontWeight: 500 },
  input: {
    width: "100%", padding: "8px 12px", background: "#f8fafc", border: "1px solid #e2e8f0",
    borderRadius: 6, color: "#1e293b", fontSize: 13, boxSizing: "border-box",
    outline: "none",
  },
  select: {
    width: "100%", padding: "8px 12px", background: "#f8fafc", border: "1px solid #e2e8f0",
    borderRadius: 6, color: "#1e293b", fontSize: 13,
  },
  row: { display: "flex", gap: 8, alignItems: "end" },
  gap: { marginBottom: 10 },

  // Buttons
  btn: { padding: "8px 16px", borderRadius: 6, border: "none", fontSize: 12, fontWeight: 600, cursor: "pointer", transition: "all 0.15s" },
  btnBlue: { background: "#2563eb", color: "#fff" },
  btnGreen: { background: "#16a34a", color: "#fff" },
  btnRed: { background: "#dc2626", color: "#fff" },
  btnGhost: { background: "#fff", color: "#64748b", border: "1px solid #e2e8f0" },
  btnFull: { width: "100%", marginTop: 10 },

  // Misc
  badge: (c) => ({
    display: "inline-block", padding: "2px 10px", borderRadius: 12, fontSize: 10, fontWeight: 600,
    background: c + "15", color: c, border: `1px solid ${c}30`,
  }),
  table: { width: "100%", borderCollapse: "collapse", fontSize: 12 },
  th: { textAlign: "left", padding: "8px 10px", borderBottom: "2px solid #e2e8f0", color: "#64748b", fontWeight: 600, fontSize: 11 },
  td: { padding: "7px 10px", borderBottom: "1px solid #f1f5f9", color: "#334155" },
  mono: {
    fontFamily: "'SF Mono', Menlo, monospace", fontSize: 12, background: "#f8fafc", border: "1px solid #e2e8f0",
    borderRadius: 6, padding: 16, maxHeight: 280, overflow: "auto", whiteSpace: "pre-wrap", color: "#475569",
  },
}

// ── API ─────────────────────────────────────────────────────────────────

async function api(path, opts = {}) {
  const res = await fetch(`${API}${path}`, { headers: { "Content-Type": "application/json" }, ...opts })
  return res.json()
}
function post(path, body) { return api(path, { method: "POST", body: JSON.stringify(body) }) }

// ── Helpers ─────────────────────────────────────────────────────────────

function Badge({ status }) {
  const c = { running: "#16a34a", healthy: "#16a34a", completed: "#16a34a", exited: "#dc2626", failed: "#dc2626", not_found: "#94a3b8", restarting: "#eab308" }
  return <span style={s.badge(c[status] || "#94a3b8")}>{status}</span>
}

function fmt(n) { return n != null ? Number(n).toLocaleString() : "—" }

// ── Nav sections ────────────────────────────────────────────────────────

const NAV = [
  { section: "Test Runs" },
  { id: "testrun", label: "Active Test", dot: "#dc2626", tip: "Start, stop, and manage named test runs" },
  { id: "history", label: "Test History", dot: "#f59e0b", tip: "Past tests with before/after comparisons" },
  { section: "Stress Test" },
  { id: "target", label: "Database Target", dot: "#8b5cf6", tip: "Configure PG host, credentials, intensity, import dumps" },
  { id: "operations", label: "Data Operations", dot: "#f59e0b", tip: "Inject rows, bulk update, simulate table growth" },
  { id: "connections", label: "Connections", dot: "#3b82f6", tip: "Connection pressure, growth ladder, load generators" },
  { section: "Introspection" },
  { id: "schema", label: "Schema & ORM", dot: "#8b5cf6", tip: "Auto-discovered tables, FK chains, SQLAlchemy classes" },
  { section: "Analysis" },
  { id: "analysis", label: "AI Analyzer", dot: "#10b981", tip: "Send diagnostics to Claude for tuning advice" },
  { id: "reports", label: "Reports", dot: "#10b981", tip: "Saved AI analysis and ladder results" },
]

// ── Page ────────────────────────────────────────────────────────────────

export default function Home() {
  const [status, setStatus] = useState(null)
  const [jobs, setJobs] = useState([])
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState({})
  const [report, setReport] = useState(null)
  const [reportsList, setReportsList] = useState([])
  const [activeNav, setActiveNav] = useState("target")
  const [flushConfirm, setFlushConfirm] = useState("")
  const [flushResult, setFlushResult] = useState(null)
  const [activeTest, setActiveTest] = useState(null)
  const [testHistory, setTestHistory] = useState([])
  const [newTestName, setNewTestName] = useState("")
  const [newTestIntensity, setNewTestIntensity] = useState("medium")
  const [newTestDump, setNewTestDump] = useState("")
  const [resetOnStart, setResetOnStart] = useState(true)

  const [f, setF] = useState({
    injectTable: "orders", injectRows: 1000000,
    updateTable: "orders", updateSet: "status='archived'", updateWhere: "placed_at < now() - interval '1 year'", updateBatch: 100000,
    connCount: 50, connDuration: 300, connMode: "mixed",
    ladderSteps: "10,25,50,100,200", ladderDuration: 180, ladderMode: "mixed",
    analyzeFocus: "",
  })
  const set = (k, v) => setF(p => ({ ...p, [k]: v }))

  const log = useCallback((msg) => setLogs(p => [...p.slice(-30), `[${new Date().toLocaleTimeString()}] ${msg}`]), [])

  const refresh = useCallback(async () => {
    try {
      const [st, jb] = await Promise.all([api("/status"), api("/jobs")])
      setStatus(st)
      setJobs(jb)
    } catch {}
  }, [])

  useEffect(() => { refresh(); const i = setInterval(refresh, 5000); return () => clearInterval(i) }, [refresh])

  const act = async (key, fn) => {
    setLoading(p => ({ ...p, [key]: true }))
    try {
      const r = await fn()
      log(`${key}: ${JSON.stringify(r).slice(0, 200)}`)
      refresh()
      return r
    } catch (e) { log(`${key} ERROR: ${e.message}`) }
    finally { setLoading(p => ({ ...p, [key]: false })) }
  }

  const [config, setConfig] = useState(null)
  const [ormSchema, setOrmSchema] = useState(null)

  const ORM_API = typeof window !== "undefined"
    ? `${window.location.protocol}//${window.location.hostname}:9091`
    : "http://localhost:9091"

  const tables = status?.tables ? Object.keys(status.tables).sort() : []
  const db = status?.database || {}
  const svcs = status?.services || {}

  useEffect(() => { api("/config").then(setConfig).catch(() => {}) }, [])
  useEffect(() => {
    fetch(`${ORM_API}/schema`).then(r => r.json()).then(setOrmSchema).catch(() => {})
    api("/tests/active").then(setActiveTest).catch(() => {})
    api("/tests").then(setTestHistory).catch(() => {})
  }, [])

  const currentIntensity = config?.intensity?.current || "medium"

  const scrollTo = (id) => {
    setActiveNav(id)
    document.getElementById(`section-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" })
  }

  return (
    <div style={s.layout}>

      {/* ═══ Left Sidebar ══════════════════════════════════════════════ */}
      <nav style={s.sidebar}>
        <div style={s.sidebarLogo}>Burnside Project</div>
        <div style={s.sidebarSub}>pg-stress</div>

        {NAV.map((item, i) =>
          item.section ? (
            <div key={i} style={s.navSection}>{item.section}</div>
          ) : (
            <div key={item.id} style={s.navItem(activeNav === item.id)} onClick={() => scrollTo(item.id)} title={item.tip}>
              <div style={s.navDot(item.dot)} />
              <div>
                <div>{item.label}</div>
                {item.tip && <div style={{ fontSize: 9, color: "#94a3b8", fontWeight: 400, lineHeight: 1.2, marginTop: 1 }}>{item.tip}</div>}
              </div>
            </div>
          )
        )}

        {/* Burnside Project */}
        <div style={s.navSection}>Burnside Project</div>
        <a href={typeof window !== "undefined" ? `${window.location.protocol}//${window.location.hostname}:8200` : "#"} target="_blank" style={{ ...s.navItem(false), textDecoration: "none" }}>
          <div style={s.navDot("#3b82f6")} />
          <div>Metrics Dashboard<div style={{ fontSize: 9, color: "#94a3b8", fontWeight: 400 }}>Real-time charts and table stats</div></div>
        </a>
        <a href="https://github.com/burnside-project/pg-collector" target="_blank" style={{ ...s.navItem(false), textDecoration: "none" }}>
          <div style={s.navDot("#10b981")} />
          <div>pg-collector<div style={{ fontSize: 9, color: "#94a3b8", fontWeight: 400 }}>Production telemetry agent</div></div>
        </a>
        <a href="https://github.com/burnside-project/pg-stress" target="_blank" style={{ ...s.navItem(false), textDecoration: "none" }}>
          <div style={s.navDot("#64748b")} />
          <div>Documentation<div style={{ fontSize: 9, color: "#94a3b8", fontWeight: 400 }}>GitHub docs and runbook</div></div>
        </a>

        <div style={s.sidebarFooter}>
          Test Like a Machine
        </div>
      </nav>

      {/* ═══ Main Content ══════════════════════════════════════════════ */}
      <main style={s.main}>

        {/* Safety Banner */}
        <div style={{
          background: "#fef3c7", border: "2px solid #f59e0b", borderRadius: 8, padding: "12px 20px",
          marginBottom: 16, display: "flex", alignItems: "center", gap: 12,
        }}>
          <div style={{ fontSize: 24 }}>&#9888;</div>
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, color: "#92400e" }}>TEST ENVIRONMENT — Isolated Database</div>
            <div style={{ fontSize: 11, color: "#92400e" }}>
              Target: <strong>{config?.database?.host || "?"}:{config?.database?.port || "?"} / {config?.database?.database || "?"}</strong> — This is a disposable test database running in a Docker container. All operations (inject, bulk update, chaos) write directly to this database. Not connected to production.
            </div>
          </div>
        </div>

        {/* Console Header */}
        <div style={{ display: "flex", alignItems: "center", marginBottom: 16 }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 700, color: "#1e293b" }}>Control Panel</div>
            <div style={{ fontSize: 12, color: "#94a3b8" }}>Stress test orchestration — intensity, WHAT IF scenarios, AI analysis</div>
          </div>
        </div>

        {/* ═══ SECTION: Active Test Run ═══════════════════════════════ */}
        <div id="section-testrun" style={s.section}>
          <div style={s.sectionHead}>
            <span style={s.sectionTitle}>Test Run</span>
            <span style={s.sectionSub}>— Named test runs with baseline reset and before/after tracking</span>
          </div>

          {activeTest && activeTest.status === "running" ? (
            /* Active test banner */
            <div style={{ background: "#f0fdf4", border: "2px solid #16a34a", borderRadius: 8, padding: 20, marginBottom: 16 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
                <div style={{ width: 12, height: 12, borderRadius: "50%", background: "#16a34a", animation: "pulse 2s infinite" }} />
                <div style={{ fontSize: 18, fontWeight: 700, color: "#166534" }}>{activeTest.name}</div>
                <Badge status="running" />
                <div style={{ flex: 1 }} />
                <span style={{ fontSize: 12, color: "#16a34a", fontWeight: 600 }}>{activeTest.intensity?.toUpperCase()}</span>
              </div>
              <div style={{ fontSize: 12, color: "#166534", marginBottom: 8 }}>
                Started: {activeTest.started_at?.split("T")[0]} {activeTest.started_at?.split("T")[1]?.split(".")[0]}
                {activeTest.db_before && ` — Baseline: ${activeTest.db_before.total_rows?.toLocaleString() || "?"} rows (${activeTest.db_before.db_size || "?"})`}
              </div>
              {activeTest.db_before?.tables && (
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
                  {Object.entries(activeTest.db_before.tables).slice(0, 6).map(([t, info]) => (
                    <span key={t} style={{ background: "#dcfce7", padding: "2px 8px", borderRadius: 4, fontSize: 10, color: "#166534" }}>
                      {t}: {info.rows?.toLocaleString()}
                    </span>
                  ))}
                </div>
              )}
              <button style={{ ...s.btn, ...s.btnRed }} disabled={loading.stopTest}
                onClick={async () => {
                  await act("stopTest", () => post("/tests/stop", {}))
                  const [at, th] = await Promise.all([api("/tests/active"), api("/tests")])
                  setActiveTest(at); setTestHistory(th)
                }}>
                {loading.stopTest ? "Stopping..." : "Stop & Save Test"}
              </button>
            </div>
          ) : (
            /* New test form */
            <div style={s.grid}>
              <div style={s.card("#16a34a")}>
                <div style={s.cardTitle}>Start New Test</div>
                <div style={s.cardDesc}>Every test starts from a known baseline. The database is reset before each run.</div>
                <div style={s.gap}>
                  <label style={s.label}>Test Name</label>
                  <input style={s.input} value={newTestName} onChange={e => setNewTestName(e.target.value)}
                    placeholder="e.g., baseline-medium, after-btree-index, high-chaos" />
                </div>
                <div style={s.gap}>
                  <label style={s.label}>Intensity</label>
                  <div style={{ display: "flex", gap: 8 }}>
                    {["low", "medium", "high"].map(level => (
                      <button key={level} style={{
                        ...s.btn, flex: 1, padding: "10px 8px",
                        background: newTestIntensity === level ? (level === "low" ? "#dcfce7" : level === "medium" ? "#fef3c7" : "#fee2e2") : "#f8fafc",
                        border: newTestIntensity === level ? `2px solid ${level === "low" ? "#16a34a" : level === "medium" ? "#f59e0b" : "#dc2626"}` : "1px solid #e2e8f0",
                        color: newTestIntensity === level ? (level === "low" ? "#16a34a" : level === "medium" ? "#92400e" : "#dc2626") : "#94a3b8",
                      }} onClick={() => setNewTestIntensity(level)}>
                        {level.charAt(0).toUpperCase() + level.slice(1)}
                      </button>
                    ))}
                  </div>
                </div>
                <div style={s.gap}>
                  <label style={{ ...s.label, display: "flex", alignItems: "center", gap: 6 }}>
                    <input type="checkbox" checked={resetOnStart} onChange={e => setResetOnStart(e.target.checked)} />
                    Reset database to baseline before starting
                  </label>
                </div>
                {resetOnStart && (
                  <div style={s.gap}>
                    <label style={s.label}>Baseline dump path (on server)</label>
                    <input style={s.input} value={newTestDump} onChange={e => setNewTestDump(e.target.value)}
                      placeholder="/tmp/soak_test.dump" />
                  </div>
                )}
                <button style={{ ...s.btn, ...s.btnGreen, width: "100%", padding: "10px", marginTop: 8 }}
                  disabled={!newTestName || loading.startTest}
                  onClick={async () => {
                    await act("startTest", () => post("/tests/start", {
                      name: newTestName,
                      intensity: newTestIntensity,
                      baseline_dump: resetOnStart && newTestDump ? newTestDump : null,
                    }))
                    const [at, th] = await Promise.all([api("/tests/active"), api("/tests")])
                    setActiveTest(at); setTestHistory(th)
                    setNewTestName("")
                  }}>
                  {loading.startTest ? "Starting..." : `Start Test: "${newTestName || "..."}"`}
                </button>
              </div>

              <div style={s.card("#16a34a")}>
                <div style={s.cardTitle}>How It Works</div>
                <div style={{ fontSize: 12, color: "#334155", lineHeight: 1.6 }}>
                  <strong>1. Reset to baseline</strong> — Restore from your production dump so every test starts from the same known state.<br/><br/>
                  <strong>2. Run at intensity</strong> — ORM + SQL generators stress the database at Low, Medium, or High.<br/><br/>
                  <strong>3. Inject & observe</strong> — Use Data Operations to inject rows, bulk update. Watch metrics in real-time.<br/><br/>
                  <strong>4. Stop & save</strong> — Final DB state captured. Before/after comparison saved to history.<br/><br/>
                  <strong>5. Compare</strong> — View any past test, compare TPS, cache ratio, growth across runs.
                </div>
              </div>
            </div>
          )}
        </div>

        {/* ═══ SECTION: Test History ══════════════════════════════════ */}
        {testHistory.length > 0 && (
        <div id="section-history" style={s.section}>
          <div style={s.sectionHead}>
            <span style={s.sectionTitle}>Test History</span>
            <span style={s.sectionSub}>— Past test runs with before/after comparisons</span>
            <div style={{ flex: 1 }} />
            <button style={{ ...s.btn, ...s.btnGhost, fontSize: 11 }}
              onClick={async () => setTestHistory(await api("/tests"))}>Refresh</button>
          </div>
          <div style={{ overflow: "auto" }}>
            <table style={s.table}>
              <thead>
                <tr>
                  <th style={s.th}>Name</th>
                  <th style={s.th}>Intensity</th>
                  <th style={s.th}>Status</th>
                  <th style={s.th}>Started</th>
                  <th style={s.th}>Samples</th>
                  <th style={s.th}>Before</th>
                  <th style={s.th}>After</th>
                  <th style={s.th}>Delta</th>
                </tr>
              </thead>
              <tbody>
                {testHistory.map(t => {
                  const beforeRows = t.db_before?.total_rows || 0
                  const afterRows = t.db_after?.total_rows || 0
                  const delta = afterRows - beforeRows
                  return (
                    <tr key={t.id} style={{ background: t.status === "running" ? "#f0fdf4" : "" }}>
                      <td style={{ ...s.td, fontWeight: 600 }}>{t.name}</td>
                      <td style={s.td}><span style={{
                        background: t.intensity === "low" ? "#dcfce7" : t.intensity === "high" ? "#fee2e2" : "#fef3c7",
                        color: t.intensity === "low" ? "#166534" : t.intensity === "high" ? "#991b1b" : "#92400e",
                        padding: "1px 8px", borderRadius: 10, fontSize: 10, fontWeight: 600,
                      }}>{t.intensity}</span></td>
                      <td style={s.td}><Badge status={t.status} /></td>
                      <td style={{ ...s.td, fontSize: 11, color: "#64748b" }}>{t.started_at?.split("T")[0]}</td>
                      <td style={{ ...s.td, textAlign: "right" }}>{t.sample_count?.toLocaleString()}</td>
                      <td style={{ ...s.td, fontSize: 11 }}>{beforeRows ? `${beforeRows.toLocaleString()} rows` : "—"}</td>
                      <td style={{ ...s.td, fontSize: 11 }}>{afterRows ? `${afterRows.toLocaleString()} rows` : "—"}</td>
                      <td style={{ ...s.td, fontSize: 11, fontWeight: 600, color: delta > 0 ? "#16a34a" : delta < 0 ? "#dc2626" : "#94a3b8" }}>
                        {delta > 0 ? `+${delta.toLocaleString()}` : delta < 0 ? delta.toLocaleString() : "—"}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
        )}

        {/* Stats Bar */}
        <div style={s.topBar}>
          <div style={s.stat}><div style={s.statVal}>{db.db_size || "..."}</div><div style={s.statLbl}>Database</div></div>
          <div style={s.stat}><div style={s.statVal}>{db.connections ?? "..."}</div><div style={s.statLbl}>Connections</div></div>
          <div style={s.stat}><div style={s.statVal}>{tables.length}</div><div style={s.statLbl}>Tables</div></div>
          <div style={s.stat}><div style={s.statVal}>{jobs.filter(j => j.status === "running").length}</div><div style={s.statLbl}>Active Jobs</div></div>
          <div style={s.stat}><div style={s.statVal}>{status?.reports ?? 0}</div><div style={s.statLbl}>Reports</div></div>
        </div>

        {/* ═══ SECTION: Database Target & Intensity ═══════════════════ */}
        <div id="section-target" style={s.section}>
          <div style={s.sectionHead}>
            <span style={s.sectionTitle}>Database Target & Intensity</span>
            <span style={s.sectionSub}>— Which database, how hard to hit it</span>
          </div>
          <div style={s.grid}>
            <div style={s.card("#8b5cf6")}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                <div style={s.cardTitle}>Database Target</div>
                <span style={{ background: "#dc2626", color: "#fff", fontSize: 9, fontWeight: 700, padding: "2px 8px", borderRadius: 10, letterSpacing: 1 }}>TEST DB</span>
              </div>
              <div style={s.cardDesc}>Isolated PostgreSQL container — safe to stress, inject, and destroy.</div>
              <div style={{ background: "#eff6ff", border: "1px solid #bfdbfe", borderRadius: 6, padding: 12, marginBottom: 8 }}>
                <div style={{ fontSize: 16, fontWeight: 700, color: "#1e40af", marginBottom: 4 }}>
                  {config?.database?.host || "localhost"}:{config?.database?.port || 5434}
                </div>
                <div style={{ fontSize: 14, fontWeight: 600, color: "#1e40af" }}>
                  {config?.database?.database || "testdb"}
                </div>
                <div style={{ fontSize: 11, color: "#3b82f6", marginTop: 4 }}>
                  {db.db_size || "..."} — {tables.length} tables — {db.connections ?? "?"} connections
                </div>
              </div>
              <table style={s.table}>
                <tbody>
                  <tr><td style={{ ...s.td, color: "#64748b", width: 80, fontWeight: 500 }}>User</td><td style={s.td}>{config?.database?.user || "postgres"}</td></tr>
                </tbody>
              </table>
              <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 8 }}>Configured in .env (PG_HOST, PG_USER, PG_PASSWORD, PG_DATABASE)</div>
            </div>

            <div style={s.card("#8b5cf6")}>
              <div style={s.cardTitle}>Stress Intensity</div>
              <div style={s.cardDesc}>Controls burst connections, chaos probability, ORM concurrency, and pauses.</div>
              <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
                {[
                  { level: "low", label: "Low", color: "#16a34a", desc: "No chaos, 3-15 conns, long pauses" },
                  { level: "medium", label: "Medium", color: "#f59e0b", desc: "25% chaos, 5-50 conns, moderate" },
                  { level: "high", label: "High", color: "#ef4444", desc: "50% chaos, 15-80 conns, aggressive" },
                ].map(p => (
                  <button key={p.level}
                    style={{
                      ...s.btn, flex: 1, padding: "12px 8px", textAlign: "center",
                      background: currentIntensity === p.level ? p.color + "12" : "#fff",
                      border: currentIntensity === p.level ? `2px solid ${p.color}` : "1px solid #e2e8f0",
                      color: currentIntensity === p.level ? p.color : "#94a3b8",
                      borderRadius: 8,
                    }}
                    onClick={() => act(`intensity-${p.level}`, async () => {
                      const r = await post("/config/intensity", { level: p.level })
                      setConfig(await api("/config"))
                      return r
                    })}
                  >
                    <div style={{ fontSize: 14, fontWeight: 700 }}>{p.label}</div>
                    <div style={{ fontSize: 10, marginTop: 4, opacity: 0.7 }}>{p.desc}</div>
                  </button>
                ))}
              </div>
              <div style={{ fontSize: 11, color: "#94a3b8" }}>
                {currentIntensity === "low" && "Safe for small databases and BYOD validation."}
                {currentIntensity === "medium" && "Good baseline. 25% chaos, moderate burst intensity."}
                {currentIntensity === "high" && "Designed to find breaking points. May cause deadlocks."}
                {" "}Restart generators after changing.
              </div>
            </div>

            <div style={s.card("#8b5cf6")}>
              <div style={s.cardTitle}>BYOD Import</div>
              <div style={s.cardDesc}>Restore a pg_dump file from your production database.</div>
              <div style={s.gap}>
                <label style={s.label}>Dump file path (on server)</label>
                <input style={s.input} id="dump-path" defaultValue="/tmp/production.dump" />
              </div>
              <button style={{ ...s.btn, ...s.btnBlue, ...s.btnFull }} disabled={loading.import}
                onClick={() => {
                  const path = document.getElementById("dump-path").value
                  act("import", () => post("/import", { dump_path: path }))
                }}>
                {loading.import ? "Importing..." : "Restore Dump"}
              </button>
              <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 8 }}>
                Upload dump to server first: scp production.dump server:/tmp/
              </div>
            </div>
          </div>
        </div>

        {/* ═══ SECTION: Operations ════════════════════════════════════ */}
        <div id="section-operations" style={s.section}>
          <div style={s.sectionHead}>
            <span style={s.sectionTitle}>Data Operations</span>
            <span style={s.sectionSub}>— Inject rows, bulk update, simulate table growth</span>
          </div>
          <div style={s.grid}>
            <div style={s.card("#f59e0b")}>
              <div style={s.cardTitle}>Inject Rows</div>
              <div style={s.cardDesc}>Simulate table growth. "What if orders grows by 5M rows?"</div>
              <div style={s.gap}>
                <label style={s.label}>Target Table</label>
                <select style={s.select} value={f.injectTable} onChange={e => set("injectTable", e.target.value)}>
                  {tables.map(t => <option key={t}>{t}</option>)}
                </select>
              </div>
              <div style={s.gap}>
                <label style={s.label}>Number of Rows</label>
                <input style={s.input} type="number" value={f.injectRows} onChange={e => set("injectRows", +e.target.value)} />
              </div>
              <button style={{ ...s.btn, ...s.btnBlue, ...s.btnFull }} disabled={loading.inject}
                onClick={() => act("inject", () => post("/inject", { table: f.injectTable, rows: f.injectRows }))}>
                {loading.inject ? "Injecting..." : `Inject ${fmt(f.injectRows)} rows into ${f.injectTable}`}
              </button>
            </div>

            <div style={s.card("#f59e0b")}>
              <div style={s.cardTitle}>Bulk Update</div>
              <div style={s.cardDesc}>Mass UPDATE in batches. "What if we archive old orders?"</div>
              <div style={s.gap}>
                <label style={s.label}>Table</label>
                <select style={s.select} value={f.updateTable} onChange={e => set("updateTable", e.target.value)}>
                  {tables.map(t => <option key={t}>{t}</option>)}
                </select>
              </div>
              <div style={s.gap}>
                <label style={s.label}>SET clause</label>
                <input style={s.input} value={f.updateSet} onChange={e => set("updateSet", e.target.value)} />
              </div>
              <div style={s.gap}>
                <label style={s.label}>WHERE clause</label>
                <input style={s.input} value={f.updateWhere} onChange={e => set("updateWhere", e.target.value)} />
              </div>
              <div style={s.gap}>
                <label style={s.label}>Batch Size</label>
                <input style={s.input} type="number" value={f.updateBatch} onChange={e => set("updateBatch", +e.target.value)} />
              </div>
              <button style={{ ...s.btn, ...s.btnBlue, ...s.btnFull }} disabled={loading.update}
                onClick={() => act("update", () => post("/bulk-update", { table: f.updateTable, set_clause: f.updateSet, where_clause: f.updateWhere || null, batch_size: f.updateBatch }))}>
                {loading.update ? "Updating..." : "Run Bulk Update"}
              </button>
            </div>

            <div style={s.card("#f59e0b")}>
              <div style={s.cardTitle}>Table Stats</div>
              <div style={s.cardDesc}>Current row counts, dead tuples, and sizes.</div>
              <div style={{ maxHeight: 280, overflow: "auto" }}>
                <table style={s.table}>
                  <thead><tr><th style={s.th}>Table</th><th style={{ ...s.th, textAlign: "right" }}>Rows</th><th style={{ ...s.th, textAlign: "right" }}>Dead</th><th style={{ ...s.th, textAlign: "right" }}>Size</th></tr></thead>
                  <tbody>
                    {tables.map(t => {
                      const d = status.tables[t]
                      return (<tr key={t}>
                        <td style={s.td}>{t}</td>
                        <td style={{ ...s.td, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{fmt(d.n_live_tup)}</td>
                        <td style={{ ...s.td, textAlign: "right", color: d.n_dead_tup > 10000 ? "#dc2626" : "#94a3b8" }}>{fmt(d.n_dead_tup)}</td>
                        <td style={{ ...s.td, textAlign: "right", color: "#64748b" }}>{d.size}</td>
                      </tr>)
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>

        {/* ═══ SECTION: Connections ═══════════════════════════════════ */}
        <div id="section-connections" style={s.section}>
          <div style={s.sectionHead}>
            <span style={s.sectionTitle}>Transactions & Connections</span>
            <span style={s.sectionSub}>— Stress concurrency, find breaking points, load generators</span>
          </div>
          <div style={s.grid}>
            <div style={s.card("#3b82f6")}>
              <div style={s.cardTitle}>Connection Pressure</div>
              <div style={s.cardDesc}>Open N concurrent connections and sustain for duration.</div>
              <div style={s.row}>
                <div style={{ flex: 1 }}><label style={s.label}>Connections</label><input style={s.input} type="number" value={f.connCount} onChange={e => set("connCount", +e.target.value)} /></div>
                <div style={{ flex: 1 }}><label style={s.label}>Duration (sec)</label><input style={s.input} type="number" value={f.connDuration} onChange={e => set("connDuration", +e.target.value)} /></div>
                <div style={{ flex: 1 }}><label style={s.label}>Mode</label>
                  <select style={s.select} value={f.connMode} onChange={e => set("connMode", e.target.value)}>
                    <option value="mixed">Mixed (R+W)</option><option value="readonly">Read Only</option><option value="tpcb">TPC-B (Write)</option>
                  </select>
                </div>
              </div>
              <button style={{ ...s.btn, ...s.btnBlue, ...s.btnFull }} disabled={loading.conn}
                onClick={() => act("conn", () => post("/connections", { connections: f.connCount, duration: f.connDuration, mode: f.connMode }))}>
                {loading.conn ? "Running..." : `Stress ${f.connCount} connections × ${f.connDuration}s`}
              </button>
            </div>

            <div style={s.card("#3b82f6")}>
              <div style={s.cardTitle}>Growth Ladder</div>
              <div style={s.cardDesc}>Ramp connections step-by-step to find the breaking point.</div>
              <div style={s.gap}><label style={s.label}>Steps (connection counts, comma-separated)</label><input style={s.input} value={f.ladderSteps} onChange={e => set("ladderSteps", e.target.value)} /></div>
              <div style={s.row}>
                <div style={{ flex: 1 }}><label style={s.label}>Seconds per step</label><input style={s.input} type="number" value={f.ladderDuration} onChange={e => set("ladderDuration", +e.target.value)} /></div>
                <div style={{ flex: 1 }}><label style={s.label}>Mode</label>
                  <select style={s.select} value={f.ladderMode} onChange={e => set("ladderMode", e.target.value)}>
                    <option value="mixed">Mixed</option><option value="readonly">Read Only</option><option value="tpcb">TPC-B</option>
                  </select>
                </div>
              </div>
              {(() => { const steps = f.ladderSteps.split(",").filter(Boolean); return (
                <button style={{ ...s.btn, ...s.btnBlue, ...s.btnFull }} disabled={loading.ladder}
                  onClick={() => act("ladder", () => post("/ladder", { steps: steps.map(Number), phase_duration: f.ladderDuration, mode: f.ladderMode }))}>
                  {loading.ladder ? "Running..." : `Run ${steps.length} phases (~${Math.round(steps.length * f.ladderDuration / 60)} min)`}
                </button>
              )})()}
            </div>

            <div style={s.card("#3b82f6")}>
              <div style={s.cardTitle}>Load Generators</div>
              <div style={s.cardDesc}>Start additional workload sources alongside the raw SQL generator.</div>
              <table style={s.table}>
                <thead><tr><th style={s.th}>Generator</th><th style={s.th}>Status</th><th style={s.th}></th></tr></thead>
                <tbody>
                  <tr>
                    <td style={s.td}>Raw SQL (Go)<br/><span style={{ fontSize: 10, color: "#94a3b8" }}>25+ OLTP operations + chaos</span></td>
                    <td style={s.td}><Badge status={svcs["load-generator"]?.status || "not_found"} /></td>
                    <td style={s.td}><span style={{ fontSize: 11, color: "#94a3b8" }}>always on</span></td>
                  </tr>
                  {[
                    { key: "orm", name: "ORM (SQLAlchemy)", svc: "load-generator-orm", desc: "N+1, eager load, EXISTS, bulk INSERT" },
                    { key: "pgbench", name: "pgbench", svc: "pgbench-runner", desc: "TPC-B + custom e-commerce scripts" },
                  ].map(g => (
                    <tr key={g.key}>
                      <td style={s.td}>{g.name}<br/><span style={{ fontSize: 10, color: "#94a3b8" }}>{g.desc}</span></td>
                      <td style={s.td}><Badge status={svcs[g.svc]?.status || "not_found"} /></td>
                      <td style={s.td}>
                        {svcs[g.svc]?.status === "running"
                          ? <button style={{ ...s.btn, ...s.btnRed, fontSize: 11, padding: "4px 12px" }} onClick={() => act(`stop-${g.key}`, () => post(`/generators/${g.key}/stop`))}>Stop</button>
                          : <button style={{ ...s.btn, ...s.btnGreen, fontSize: 11, padding: "4px 12px" }} onClick={() => act(`start-${g.key}`, () => post(`/generators/${g.key}/start`))}>Start</button>
                        }
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* ═══ SECTION: Schema Introspection & ORM ═══════════════════ */}
        {ormSchema && (
        <div id="section-schema" style={s.section}>
          <div style={s.sectionHead}>
            <span style={s.sectionTitle}>Schema Introspection & ORM</span>
            <span style={s.sectionSub}>— SQLAlchemy auto-discovered classes, FK chains, table classification</span>
          </div>
          <div style={s.grid}>
            <div style={s.card("#8b5cf6")}>
              <div style={s.cardTitle}>Table Classification</div>
              <div style={s.cardDesc}>How pg-stress categorized your {ormSchema.total_tables} tables ({ormSchema.total_size}).</div>
              <table style={s.table}>
                <tbody>
                  {Object.entries(ormSchema.classification || {}).map(([role, tbls]) => (
                    <tr key={role}><td style={{ ...s.td, color: "#64748b", width: 120, textTransform: "capitalize", fontWeight: 500 }}>{role.replace("_", " ")}</td><td style={{ ...s.td, fontSize: 12 }}>{tbls.length > 0 ? tbls.join(", ") : "—"}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div style={s.card("#8b5cf6")}>
              <div style={s.cardTitle}>ORM Operations</div>
              <div style={s.cardDesc}>Which tables are eligible for each operation type.</div>
              <table style={s.table}>
                <tbody>
                  <tr><td style={{ ...s.td, color: "#64748b", width: 100, fontWeight: 500 }}>Queryable</td><td style={{ ...s.td, fontSize: 12 }}>{(ormSchema.operations?.queryable || []).join(", ") || "—"}</td></tr>
                  <tr><td style={{ ...s.td, color: "#64748b", fontWeight: 500 }}>Insertable</td><td style={{ ...s.td, fontSize: 12 }}>{(ormSchema.operations?.insertable || []).join(", ") || "—"}</td></tr>
                  <tr><td style={{ ...s.td, color: "#64748b", fontWeight: 500 }}>Updatable</td><td style={{ ...s.td, fontSize: 12 }}>{(ormSchema.operations?.updatable || []).join(", ") || "—"}</td></tr>
                  <tr><td style={{ ...s.td, color: "#64748b", fontWeight: 500 }}>Paginable</td><td style={{ ...s.td, fontSize: 12 }}>{(ormSchema.operations?.paginable || []).join(", ") || "—"}</td></tr>
                </tbody>
              </table>
              <div style={{ marginTop: 12 }}>
                <div style={{ fontSize: 11, color: "#94a3b8", marginBottom: 4, fontWeight: 500 }}>Pattern Mix Weights</div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {Object.entries(ormSchema.mix_weights || {}).map(([k, v]) => (
                    <span key={k} style={{ background: "#f5f3ff", padding: "2px 8px", borderRadius: 4, fontSize: 11, color: "#7c3aed", border: "1px solid #ede9fe" }}>{k}: {v}%</span>
                  ))}
                </div>
              </div>
            </div>

            <div style={s.card("#8b5cf6")}>
              <div style={s.cardTitle}>FK Relationships ({(ormSchema.relationships || []).length})</div>
              <div style={s.cardDesc}>Foreign key graph discovered from your schema.</div>
              <table style={s.table}>
                <thead><tr><th style={s.th}>Parent</th><th style={s.th}>Child</th><th style={s.th}>FK Column</th></tr></thead>
                <tbody>
                  {(ormSchema.relationships || []).map((r, i) => (
                    <tr key={i}><td style={s.td}>{r.parent}</td><td style={s.td}>{r.child}</td><td style={{ ...s.td, color: "#64748b" }}>{r.via}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div style={s.card("#8b5cf6")}>
              <div style={s.cardTitle}>FK Chains ({(ormSchema.fk_chains || []).length})</div>
              <div style={s.cardDesc}>Multi-hop chains that drive N+1 and eager load patterns.</div>
              <div style={{ maxHeight: 300, overflow: "auto" }}>
                {(ormSchema.fk_chains || []).map((c, i) => (
                  <div key={i} style={{ padding: "4px 0", borderBottom: "1px solid #f1f5f9", fontSize: 12 }}>
                    <span style={{ color: "#94a3b8", marginRight: 8 }}>depth {c.depth}</span>
                    {c.tables.join(" → ")}
                  </div>
                ))}
              </div>
            </div>

            <div style={{ ...s.card("#8b5cf6"), gridColumn: "1 / -1" }}>
              <div style={s.cardTitle}>SQLAlchemy ORM Classes ({Object.keys(ormSchema.orm_classes || {}).length})</div>
              <div style={s.cardDesc}>Auto-generated via automap_base() — no models to write.</div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(350px, 1fr))", gap: 12, marginTop: 8 }}>
                {Object.entries(ormSchema.orm_classes || {}).map(([name, info]) => (
                  <div key={name} style={{ background: "#f8fafc", borderRadius: 6, padding: 12, border: "1px solid #e2e8f0" }}>
                    <div style={{ fontWeight: 600, color: "#7c3aed", fontSize: 13, marginBottom: 4 }}>{name}</div>
                    <div style={{ fontSize: 11, color: "#94a3b8", marginBottom: 4 }}>
                      Columns: <span style={{ color: "#64748b" }}>{info.columns.join(", ")}</span>
                    </div>
                    {info.relationships.length > 0 && (
                      <div style={{ fontSize: 11, color: "#94a3b8" }}>
                        Relationships: {info.relationships.map((r, i) => (
                          <span key={i} style={{ color: "#16a34a", marginLeft: 4 }}>{r.name} → {r.target} ({r.direction})</span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
        )}

        {/* ═══ SECTION: Analysis & Reports ═══════════════════════════ */}
        <div id="section-analysis" style={s.section}>
          <div style={s.sectionHead}>
            <span style={s.sectionTitle}>AI Analyzer</span>
            <span style={s.sectionSub}>— Claude-powered tuning advice, capacity predictions</span>
          </div>
          <div style={s.grid}>
            <div style={s.card("#10b981")}>
              <div style={s.cardTitle}>Run Analysis</div>
              <div style={s.cardDesc}>Send PostgreSQL diagnostics to Claude for tuning advice and predictions.</div>
              <div style={s.gap}>
                <label style={s.label}>Analysis Focus</label>
                <select style={s.select} value={f.analyzeFocus} onChange={e => set("analyzeFocus", e.target.value)}>
                  <option value="">Full Analysis — health score, queries, tuning, capacity</option>
                  <option value="tuning">Tuning — PostgreSQL parameter recommendations</option>
                  <option value="queries">Queries — N+1 detection, slow query fixes, index suggestions</option>
                  <option value="capacity">Capacity — growth projections, breaking points, scaling</option>
                </select>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button style={{ ...s.btn, ...s.btnGreen, flex: 1 }} disabled={loading.analyze}
                  onClick={() => act("analyze", () => post("/analyze", { focus: f.analyzeFocus || null }))}>
                  {loading.analyze ? "Analyzing..." : "Run Analysis"}
                </button>
                <button style={{ ...s.btn, ...s.btnGhost, flex: 1 }}
                  onClick={async () => { try { setReport(await api("/analyze/latest")) } catch { setReport({ error: "No reports yet" }) } }}>
                  View Latest
                </button>
              </div>
            </div>

            <div id="section-jobs" style={{ ...s.card("#10b981"), gridColumn: "1 / -1" }}>
              <div style={s.cardTitle}>Background Jobs</div>
              <div style={s.cardDesc}>Live progress for inject, bulk update, ladder, and analysis operations.</div>
              {jobs.length === 0 ? (
                <p style={{ fontSize: 12, color: "#94a3b8" }}>No jobs yet. Run an operation above.</p>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {[...jobs].reverse().slice(0, 10).map(j => (
                    <div key={j.id} style={{
                      background: j.status === "running" ? "#f0fdf4" : j.status === "failed" ? "#fef2f2" : "#f8fafc",
                      border: `1px solid ${j.status === "running" ? "#bbf7d0" : j.status === "failed" ? "#fecaca" : "#e2e8f0"}`,
                      borderRadius: 6, padding: 12,
                    }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                        <Badge status={j.status} />
                        <span style={{ fontSize: 12, fontWeight: 600, color: "#1e293b" }}>{j.type}</span>
                        <span style={{ fontSize: 10, color: "#94a3b8", fontFamily: "monospace" }}>{j.id}</span>
                        <div style={{ flex: 1 }} />
                        <span style={{ fontSize: 11, color: "#64748b" }}>{j.elapsed_s}s elapsed</span>
                      </div>
                      {/* Progress bar */}
                      {j.status === "running" && (
                        <div style={{ background: "#e2e8f0", borderRadius: 3, height: 6, marginBottom: 6 }}>
                          <div style={{ background: "#16a34a", borderRadius: 3, height: 6, width: `${j.progress || 0}%`, transition: "width 0.5s" }} />
                        </div>
                      )}
                      <div style={{ fontSize: 11, color: "#64748b" }}>{j.progress_msg || ""}</div>
                      {/* Before / After */}
                      {(j.before || j.after) && (
                        <div style={{ display: "flex", gap: 16, marginTop: 6, fontSize: 11 }}>
                          {j.before && <div><span style={{ color: "#94a3b8" }}>Before:</span> <span style={{ color: "#1e293b", fontWeight: 500 }}>{typeof j.before.rows === "number" ? j.before.rows.toLocaleString() : JSON.stringify(j.before)} rows</span> {j.before.size && <span style={{ color: "#94a3b8" }}>({j.before.size})</span>}</div>}
                          {j.after && <div><span style={{ color: "#94a3b8" }}>After:</span> <span style={{ color: "#1e293b", fontWeight: 500 }}>{typeof j.after.rows === "number" ? j.after.rows.toLocaleString() : JSON.stringify(j.after)} rows</span> {j.after.size && <span style={{ color: "#94a3b8" }}>({j.after.size})</span>}</div>}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

          </div>
        </div>

        {/* ═══ SECTION: Reports ══════════════════════════════════════ */}
        <div id="section-reports" style={s.section}>
          <div style={s.sectionHead}>
            <span style={s.sectionTitle}>Reports</span>
            <span style={s.sectionSub}>— Saved AI analysis, ladder results, downloadable reports</span>
          </div>
          <div style={s.grid}>
            <div style={s.card("#10b981")}>
              <div style={s.cardTitle}>Saved Reports</div>
              <div style={s.cardDesc}>Reports are saved to the server at <code style={{ background: "#f1f5f9", padding: "1px 6px", borderRadius: 3, fontSize: 11 }}>REPORTS_DIR</code> (default: <code style={{ background: "#f1f5f9", padding: "1px 6px", borderRadius: 3, fontSize: 11 }}>/app/reports</code>). Configure in .env.</div>
              <button style={{ ...s.btn, ...s.btnGhost, ...s.btnFull, marginBottom: 12 }}
                onClick={async () => { try { setReportsList(await api("/reports")) } catch {} }}>
                Refresh Reports
              </button>
              {reportsList.length > 0 ? (
                <div style={{ maxHeight: 300, overflow: "auto" }}>
                  <table style={s.table}>
                    <thead><tr><th style={s.th}>Type</th><th style={s.th}>Focus</th><th style={s.th}>Created</th><th style={s.th}>Links</th></tr></thead>
                    <tbody>
                      {reportsList.map(r => (
                        <tr key={r.id}>
                          <td style={s.td}>{r.type}</td>
                          <td style={s.td}>{r.focus || "full"}</td>
                          <td style={{ ...s.td, fontSize: 11, color: "#64748b" }}>{r.created_at?.split("T")[0]} {r.created_at?.split("T")[1]?.split(".")[0]}</td>
                          <td style={s.td}>
                            <a href={`${API}/reports/${r.file}`} target="_blank" style={{ color: "#2563eb", fontSize: 11, marginRight: 8 }}>JSON</a>
                            <a href={`${API}/reports/${r.file.replace(".json", ".md")}`} target="_blank" style={{ color: "#2563eb", fontSize: 11 }}>Markdown</a>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p style={{ fontSize: 12, color: "#94a3b8" }}>No reports yet. Run AI analysis or a growth ladder to generate one.</p>
              )}
            </div>

            <div style={s.card("#10b981")}>
              <div style={s.cardTitle}>Report Viewer</div>
              <div style={s.cardDesc}>Click a report to view inline, or use the links to download.</div>
              {reportsList.length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {reportsList.slice(0, 5).map(r => (
                    <button key={r.id} style={{ ...s.btn, ...s.btnGhost, textAlign: "left", fontSize: 12 }}
                      onClick={async () => { try { setReport(await api(`/reports/${r.file}`)) } catch {} }}>
                      {r.type} — {r.focus || "full"} ({r.created_at?.split("T")[0]})
                    </button>
                  ))}
                </div>
              )}
              {!reportsList.length && (
                <button style={{ ...s.btn, ...s.btnGhost, ...s.btnFull }}
                  onClick={async () => { try { setReport(await api("/analyze/latest")) } catch { setReport({ error: "No reports yet" }) } }}>
                  View Latest Analysis
                </button>
              )}
            </div>
          </div>

          {report && (
            <div style={{ ...s.card("#10b981"), marginTop: 16 }}>
              <div style={{ display: "flex", alignItems: "center", marginBottom: 8 }}>
                <div style={s.cardTitle}>Report</div>
                <div style={{ flex: 1 }} />
                <button style={{ ...s.btn, ...s.btnGhost }} onClick={() => setReport(null)}>Close</button>
              </div>
              <div style={s.mono}>
                {typeof report === "string" ? report
                  : report.analysis ? report.analysis
                  : JSON.stringify(report, null, 2)}
              </div>
            </div>
          )}
        </div>

        {/* ═══ SECTION: Data Management ═════════════════════════════ */}
        <div style={s.section}>
          <div style={s.sectionHead}>
            <span style={s.sectionTitle}>Data Management</span>
            <span style={s.sectionSub}>— Flush metrics, reports, and job history</span>
          </div>
          <div style={s.grid}>
            <div style={s.card("#dc2626")}>
              <div style={s.cardTitle}>Flush Data</div>
              <div style={s.cardDesc}>Permanently delete all collected metrics, reports, and job history. This cannot be undone.</div>
              <div style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 6, padding: 12, marginBottom: 12 }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: "#dc2626", marginBottom: 6 }}>I understand the implications</div>
                <div style={{ fontSize: 11, color: "#64748b", marginBottom: 8 }}>This will permanently delete all dashboard metrics (SQLite), saved AI analysis reports, ladder results, and job history.</div>
                <label style={s.label}>Type <strong>DELETE ALL DATA</strong> to confirm</label>
                <input style={{ ...s.input, borderColor: flushConfirm === "DELETE ALL DATA" ? "#16a34a" : "#e2e8f0" }}
                  value={flushConfirm} onChange={e => setFlushConfirm(e.target.value)}
                  placeholder="DELETE ALL DATA" />
              </div>
              <button style={{ ...s.btn, width: "100%", background: flushConfirm === "DELETE ALL DATA" ? "#dc2626" : "#e2e8f0", color: flushConfirm === "DELETE ALL DATA" ? "#fff" : "#94a3b8", cursor: flushConfirm === "DELETE ALL DATA" ? "pointer" : "not-allowed" }}
                disabled={flushConfirm !== "DELETE ALL DATA" || loading.flush}
                onClick={async () => {
                  const r = await act("flush", () => post("/flush", { confirmation: flushConfirm, target: "all" }))
                  setFlushResult(r)
                  setFlushConfirm("")
                  setReportsList([])
                }}>
                {loading.flush ? "Flushing..." : "Flush All Data"}
              </button>
              {flushResult && (
                <div style={{ marginTop: 8, fontSize: 11, color: "#16a34a", background: "#f0fdf4", padding: 8, borderRadius: 4 }}>
                  Flushed: {JSON.stringify(flushResult.result || flushResult)}
                </div>
              )}
            </div>

            <div style={s.card("#64748b")}>
              <div style={s.cardTitle}>Storage Info</div>
              <div style={s.cardDesc}>Where pg-stress stores data.</div>
              <table style={s.table}>
                <tbody>
                  <tr><td style={{ ...s.td, color: "#64748b", fontWeight: 500, width: 120 }}>Metrics</td><td style={s.td}>SQLite — <code style={{ fontSize: 10, background: "#f1f5f9", padding: "1px 4px", borderRadius: 2 }}>dashboard-data:/data/metrics.db</code></td></tr>
                  <tr><td style={{ ...s.td, color: "#64748b", fontWeight: 500 }}>Reports</td><td style={s.td}>JSON + MD — <code style={{ fontSize: 10, background: "#f1f5f9", padding: "1px 4px", borderRadius: 2 }}>control-plane-reports:/app/reports/</code></td></tr>
                  <tr><td style={{ ...s.td, color: "#64748b", fontWeight: 500 }}>PostgreSQL</td><td style={s.td}>PG files — <code style={{ fontSize: 10, background: "#f1f5f9", padding: "1px 4px", borderRadius: 2 }}>stress-pg-data</code></td></tr>
                </tbody>
              </table>
              <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 8 }}>
                <code style={{ fontSize: 10 }}>make stop</code> preserves data. <code style={{ fontSize: 10 }}>make down</code> removes volumes.
              </div>
            </div>
          </div>
        </div>

        {/* ═══ Activity Log ══════════════════════════════════════════ */}
        {logs.length > 0 && (
          <div style={s.section}>
            <div style={{ ...s.sectionHead, marginBottom: 12 }}>
              <span style={s.sectionTitle}>Activity Log</span>
              <div style={{ flex: 1 }} />
              <button style={{ ...s.btn, ...s.btnGhost, fontSize: 11 }} onClick={() => setLogs([])}>Clear</button>
            </div>
            <div style={s.mono}>{logs.join("\n")}</div>
          </div>
        )}

      </main>
    </div>
  )
}
