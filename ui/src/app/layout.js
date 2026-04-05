export const metadata = {
  title: "Burnside Project — pg-stress",
  description: "PostgreSQL stress test control plane",
}

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body style={{ margin: 0, fontFamily: "system-ui, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif", background: "#f8fafc", color: "#1e293b" }}>
        {children}
      </body>
    </html>
  )
}
