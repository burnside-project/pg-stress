"use client"

import { useState, useEffect, useCallback } from "react"

const API = typeof window !== "undefined"
  ? `${window.location.protocol}//${window.location.hostname}:8100`
  : "http://localhost:8100"

// ── Styles ──────────────────────────────────────────────────────────────

const styles = {
  container: { maxWidth: 1200, margin: "0 auto", padding: "24px" },
  header: { display: "flex", alignItems: "center", gap: 16, marginBottom: 32, borderBottom: "1px solid #222", paddingBottom: 16 },
  logo: { fontSize: 28, fontWeight: 700, color: "#fff" },
  subtitle: { fontSize: 14, color: "#666" },
  grid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))", gap: 16 },
  card: { background: "#111", border: "1px solid #222", borderRadius: 8, padding: 20 },
  cardTitle: { fontSize: 16, fontWeight: 600, color: "#fff", marginBottom: 12, display: "flex", alignItems: "center", gap: 8 },
  label: { fontSize: 12, color: "#888", marginBottom: 4, display: "block" },
  input: { width: "100%", padding: "8px 12px", background: "#1a1a1a", border: "1px solid #333", borderRadius: 6, color: "#fff", fontSize: 14, boxSizing: "border-box" },
  select: { width: "100%", padding: "8px 12px", background: "#1a1a1a", border: "1px solid #333", borderRadius: 6, color: "#fff", fontSize: 14 },
  btn: { padding: "8px 16px", borderRadius: 6, border: "none", fontSize: 13, fontWeight: 600, cursor: "pointer", transition: "all 0.15s" },
  btnPrimary: { background: "#2563eb", color: "#fff" },
  btnSuccess: { background: "#16a34a", color: "#fff" },
  btnDanger: { background: "#dc2626", color: "#fff" },
  btnGhost: { background: "transparent", color: "#888", border: "1px solid #333" },
  row: { display: "flex", gap: 8, alignItems: "end" },
  badge: (color) => ({ display: "inline-block", padding: "2px 8px", borderRadius: 12, fontSize: 11, fontWeight: 600, background: color + "22", color }),
  stat: { textAlign: "center" },
  statValue: { fontSize: 24, fontWeight: 700, color: "#fff" },
  statLabel: { fontSize: 11, color: "#666", marginTop: 2 },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 13 },
  th: { textAlign: "left", padding: "8px", borderBottom: "1px solid #222", color: "#888", fontWeight: 500 },
  td: { padding: "8px", borderBottom: "1px solid #1a1a1a" },
  log: { background: "#0a0a0a", border: "1px solid #222", borderRadius: 6, padding: 12, fontSize: 12, fontFamily: "monospace", maxHeight: 200, overflow: "auto", whiteSpace: "pre-wrap", color: "#888" },
  alert: (type) => ({ padding: "10px 14px", borderRadius: 6, fontSize: 13, marginBottom: 8, background: type === "error" ? "#dc262622" : type === "success" ? "#16a34a22" : "#2563eb22", color: type === "error" ? "#f87171" : type === "success" ? "#4ade80" : "#60a5fa" }),
}

// ── API helpers ─────────────────────────────────────────────────────────

async function api(path, opts = {}) {
  const res = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  })
  return res.json()
}

function post(path, body) {
  return api(path, { method: "POST", body: JSON.stringify(body) })
}

// ── Components ──────────────────────────────────────────────────────────

function StatusBadge({ status }) {
  const colors = { running: "#16a34a", healthy: "#16a34a", exited: "#dc2626", not_found: "#666", restarting: "#eab308" }
  return <span style={styles.badge(colors[status] || "#666")}>{status}</span>
}

function StatCard({ value, label }) {
  return (
    <div style={styles.stat}>
      <div style={styles.statValue}>{value}</div>
      <div style={styles.statLabel}>{label}</div>
    </div>
  )
}

// ── Main Page ───────────────────────────────────────────────────────────

