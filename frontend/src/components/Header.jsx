export default function Header() {
  return (
    <header className="topbar">
      <a className="brand" href="#" aria-label="Clarity home">
        <span className="brand-mark" aria-hidden="true"><i /><i /><i /></span>
        <span>Clarity</span>
      </a>
      <div className="dataset-pill"><span />MIMIC-IV v3.1</div>
      <button className="icon-button" aria-label="Open menu">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 7h14M5 12h14M5 17h14" /></svg>
      </button>
    </header>
  );
}
