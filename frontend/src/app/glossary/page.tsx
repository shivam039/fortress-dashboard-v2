import { columnDefinitions } from '@/lib/column-definitions';

export default function GlossaryPage() {
  const entries = Array.from(new Map(
    Object.values(columnDefinitions)
      .filter(item => item.glossaryKey)
      .map(item => [item.glossaryKey, item]),
  ).entries());

  return (
    <>
      <div className="page-header">
        <h1 className="page-title">Fortress glossary</h1>
        <p className="page-subtitle">Plain-English context for the financial and product terms used in table headings.</p>
      </div>
      <div className="section">
        {entries.map(([key, item]) => (
          <article id={item.glossaryKey} key={key} style={{ marginBottom: '1.5rem', scrollMarginTop: '6rem' }}>
            <h2 className="section-title">{item.label}</h2>
            <p>{item.description}</p>
            {item.format && <p className="page-subtitle">Displayed format: {item.format}.</p>}
          </article>
        ))}
      </div>
    </>
  );
}
