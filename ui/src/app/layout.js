export const metadata = {
  title: "pg-stress",
  description: "PostgreSQL stress test control plane",
}

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body style={{ margin: 0, fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif", background: "#0a0a0a", color: "#e0e0e0" }}>
        {children}
      </body>
    </html>
  )
}