export default function Home() {
  const [status, setStatus] = useState(null)
  const [jobs, setJobs] = useState([])
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState({})

  // Form states
  const [injectTable, setInjectTable] = useState("orders")
  const [injectRows, setInjectRows] = useState(1000000)
  const [updateTable, setUpdateTable] = useState("orders")
  const [updateSet, setUpdateSet] = useState("status='archived'")
  const [updateWhere, setUpdateWhere] = useState("placed_at < now() - interval '1 year'")
  const [updateBatch, setUpdateBatch] = useState(100000)
  const [connCount, setConnCount] = useState(50)
  const [connDuration, setConnDuration] = useState(300)
  const [connMode, setConnMode] = useState("mixed")
  const [ladderSteps, setLadderSteps] = useState("10,25,50,100,200")
  const [ladderDuration, setLadderDuration] = useState(180)
  const [analyzeFocus, setAnalyzeFocus] = useState("")
  const [latestReport, setLatestReport] = useState(null)

  const addLog = useCallback((msg) => {
    setLogs((prev) => [...prev.slice(-50), `[${new Date().toLocaleTimeString()}] ${msg}`])
  }, [])

  const refresh = useCallback(async () => {
    try {
      const s = await api("/status")
      setStatus(s)
      const j = await api("/jobs")
      setJobs(j)
    } catch (e) {
      /* ignore */
    }
  }, [])

  useEffect(() => {
    refresh()
    const interval = setInterval(refresh, 5000)
    return () => clearInterval(interval)
  }, [refresh])

  const act = async (key, fn) => {
    setLoading((p) => ({ ...p, [key]: true }))
    try {
      const res = await fn()
      addLog(`${key}: ${JSON.stringify(res)}`)
      refresh()
      return res
    } catch (e) {
      addLog(`${key} ERROR: ${e.message}`)
    } finally {
      setLoading((p) => ({ ...p, [key]: false }))
    }
  }

  const tables = status?.tables ? Object.keys(status.tables).sort() : []
  const dbSize = status?.database?.db_size || "..."
  const dbConns = status?.database?.connections || "..."

  return (
    <div style={styles.container}>
      {/* Header */}
      <div style={styles.header}>
        <div>
          <div style={styles.logo}>pg-stress</div>
          <div style={styles.subtitle}>Control Plane</div>
        </div>
        <div style={{ flex: 1 }} />
        <StatCard value={dbSize} label="Database Size" />
        <StatCard value={dbConns} label="Connections" />
        <StatCard value={jobs.filter((j) => j.status === "running").length} label="Active Jobs" />
      </div>

      <div style={styles.grid}>
        {/* ── Services ──────────────────────────────────────────── */}
        <div style={styles.card}>
          <div style={styles.cardTitle}>Services</div>
          <table style={styles.table}>
            <thead>
              <tr><th style={styles.th}>Service</th><th style={styles.th}>Status</th><th style={styles.th}></th></tr>
            </thead>
            <tbody>
              {status && Object.entries(status.services).map(([name, svc]) => (
                <tr key={name}>
                  <td style={styles.td}>{name}</td>
                  <td style={styles.td}><StatusBadge status={svc.status} /></td>
                  <td style={styles.td}>
                    {(name === "load-generator-orm" || name === "pgbench-runner") && (
                      svc.status === "running"
                        ? <button style={{ ...styles.btn, ...styles.btnDanger }} onClick={() => act(`stop-${name}`, () => post(`/generators/${name === "load-generator-orm" ? "orm" : "pgbench"}/stop`))}>Stop</button>
                        : <button style={{ ...styles.btn, ...styles.btnSuccess }} onClick={() => act(`start-${name}`, () => post(`/generators/${name === "load-generator-orm" ? "orm" : "pgbench"}/start`))}>Start</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* ── Tables ────────────────────────────────────────────── */}
        <div style={styles.card}>
          <div style={styles.cardTitle}>Tables</div>
          <table style={styles.table}>
            <thead>
              <tr><th style={styles.th}>Table</th><th style={styles.th}>Rows</th><th style={styles.th}>Dead</th><th style={styles.th}>Size</th></tr>
            </thead>
            <tbody>
              {tables.map((t) => (
                <tr key={t}>
                  <td style={styles.td}>{t}</td>
                  <td style={styles.td}>{(status.tables[t].n_live_tup || 0).toLocaleString()}</td>
                  <td style={styles.td}>{(status.tables[t].n_dead_tup || 0).toLocaleString()}</td>
                  <td style={styles.td}>{status.tables[t].size}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* ── Inject Rows ───────────────────────────────────────── */}
        <div style={styles.card}>
          <div style={styles.cardTitle}>Inject Rows</div>
          <p style={{ fontSize: 12, color: "#666", marginBottom: 12 }}>"What if this table grows by N rows?"</p>
          <div style={{ marginBottom: 8 }}>
            <label style={styles.label}>Table</label>
            <select style={styles.select} value={injectTable} onChange={(e) => setInjectTable(e.target.value)}>
              {tables.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div style={{ marginBottom: 12 }}>
            <label style={styles.label}>Rows</label>
            <input style={styles.input} type="number" value={injectRows} onChange={(e) => setInjectRows(Number(e.target.value))} />
          </div>
          <button
            style={{ ...styles.btn, ...styles.btnPrimary, width: "100%" }}
            disabled={loading.inject}
            onClick={() => act("inject", () => post("/inject", { table: injectTable, rows: injectRows }))}
          >
            {loading.inject ? "Injecting..." : `Inject ${injectRows.toLocaleString()} rows`}
          </button>
        </div>

        {/* ── Bulk Update ───────────────────────────────────────── */}
        <div style={styles.card}>
          <div style={styles.cardTitle}>Bulk Update</div>
          <p style={{ fontSize: 12, color: "#666", marginBottom: 12 }}>"What if we update/archive N rows?"</p>
          <div style={{ marginBottom: 8 }}>
            <label style={styles.label}>Table</label>
            <select style={styles.select} value={updateTable} onChange={(e) => setUpdateTable(e.target.value)}>
              {tables.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div style={{ marginBottom: 8 }}>
            <label style={styles.label}>SET clause</label>
            <input style={styles.input} value={updateSet} onChange={(e) => setUpdateSet(e.target.value)} />
          </div>
          <div style={{ marginBottom: 8 }}>
            <label style={styles.label}>WHERE clause (optional)</label>
            <input style={styles.input} value={updateWhere} onChange={(e) => setUpdateWhere(e.target.value)} />
          </div>
          <div style={{ marginBottom: 12 }}>
            <label style={styles.label}>Batch size</label>
            <input style={styles.input} type="number" value={updateBatch} onChange={(e) => setUpdateBatch(Number(e.target.value))} />
          </div>
          <button
            style={{ ...styles.btn, ...styles.btnPrimary, width: "100%" }}
            disabled={loading.bulkUpdate}
            onClick={() => act("bulkUpdate", () => post("/bulk-update", { table: updateTable, set_clause: updateSet, where_clause: updateWhere || null, batch_size: updateBatch }))}
          >
            {loading.bulkUpdate ? "Updating..." : "Run Bulk Update"}
          </button>
        </div>

        {/* ── Connection Pressure ───────────────────────────────── */}
        <div style={styles.card}>
          <div style={styles.cardTitle}>Connection Pressure</div>
          <p style={{ fontSize: 12, color: "#666", marginBottom: 12 }}>"What happens at N concurrent connections?"</p>
          <div style={styles.row}>
            <div style={{ flex: 1 }}>
              <label style={styles.label}>Connections</label>
              <input style={styles.input} type="number" value={connCount} onChange={(e) => setConnCount(Number(e.target.value))} />
            </div>
            <div style={{ flex: 1 }}>
              <label style={styles.label}>Duration (s)</label>
              <input style={styles.input} type="number" value={connDuration} onChange={(e) => setConnDuration(Number(e.target.value))} />
            </div>
            <div style={{ flex: 1 }}>
              <label style={styles.label}>Mode</label>
              <select style={styles.select} value={connMode} onChange={(e) => setConnMode(e.target.value)}>
                <option value="mixed">Mixed</option>
                <option value="readonly">Read Only</option>
                <option value="tpcb">TPC-B (Write)</option>
              </select>
            </div>
          </div>
          <button
            style={{ ...styles.btn, ...styles.btnPrimary, width: "100%", marginTop: 12 }}
            disabled={loading.connections}
            onClick={() => act("connections", () => post("/connections", { connections: connCount, duration: connDuration, mode: connMode }))}
          >
            {loading.connections ? "Running..." : `Stress ${connCount} connections for ${connDuration}s`}
          </button>
        </div>

        {/* ── Growth Ladder ─────────────────────────────────────── */}
        <div style={styles.card}>
          <div style={styles.cardTitle}>Growth Ladder</div>
          <p style={{ fontSize: 12, color: "#666", marginBottom: 12 }}>Ramp connections to find the breaking point. Results saved to reports.</p>
          <div style={{ marginBottom: 8 }}>
            <label style={styles.label}>Steps (comma-separated connection counts)</label>
            <input style={styles.input} value={ladderSteps} onChange={(e) => setLadderSteps(e.target.value)} />
          </div>
          <div style={{ marginBottom: 12 }}>
            <label style={styles.label}>Phase duration (seconds per step)</label>
            <input style={styles.input} type="number" value={ladderDuration} onChange={(e) => setLadderDuration(Number(e.target.value))} />
          </div>
          <button
            style={{ ...styles.btn, ...styles.btnPrimary, width: "100%" }}
            disabled={loading.ladder}
            onClick={() => act("ladder", () => post("/ladder", { steps: ladderSteps.split(",").map(Number), phase_duration: ladderDuration }))}
          >
            {loading.ladder ? "Running..." : `Run Ladder (${ladderSteps.split(",").length} phases, ~${ladderSteps.split(",").length * ladderDuration / 60}min)`}
          </button>
        </div>

        {/* ── AI Analyzer ───────────────────────────────────────── */}
        <div style={styles.card}>
          <div style={styles.cardTitle}>AI Analyzer</div>
          <p style={{ fontSize: 12, color: "#666", marginBottom: 12 }}>Send diagnostics to Claude for tuning advice, query fixes, and capacity predictions.</p>
          <div style={{ marginBottom: 12 }}>
            <label style={styles.label}>Focus</label>
            <select style={styles.select} value={analyzeFocus} onChange={(e) => setAnalyzeFocus(e.target.value)}>
              <option value="">Full Analysis</option>
              <option value="tuning">PostgreSQL Tuning</option>
              <option value="queries">Query Optimization</option>
              <option value="capacity">Capacity Predictions</option>
            </select>
          </div>
          <div style={styles.row}>
            <button
              style={{ ...styles.btn, ...styles.btnSuccess, flex: 1 }}
              disabled={loading.analyze}
              onClick={() => act("analyze", () => post("/analyze", { focus: analyzeFocus || null }))}
            >
              {loading.analyze ? "Analyzing..." : "Run Analysis"}
            </button>
            <button
              style={{ ...styles.btn, ...styles.btnGhost, flex: 1 }}
              onClick={async () => {
                try {
                  const r = await api("/analyze/latest")
                  setLatestReport(r)
                } catch { setLatestReport({ error: "No reports yet" }) }
              }}
            >
              View Latest Report
            </button>
          </div>
        </div>

        {/* ── Jobs ──────────────────────────────────────────────── */}
        <div style={styles.card}>
          <div style={styles.cardTitle}>Background Jobs</div>
          {jobs.length === 0 ? (
            <p style={{ fontSize: 13, color: "#666" }}>No jobs yet. Run an operation above.</p>
          ) : (
            <table style={styles.table}>
              <thead>
                <tr><th style={styles.th}>ID</th><th style={styles.th}>Type</th><th style={styles.th}>Status</th><th style={styles.th}>Started</th></tr>
              </thead>
              <tbody>
                {jobs.slice(-10).reverse().map((j) => (
                  <tr key={j.id}>
                    <td style={styles.td}><code>{j.id}</code></td>
                    <td style={styles.td}>{j.type}</td>
                    <td style={styles.td}><StatusBadge status={j.status} /></td>
                    <td style={{ ...styles.td, fontSize: 11 }}>{j.started_at?.split("T")[1]?.split(".")[0]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* ── Latest Report ─────────────────────────────────────── */}
        {latestReport && (
          <div style={{ ...styles.card, gridColumn: "1 / -1" }}>
            <div style={styles.cardTitle}>
              Latest Report
              <button style={{ ...styles.btn, ...styles.btnGhost, marginLeft: "auto" }} onClick={() => setLatestReport(null)}>Close</button>
            </div>
            <div style={styles.log}>
              {latestReport.analysis || JSON.stringify(latestReport, null, 2)}
            </div>
          </div>
        )}
      </div>

      {/* ── Activity Log ────────────────────────────────────────── */}
      {logs.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div style={{ display: "flex", alignItems: "center", marginBottom: 8 }}>
            <span style={{ fontSize: 13, color: "#888" }}>Activity Log</span>
            <button style={{ ...styles.btn, ...styles.btnGhost, marginLeft: "auto", fontSize: 11 }} onClick={() => setLogs([])}>Clear</button>
          </div>
          <div style={styles.log}>{logs.join("\n")}</div>
        </div>
      )}
    </div>
  )
}
