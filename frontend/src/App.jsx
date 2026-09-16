import { useEffect, useRef, useState } from "react";
import Header from "./components/Header";
import QuestionForm from "./components/QuestionForm";
import AnswerCard from "./components/AnswerCard";
import { demoResult } from "./data/demoResult";

export default function App() {
  const [messages, setMessages] = useState([]);
  const [toast, setToast] = useState("");
  const toastTimer = useRef();
  const conversationEnd = useRef();

  useEffect(() => () => window.clearTimeout(toastTimer.current), []);

  function showToast(message) {
    setToast(message);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(""), 1800);
  }

  function submitQuestion(question) {
    setMessages((current) => [
      ...current,
      {
        id: crypto.randomUUID(),
        question,
        result: demoResult,
      },
    ]);
  }

  useEffect(() => {
    if (messages.length > 0) {
      conversationEnd.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [messages.length]);

  return (
    <div className="app-shell">
      <Header />
      <main>
        {messages.length === 0 ? (
          <QuestionForm onSubmit={submitQuestion} />
        ) : (
          <section className="chat-page">
            <div className="chat-heading">
              <div>
                <p className="eyebrow">Current conversation</p>
                <h2>Clinical data exploration</h2>
              </div>
              <button className="clear-chat" onClick={() => setMessages([])}>Clear conversation</button>
            </div>

            <div className="conversation" aria-live="polite">
              {messages.map((message) => (
                <div className="chat-turn" key={message.id}>
                  <div className="question-row">
                    <span className="avatar">You</span>
                    <p>{message.question}</p>
                  </div>
                  <div className="assistant-label">
                    <span className="assistant-mark" aria-hidden="true"><i /><i /><i /></span>
                    <span>Clarity</span>
                  </div>
                  <AnswerCard result={message.result} onToast={showToast} />
                </div>
              ))}
              <div ref={conversationEnd} />
            </div>

            <QuestionForm compact onSubmit={submitQuestion} />
          </section>
        )}
      </main>
      <footer>
        <span>For research exploration only — not for clinical decision-making.</span>
        <span>Powered by MIMIC-IV</span>
      </footer>
      <div className={`toast ${toast ? "show" : ""}`} role="status">{toast}</div>
    </div>
  );
}
