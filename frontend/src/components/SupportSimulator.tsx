import { useState } from 'react'
import { getCsrfToken } from '../services/auth-state'
import { apiBase } from '../services/orders'

type Mode = 'bot' | 'human'
type Message = { sender: 'customer' | 'bot' | 'staff'; text: string }
type SimulationResult = { reply: string | null; mode: Mode; needs_human: boolean; simulated: boolean }

export function SupportSimulator() {
  const [mode, setMode] = useState<Mode>('bot')
  const [draft, setDraft] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function send() {
    const message = draft.trim()
    if (!message || busy) return
    setDraft('')
    setError('')
    setMessages(previous => [...previous, { sender: 'customer', text: message }])
    setBusy(true)
    try {
      const csrf = getCsrfToken()
      const response = await fetch(`${apiBase}/api/v1/support/simulator/message`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        body: JSON.stringify({ message, mode }),
      })
      if (!response.ok) throw new Error('Simulator request failed (' + response.status + ')')
      const result = await response.json() as SimulationResult
      setMode(result.mode)
      if (result.reply) setMessages(previous => [...previous, { sender: 'bot', text: result.reply! }])
    } catch {
      setError('Unable to reach the simulator. Check your Mumchies OS session.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section style={{ maxWidth: 480, margin: '24px auto', fontFamily: 'system-ui' }}>
      <h2>WhatsApp Support Simulator</h2>
      <p>Offline demo only. No WhatsApp messages are sent.</p>
      <div style={{ background: '#e8e3d8', padding: 16, borderRadius: 12, minHeight: 340 }}>
        {messages.map((item, index) => (
          <div key={index} style={{ background: item.sender === 'customer' ? '#fff' : '#d9fdd3',
            padding: 10, margin: '10px 0', borderRadius: 10, maxWidth: '85%',
            marginLeft: item.sender === 'customer' ? 0 : 'auto' }}>
            <small>{item.sender}</small><div>{item.text}</div>
          </div>
        ))}
      </div>
      <p>Control: <strong>{mode === 'human' ? 'Human takeover — bot paused' : 'Bot enabled'}</strong></p>
      <div style={{ display: 'flex', gap: 8 }}>
        <input aria-label="Customer message" value={draft} onChange={event => setDraft(event.target.value)}
          onKeyDown={event => { if (event.key === 'Enter') void send() }}
          placeholder="Type a customer message..." style={{ flex: 1, padding: 10 }} />
        <button disabled={busy || !draft.trim()} onClick={() => void send()}>Send</button>
      </div>
      {error && <p role="alert">{error}</p>}
      <button style={{ marginTop: 12 }} onClick={() => { setMode('bot'); setMessages([]); setError('') }}>
        Start new test conversation
      </button>
    </section>
  )
}
