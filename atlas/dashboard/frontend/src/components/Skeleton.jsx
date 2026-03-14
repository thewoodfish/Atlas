export function Skeleton({ w = '100%', h = 16, className = '' }) {
  return (
    <div style={{ width: w, height: h, background: '#1e293b', borderRadius: 6, animation: 'pulse 1.5s ease-in-out infinite' }}
      className={className} />
  )
}

export function SkeletonCard() {
  return (
    <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 12, padding: 16 }}>
      <Skeleton h={12} w="60%" />
      <div style={{ marginTop: 12 }} />
      <Skeleton h={28} w="80%" />
      <div style={{ marginTop: 8 }} />
      <Skeleton h={10} w="50%" />
    </div>
  )
}
