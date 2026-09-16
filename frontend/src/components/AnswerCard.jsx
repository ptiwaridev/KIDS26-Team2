import { useState } from "react";

const tabs = [["results", "Results"], ["sql", "SQL query"], ["method", "Method"]];

export default function AnswerCard({ result, onToast }) {
  const [activeTab, setActiveTab] = useState("results");

  function downloadCsv() {
    const lines = [["Age group", "Patients", "Share"], ...result.rows];
    const csv = `${lines.map((row) => row.join(",")).join("\n")}\n`;
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "mimic-iv-results.csv";
    link.click();
    URL.revokeObjectURL(url);
    onToast("CSV downloaded");
  }

  async function copySql() {
    await navigator.clipboard.writeText(result.sql);
    onToast("SQL copied to clipboard");
  }

  return (
    <article className="answer-card">
      <div className="answer-heading">
        <div>
          <p className="eyebrow">Analysis complete</p>
          <h2>{result.value} <span>{result.label}</span></h2>
        </div>
        <div className="verified"><span>✓</span> Query verified</div>
      </div>
      <p className="answer-copy">{result.summary}</p>
      <div className="facts">
        {result.facts.map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}
      </div>
      <div className="tabs" role="tablist">
        {tabs.map(([id, label]) => (
          <button className={`tab ${activeTab === id ? "active" : ""}`} key={id} onClick={() => setActiveTab(id)} role="tab" aria-selected={activeTab === id}>{label}</button>
        ))}
      </div>
      {activeTab === "results" && (
        <div className="tab-panel active">
          <div className="table-toolbar">
            <p>Result preview</p>
            <button onClick={downloadCsv} className="text-button">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v11m0 0 4-4m-4 4-4-4M5 19h14" /></svg>
              Download CSV
            </button>
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Age group</th><th>Patients</th><th>Share</th></tr></thead>
              <tbody>{result.rows.map((row) => <tr key={row[0]}>{row.map((cell) => <td key={cell}>{cell}</td>)}</tr>)}</tbody>
            </table>
          </div>
        </div>
      )}
      {activeTab === "sql" && (
        <div className="tab-panel active">
          <div className="code-heading"><span>Generated SQL</span><button onClick={copySql}>Copy</button></div>
          <pre><code>{result.sql}</code></pre>
        </div>
      )}
      {activeTab === "method" && (
        <div className="tab-panel active method">
          <p><strong>How this was calculated</strong></p>
          <p>Patient age was estimated at ICU admission. Each patient was counted once, even if they had multiple ICU stays.</p>
          <p className="note">Ages above 89 are grouped together in MIMIC-IV to protect patient privacy.</p>
        </div>
      )}
    </article>
  );
}
