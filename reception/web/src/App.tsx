import { useEffect, useState } from 'react'
import './App.css'

type Status =
  | 'idle'  // 初期状態
  | 'sending' // 呼び出し中
  | 'sent' // 呼び出し済み
  | 'cancelling' // キャンセル中
  | 'cancelled' // キャンセル済み
  | 'accepted' // 対応済み
  | 'error' // エラー

// 各画面から初期画面へ戻るまでの時間
const RESET_MS: Partial<Record<Status, number>> = {
  sent: 60000, // 応答待ち。この間はキャンセル可能
  accepted: 10000,
  cancelled: 3000,
  error: 5000,
}

// 残り時間の数字と、減っていく円形プログレス
function Countdown({ ms }: { ms: number }) {
  const [left, setLeft] = useState(ms)

  useEffect(() => {
    const end = Date.now() + ms
    const id = setInterval(() => setLeft(Math.max(0, end - Date.now())), 100)
    return () => clearInterval(id)
  }, [ms])

  const r = 36
  const c = 2 * Math.PI * r

  return (
    <div className='countdown'>
      <svg viewBox='0 0 80 80'>
        <circle className='track' cx='40' cy='40' r={r} />
        <circle
          className='bar'
          cx='40'
          cy='40'
          r={r}
          strokeDasharray={c}
          strokeDashoffset={c * (1 - left / ms)}
          transform='rotate(-90 40 40)'
        />
      </svg>
      {/* <span>{Math.ceil(left / 1000)}</span> */}
    </div>
  )
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

  // 応答待ちの間、対応状況をポーリング
  useEffect(() => {
    if (status !== 'sent' || !callId) return
    const id = setInterval(async () => {
      try {
        const r = await fetch(`/api/calls/${callId}`)
        if (!r.ok) return
        const data = await r.json()
        if (data.state === 'accepted') {
          setStatus('accepted')
        }
      } catch {
        // 一時的な失敗は次回のポーリングに任せる
      }
    }, 2000)
    return () => clearInterval(id)
  }, [status, callId])

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
      setCallId(data.id ?? null) // cooldown 時は id なし → キャンセル不可
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
      // 409 = キャンセル直前に対応済みになった
      setStatus(r.ok ? 'cancelled' : r.status === 409 ? 'sent' : 'error')
    } catch {
      setStatus('error')
    }
  }

  if (status === 'accepted') {
    return (
      <main className='message'>
        <p>
          スタッフが向かっています。
          <br />
          少々お待ちください。
        </p>
        <Countdown key="accepted" ms={RESET_MS.accepted!} />
        <p className="note">画面が元に戻っても、スタッフはそのまま向かいます。</p>
      </main>
    )
  }

  if (status === 'sent' || status === 'cancelling') {
    return (
      <main className='message'>
        <p>
          呼び出しを行いました。
          <br />
          少々お待ちください。
        </p>
        {status === 'sent' && <Countdown ms={RESET_MS.sent!} />}
        {callId && (
          <button className='cancel' disabled={status === 'cancelling'} onClick={cancel}>
            呼び出しを取り消す
          </button>
        )}
        <p className="note">画面が元に戻っても、呼び出しは取り消されません。</p>
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
