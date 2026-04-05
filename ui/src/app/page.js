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
  { section: "Stress Test" },
  { id: "target", label: "Database Target", dot: "#8b5cf6" },
  { id: "operations", label: "Data Operations", dot: "#f59e0b" },
  { id: "connections", label: "Connections", dot: "#3b82f6" },
  { section: "Introspection" },
  { id: "schema", label: "Schema & ORM", dot: "#8b5cf6" },
  { section: "Analysis" },
  { id: "analysis", label: "AI Analyzer", dot: "#10b981" },
  { id: "jobs", label: "Jobs & Reports", dot: "#10b981" },
]

// ── Page ────────────────────────────────────────────────────────────────

export default function Home() {
  const [status, setStatus] = useState(null)
  const [jobs, setJobs] = useState([])
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState({})
  const [report, setReport] = useState(null)
  const [activeNav, setActiveNav] = useState("target")

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
            <div key={item.id} style={s.navItem(activeNav === item.id)} onClick={() => scrollTo(item.id)}>
              <div style={s.navDot(item.dot)} />
              {item.label}
            </div>
          )
        )}

        {/* Services */}
        <div style={s.navSection}>Services</div>
        {Object.entries(svcs).filter(([,v]) => v.status === "running").map(([k]) => (
          <div key={k} style={{ ...s.navItem(false), fontSize: 12 }}>
            <div style={s.navDot("#16a34a")} />
            {k}
          </div>
        ))}

        <div style={s.sidebarFooter}>
          Test Like a Machine
        </div>
      </nav>

      {/* ═══ Main Content ══════════════════════════════════════════════ */}
      <main style={s.main}>

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
              <div style={s.cardTitle}>Database Target</div>
              <div style={s.cardDesc}>The PostgreSQL instance under test.</div>
              <table style={s.table}>
                <tbody>
                  <tr><td style={{ ...s.td, color: "#64748b", width: 80, fontWeight: 500 }}>Host</td><td style={s.td}>{config?.database?.host || "localhost"} : {config?.database?.port || 5434}</td></tr>
                  <tr><td style={{ ...s.td, color: "#64748b", fontWeight: 500 }}>User</td><td style={s.td}>{config?.database?.user || "postgres"}</td></tr>
                  <tr><td style={{ ...s.td, color: "#64748b", fontWeight: 500 }}>Database</td><td style={s.td}>{config?.database?.database || "testdb"}</td></tr>
                  <tr><td style={{ ...s.td, color: "#64748b", fontWeight: 500 }}>Size</td><td style={s.td}>{db.db_size || "..."}</td></tr>
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

            <div id="section-jobs" style={s.card("#10b981")}>
              <div style={s.cardTitle}>Background Jobs</div>
              <div style={s.cardDesc}>Long-running operations report status here.</div>
              {jobs.length === 0 ? (
                <p style={{ fontSize: 12, color: "#94a3b8" }}>No jobs yet. Run an operation above.</p>
              ) : (
                <div style={{ maxHeight: 200, overflow: "auto" }}>
                  <table style={s.table}>
                    <thead><tr><th style={s.th}>ID</th><th style={s.th}>Type</th><th style={s.th}>Status</th><th style={s.th}>Time</th></tr></thead>
                    <tbody>
                      {[...jobs].reverse().slice(0, 15).map(j => (
                        <tr key={j.id}>
                          <td style={{ ...s.td, fontFamily: "monospace", fontSize: 11 }}>{j.id}</td>
                          <td style={s.td}>{j.type}</td>
                          <td style={s.td}><Badge status={j.status} /></td>
                          <td style={{ ...s.td, fontSize: 10, color: "#94a3b8" }}>{j.started_at?.split("T")[1]?.split(".")[0]}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div style={s.card("#10b981")}>
              <div style={s.cardTitle}>Saved Reports</div>
              <div style={s.cardDesc}>Ladder results and AI analysis reports.</div>
              <button style={{ ...s.btn, ...s.btnGhost, ...s.btnFull }}
                onClick={async () => { try { const r = await api("/reports"); setReport(r) } catch {} }}>
                List Reports
              </button>
            </div>
          </div>

          {report && (
            <div style={{ ...s.card("#10b981"), marginTop: 16, gridColumn: "1 / -1" }}>
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
