import { useEffect, useRef, useState } from 'react'
import { io } from 'socket.io-client'

export function useSocket(maxEvents = 100) {
  const [events, setEvents]     = useState([])
  const [connected, setConnected] = useState(false)
  const socketRef = useRef(null)

  useEffect(() => {
    // In production VITE_API_URL is the Railway backend URL; in dev Vite proxies.
    const server = import.meta.env.VITE_API_URL || ''
    const socket = io(server + '/ws/feed', { path: '/ws', transports: ['websocket'] })
    socketRef.current = socket

    socket.on('connect',    () => setConnected(true))
    socket.on('disconnect', () => setConnected(false))

    const EVENTS = [
      'state_change', 'market_report', 'strategy_bundle', 'risk_assessment',
      'simulation_result', 'execution_report', 'yield_payment', 'demo_shock', 'error',
    ]
    EVENTS.forEach(type => {
      socket.on(type, data => {
        setEvents(prev => {
          // Server sends { payload: {...}, ts: ... } — unwrap the inner payload
          const entry = { type, payload: data?.payload ?? data, ts: data?.ts ?? Date.now() }
          return [entry, ...prev].slice(0, maxEvents)
        })
      })
    })

    return () => socket.disconnect()
  }, [])

  return { events, connected }
}
