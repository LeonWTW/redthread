// Stand-in route for screens not yet built (Triage, Library, Report, Export).
export default function Placeholder({ title }) {
  return (
    <main className="page">
      <h1>{title}</h1>
      <p className="hint">Coming in a later milestone.</p>
    </main>
  )
}
