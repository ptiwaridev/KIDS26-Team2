import { useState } from "react";

const suggestions = [
  "How many ICU patients were over 65?",
  "Average ICU stay by admission type",
  "Most common diagnoses in the ICU",
];

export default function QuestionForm({ onSubmit, compact = false }) {
  const [question, setQuestion] = useState("");

  function submit(event) {
    event.preventDefault();
    const cleanedQuestion = question.trim();
    if (cleanedQuestion) {
      onSubmit(cleanedQuestion);
      setQuestion("");
    }
  }

  function handleKeyDown(event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.form.requestSubmit();
    }
  }

  return (
    <section className={compact ? "composer-section" : "hero"}>
      {!compact && (
        <>
          <p className="eyebrow">Clinical data, in plain language</p>
          <h1>What would you like<br />to <em>discover?</em></h1>
          <p className="intro">Ask a research question about the MIMIC-IV dataset. We’ll translate it into a safe, transparent query.</p>
        </>
      )}
      <form className="ask-box" onSubmit={submit}>
        <label className="sr-only" htmlFor="question">Ask a question about MIMIC-IV</label>
        <textarea
          id="question"
          rows="2"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={compact ? "Ask a follow-up question…" : "Ask about patients, admissions, diagnoses, labs…"}
        />
        <div className="ask-actions">
          <div className="scope"><span />Read-only query</div>
          <button className="send-button" type="submit" aria-label="Submit question">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14M14 7l5 5-5 5" /></svg>
          </button>
        </div>
      </form>
      {!compact && (
        <div className="suggestions" aria-label="Suggested questions">
          <p>Try asking</p>
          <div className="suggestion-grid">
            {suggestions.map((suggestion) => (
              <button className="suggestion" key={suggestion} onClick={() => setQuestion(suggestion)}>{suggestion}</button>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
