import { useEffect, useState } from 'react'
import './App.css'

type Status = 'idle' | 'sending' | 'sent' | 'cancelling' | 'cancelled' | 'error'

// 各画面から初期画面へ戻るまでの時間
const RESET_MS: Partial<Record<Status, number>> = {
  sent: 10000, // この間だけキャンセル可能
  cancelled: 3000,
  error: 5000,
}

export default function App() {
  const [targets, setTargets] = useState<string[]>([])
  const [status, setStatus] = useState<Status>('idle')
  const [callId, setCallId] = useState<string | null>(null)

  // 宛先一覧の取得（失敗後に idle へ戻ったら再取得）
  useEffect(() => {
    if (status !== 'idle' || targets.length > 0) return
    fetch('/api/targets')
      .then((r) => r.json())
      .then(setTargets)
      .catch(() => setStatus('error'))
  }, [status, targets.length])

  // 完了・キャンセル・エラー画面は一定時間で初期画面へ戻す
  useEffect(() => {
    const ms = RESET_MS[status]
    if (!ms) return
    const id = setTimeout(() => {
      setStatus('idle')
      setCallId(null)
    }, ms)
    return () => clearTimeout(id)
  }, [status])

  const call = async (to: string) => {
    setStatus('sending')
    try {
      const r = await fetch('/api/call', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ to }),
      })
      if (!r.ok) throw new Error()
      const data = await r.json()
      setCallId(data.id ?? null) // cooldown 時は id なし => キャンセル不可
      setStatus('sent')
    } catch {
      setStatus('error')
    }
  }

  const cancel = async () => {
    if (!callId) return
    setStatus('cancelling')
    try {
      const r = await fetch('/api/cancel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: callId }),
      })
      setStatus(r.ok ? 'cancelled' : 'error')
    } catch {
      setStatus('error')
    }
  }

  if (status === 'sent' || status === 'cancelling') {
    return (
      <main className='message'>
        <p>
          お呼びしました。
          <br />
          少々お待ちください。
        </p>
        {callId && (
          <button className='cancel' disabled={status === 'cancelling'} onClick={cancel}>
            呼び出しを取り消す
          </button>
        )}
      </main>
    )
  }

  if (status === 'cancelled') {
    return <main className='message'>呼び出しを取り消しました。</main>
  }

  if (status === 'error') {
    return (
      <main className='message error'>
        処理に失敗しました。
        <br />
        お手数ですが内線をご利用ください。
      </main>
    )
  }

  return (
    <main>
      <h1>ご用件を選んでください</h1>
      <div className='buttons'>
        {targets.map((t) => (
          <button key={t} disabled={status === 'sending'} onClick={() => call(t)}>
            {t}
          </button>
        ))}
      </div>
    </main>
  )
}
