"use client"

import { useState, useEffect, useCallback } from "react"

const API = typeof window !== "undefined"
  ? `${window.location.protocol}//${window.location.hostname}:8100`
  : "http://localhost:8100"

// ── Styles ──────────────────────────────────────────────────────────────

const s = {
  page: { maxWidth: 1280, margin: "0 auto", padding: "24px 24px 64px" },
  header: { display: "flex", alignItems: "center", gap: 16, marginBottom: 8 },
  logo: { fontSize: 28, fontWeight: 700, color: "#fff" },
  tagline: { fontSize: 13, color: "#555" },
  topBar: { display: "flex", gap: 24, padding: "16px 0", marginBottom: 24, borderBottom: "1px solid #1a1a1a", flexWrap: "wrap" },
  stat: { textAlign: "center", minWidth: 80 },
  statVal: { fontSize: 22, fontWeight: 700, color: "#fff" },
  statLbl: { fontSize: 10, color: "#555", textTransform: "uppercase", letterSpacing: 1 },
  section: { marginBottom: 32 },
  sectionHead: { fontSize: 13, fontWeight: 600, color: "#555", textTransform: "uppercase", letterSpacing: 1.5, marginBottom: 12, paddingBottom: 8, borderBottom: "1px solid #1a1a1a" },
  grid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))", gap: 12 },
  card: { background: "#111", border: "1px solid #1e1e1e", borderRadius: 8, padding: 16 },
  cardWide: { background: "#111", border: "1px solid #1e1e1e", borderRadius: 8, padding: 16, gridColumn: "1 / -1" },
  cardTitle: { fontSize: 14, fontWeight: 600, color: "#fff", marginBottom: 4 },
  cardDesc: { fontSize: 12, color: "#555", marginBottom: 12 },
  label: { fontSize: 11, color: "#666", marginBottom: 3, display: "block" },
  input: { width: "100%", padding: "7px 10px", background: "#0a0a0a", border: "1px solid #2a2a2a", borderRadius: 5, color: "#ccc", fontSize: 13, boxSizing: "border-box" },
  select: { width: "100%", padding: "7px 10px", background: "#0a0a0a", border: "1px solid #2a2a2a", borderRadius: 5, color: "#ccc", fontSize: 13 },
  row: { display: "flex", gap: 8, alignItems: "end" },
  gap: { marginBottom: 8 },
  btn: { padding: "7px 14px", borderRadius: 5, border: "none", fontSize: 12, fontWeight: 600, cursor: "pointer" },
  btnBlue: { background: "#2563eb", color: "#fff" },
  btnGreen: { background: "#16a34a", color: "#fff" },
  btnRed: { background: "#dc2626", color: "#fff" },
  btnGhost: { background: "transparent", color: "#666", border: "1px solid #2a2a2a" },
  btnFull: { width: "100%", marginTop: 8 },
  badge: (c) => ({ display: "inline-block", padding: "2px 8px", borderRadius: 10, fontSize: 10, fontWeight: 600, background: c + "18", color: c }),
  table: { width: "100%", borderCollapse: "collapse", fontSize: 12 },
  th: { textAlign: "left", padding: "6px 8px", borderBottom: "1px solid #1e1e1e", color: "#555", fontWeight: 500, fontSize: 11 },
  td: { padding: "6px 8px", borderBottom: "1px solid #141414" },
  mono: { fontFamily: "monospace", fontSize: 12, background: "#0a0a0a", border: "1px solid #1e1e1e", borderRadius: 5, padding: 12, maxHeight: 240, overflow: "auto", whiteSpace: "pre-wrap", color: "#777" },
}

// ── API ─────────────────────────────────────────────────────────────────

async function api(path, opts = {}) {
  const res = await fetch(`${API}${path}`, { headers: { "Content-Type": "application/json" }, ...opts })
  return res.json()
}
function post(path, body) { return api(path, { method: "POST", body: JSON.stringify(body) }) }

// ── Helpers ─────────────────────────────────────────────────────────────

function Badge({ status }) {
  const c = { running: "#16a34a", healthy: "#16a34a", completed: "#16a34a", exited: "#dc2626", failed: "#dc2626", not_found: "#444", restarting: "#eab308" }
  return <span style={s.badge(c[status] || "#444")}>{status}</span>
}

function fmt(n) { return n != null ? Number(n).toLocaleString() : "—" }

// ── Page ────────────────────────────────────────────────────────────────

