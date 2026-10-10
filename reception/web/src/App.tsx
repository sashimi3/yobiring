import { useEffect, useState } from 'react';
import './App.css';

type Status = "idle" | "sending" | "sent" | "error";

export default function App() {
  const [targets, setTargets] = useState<string[]>([]);
  const [status, setStatus] = useState<Status>("idle");

  // 宛先一覧の取得(失敗後に idle へ戻ったら再取得)
  useEffect(() => {
    if (status !== "idle" || targets.length > 0) return;
    fetch("/api/targets")
      .then((r) => r.json())
      .then(setTargets)
      .catch(() => setStatus("error"));
  }, [status, targets.length]);

  // 完了/エラー画面は数秒で初期画面へ戻す
  useEffect(() => {
    if (status !== "sent" && status !== "error") return;
    const id = setTimeout(() => setStatus("idle"), 5000);
    return () => clearTimeout(id);
  }, [status]);

  const call = async (to: string) => {
    setStatus("sending");
    try {
      const r = await fetch("/api/call", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ to }),
      });
      setStatus(r.ok ? "sent" : "error");
    } catch {
      setStatus("error");
    }
  };

  if (status === "sent") {
    return (
      <main className="message">
        お呼びしました。
        <br />
        少々お待ちください。
      </main>
    );
  }

  if (status === "error") {
    return (
      <main className="message error">
        呼び出しに失敗しました。
        <br />
        お手数ですが内線をご利用ください。
      </main>
    );
  }

  return (
    <main>
      <h1>ご用件の部署を選んでください</h1>
      <div className="buttons">
        {targets.map((t) => (
          <button key={t} disabled={status === "sending"} onClick={() => call(t)}>
            {t}
          </button>
        ))}
      </div>
    </main>
  );
}