export default function Home() {
  const [status, setStatus] = useState(null)
  const [jobs, setJobs] = useState([])
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState({})
  const [report, setReport] = useState(null)

  // Form state
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

  const tables = status?.tables ? Object.keys(status.tables).sort() : []
  const db = status?.database || {}
  const svcs = status?.services || {}

  return (
    <div style={s.page}>

      {/* ═══ Header + Stats Bar ═══════════════════════════════════════ */}
      <div style={s.header}>
        <div>
          <div style={s.logo}>pg-stress</div>
          <div style={s.tagline}>Control Plane</div>
        </div>
      </div>

      <div style={s.topBar}>
        <div style={s.stat}><div style={s.statVal}>{db.db_size || "..."}</div><div style={s.statLbl}>Database</div></div>
        <div style={s.stat}><div style={s.statVal}>{db.connections ?? "..."}</div><div style={s.statLbl}>Connections</div></div>
        <div style={s.stat}><div style={s.statVal}>{tables.length}</div><div style={s.statLbl}>Tables</div></div>
        <div style={s.stat}><div style={s.statVal}>{jobs.filter(j => j.status === "running").length}</div><div style={s.statLbl}>Active Jobs</div></div>
        <div style={s.stat}><div style={s.statVal}>{status?.reports ?? 0}</div><div style={s.statLbl}>Reports</div></div>
        <div style={{ flex: 1 }} />
        <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
          {Object.entries(svcs).filter(([,v]) => v.status === "running").map(([k]) => (
            <span key={k} style={s.badge("#16a34a")}>{k}</span>
          ))}
        </div>
      </div>

      {/* ═══ SECTION: Operations (Data Volume) ════════════════════════ */}
      <div style={s.section}>
        <div style={s.sectionHead}>Operations — Data Volume</div>
        <div style={s.grid}>

          {/* Inject Rows */}
          <div style={s.card}>
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

          {/* Bulk Update */}
          <div style={s.card}>
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
              <input style={s.input} value={f.updateSet} onChange={e => set("updateSet", e.target.value)} placeholder="status='archived'" />
            </div>
            <div style={s.gap}>
              <label style={s.label}>WHERE clause</label>
              <input style={s.input} value={f.updateWhere} onChange={e => set("updateWhere", e.target.value)} placeholder="placed_at < now() - interval '1 year'" />
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

          {/* Tables */}
          <div style={s.card}>
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
                      <td style={{ ...s.td, textAlign: "right", color: d.n_dead_tup > 10000 ? "#f87171" : "#555" }}>{fmt(d.n_dead_tup)}</td>
                      <td style={{ ...s.td, textAlign: "right", color: "#888" }}>{d.size}</td>
                    </tr>)
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>

      {/* ═══ SECTION: Transactions & Connections ══════════════════════ */}
      <div style={s.section}>
        <div style={s.sectionHead}>Transactions & Connections</div>
        <div style={s.grid}>

          {/* Connection Pressure */}
          <div style={s.card}>
            <div style={s.cardTitle}>Connection Pressure</div>
            <div style={s.cardDesc}>Open N concurrent connections and sustain for duration.</div>
            <div style={s.row}>
              <div style={{ flex: 1 }}>
                <label style={s.label}>Connections</label>
                <input style={s.input} type="number" value={f.connCount} onChange={e => set("connCount", +e.target.value)} />
              </div>
              <div style={{ flex: 1 }}>
                <label style={s.label}>Duration (sec)</label>
                <input style={s.input} type="number" value={f.connDuration} onChange={e => set("connDuration", +e.target.value)} />
              </div>
              <div style={{ flex: 1 }}>
                <label style={s.label}>Mode</label>
                <select style={s.select} value={f.connMode} onChange={e => set("connMode", e.target.value)}>
                  <option value="mixed">Mixed (R+W)</option>
                  <option value="readonly">Read Only</option>
                  <option value="tpcb">TPC-B (Write)</option>
                </select>
              </div>
            </div>
            <button style={{ ...s.btn, ...s.btnBlue, ...s.btnFull }} disabled={loading.conn}
              onClick={() => act("conn", () => post("/connections", { connections: f.connCount, duration: f.connDuration, mode: f.connMode }))}>
              {loading.conn ? "Running..." : `Stress ${f.connCount} connections × ${f.connDuration}s`}
            </button>
          </div>

          {/* Growth Ladder */}
          <div style={s.card}>
            <div style={s.cardTitle}>Growth Ladder</div>
            <div style={s.cardDesc}>Ramp connections step-by-step to find the breaking point.</div>
            <div style={s.gap}>
              <label style={s.label}>Steps (connection counts, comma-separated)</label>
              <input style={s.input} value={f.ladderSteps} onChange={e => set("ladderSteps", e.target.value)} />
            </div>
            <div style={s.row}>
              <div style={{ flex: 1 }}>
                <label style={s.label}>Seconds per step</label>
                <input style={s.input} type="number" value={f.ladderDuration} onChange={e => set("ladderDuration", +e.target.value)} />
              </div>
              <div style={{ flex: 1 }}>
                <label style={s.label}>Mode</label>
                <select style={s.select} value={f.ladderMode} onChange={e => set("ladderMode", e.target.value)}>
                  <option value="mixed">Mixed</option>
                  <option value="readonly">Read Only</option>
                  <option value="tpcb">TPC-B</option>
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

          {/* Generators */}
          <div style={s.card}>
            <div style={s.cardTitle}>Load Generators</div>
            <div style={s.cardDesc}>Start additional workload sources alongside the raw SQL generator.</div>
            <table style={s.table}>
              <thead><tr><th style={s.th}>Generator</th><th style={s.th}>Status</th><th style={s.th}></th></tr></thead>
              <tbody>
                <tr>
                  <td style={s.td}>Raw SQL (Go)<br/><span style={{ fontSize: 10, color: "#555" }}>25+ OLTP operations + chaos</span></td>
                  <td style={s.td}><Badge status={svcs["load-generator"]?.status || "not_found"} /></td>
                  <td style={s.td}><span style={{ fontSize: 11, color: "#444" }}>always on</span></td>
                </tr>
                {[
                  { key: "orm", name: "ORM (SQLAlchemy)", svc: "load-generator-orm", desc: "N+1, eager load, EXISTS, bulk INSERT" },
                  { key: "pgbench", name: "pgbench", svc: "pgbench-runner", desc: "TPC-B + custom e-commerce scripts" },
                ].map(g => (
                  <tr key={g.key}>
                    <td style={s.td}>{g.name}<br/><span style={{ fontSize: 10, color: "#555" }}>{g.desc}</span></td>
                    <td style={s.td}><Badge status={svcs[g.svc]?.status || "not_found"} /></td>
                    <td style={s.td}>
                      {svcs[g.svc]?.status === "running"
                        ? <button style={{ ...s.btn, ...s.btnRed }} onClick={() => act(`stop-${g.key}`, () => post(`/generators/${g.key}/stop`))}>Stop</button>
                        : <button style={{ ...s.btn, ...s.btnGreen }} onClick={() => act(`start-${g.key}`, () => post(`/generators/${g.key}/start`))}>Start</button>
                      }
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* ═══ SECTION: Analysis & Reports ══════════════════════════════ */}
      <div style={s.section}>
        <div style={s.sectionHead}>Analysis & Reports</div>
        <div style={s.grid}>

          {/* AI Analyzer */}
          <div style={s.card}>
            <div style={s.cardTitle}>AI Analyzer</div>
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

          {/* Jobs */}
          <div style={s.card}>
            <div style={s.cardTitle}>Background Jobs</div>
            <div style={s.cardDesc}>Long-running operations report status here.</div>
            {jobs.length === 0 ? (
              <p style={{ fontSize: 12, color: "#444" }}>No jobs yet. Run an operation above.</p>
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
                        <td style={{ ...s.td, fontSize: 10, color: "#555" }}>{j.started_at?.split("T")[1]?.split(".")[0]}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Reports */}
          <div style={s.card}>
            <div style={s.cardTitle}>Saved Reports</div>
            <div style={s.cardDesc}>Ladder results and AI analysis reports.</div>
            <button style={{ ...s.btn, ...s.btnGhost, ...s.btnFull }}
              onClick={async () => { try { const r = await api("/reports"); setReport(r) } catch {} }}>
              List Reports
            </button>
          </div>
        </div>

        {/* Report Viewer */}
        {report && (
          <div style={{ ...s.cardWide, marginTop: 12 }}>
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

      {/* ═══ Activity Log ═════════════════════════════════════════════ */}
      {logs.length > 0 && (
        <div style={s.section}>
          <div style={{ display: "flex", alignItems: "center", marginBottom: 8 }}>
            <div style={{ ...s.sectionHead, marginBottom: 0, borderBottom: "none", flex: 1 }}>Activity Log</div>
            <button style={{ ...s.btn, ...s.btnGhost, fontSize: 11 }} onClick={() => setLogs([])}>Clear</button>
          </div>
          <div style={s.mono}>{logs.join("\n")}</div>
        </div>
      )}
    </div>
  )
}
