import React, { useState, useEffect, useMemo, useRef } from "react";
import {
  Scale,
  Search,
  AlertCircle,
  FileText,
  BookOpen,
  Database,
  Sparkles
} from "lucide-react";
import { checkServerHealth, searchActs } from "./utils/api";
import ReactMarkdown from 'react-markdown';

// Parses text chunk to extract Section/Rule numbers and the legal statement
function parseLawDetails(text) {
  if (!text) return { section: "Statutory Clause", statement: "" };

  const cleanText = text.trim();

  // Pattern 1: Matches "Section X: Title" or "X. Title. -"
  const pattern1 = /^(?:Section\s+)?(\d+[A-Z]?)\.?\s*([A-Z][a-z0-9\s,\-\(\)\/&'\'\"\"\.]+?)(?:\s*[\-\–\—\.]\s*|\n|$)/;
  const match1 = cleanText.match(pattern1);
  if (match1) {
    const secNum = match1[1];
    const secTitle = match1[2].trim();
    const statement = cleanText.substring(match1[0].length).trim();
    return {
      section: `Section ${secNum}: ${secTitle}`,
      statement: statement || cleanText
    };
  }

  // Pattern 2: Matches "Rule X: Title"
  const pattern2 = /^(?:Rule\s+)?(\d+[A-Z]?)\.?\s*([A-Z][a-z0-9\s,\-\(\)\/&'\'\"\"\.]+?)(?:\s*[\-\–\—\.]\s*|\n|$)/i;
  const match2 = cleanText.match(pattern2);
  if (match2) {
    const ruleNum = match2[1];
    const ruleTitle = match2[2].trim();
    const statement = cleanText.substring(match2[0].length).trim();
    return {
      section: `Rule ${ruleNum}: ${ruleTitle}`,
      statement: statement || cleanText
    };
  }

  // Fallback pattern for simple numeric start: "5. Eviction..."
  const pattern3 = /^(\d+[A-Z]?)\.\s+([A-Za-z0-9\s,\-\(\)\/&]+?)(?:\.|\s+-|\n|$)/;
  const match3 = cleanText.match(pattern3);
  if (match3) {
    const num = match3[1];
    const title = match3[2].trim();
    const statement = cleanText.substring(match3[0].length).trim();
    return {
      section: `Section ${num}: ${title}`,
      statement: statement || cleanText
    };
  }

  // If no formal pattern matches, use a clean preview of the text statement
  const previewText = cleanText.replace(/[\r\n]+/g, ' ').trim();
  const preview = previewText.length > 80 ? previewText.substring(0, 80).trim() + "..." : previewText;

  return {
    section: `Excerpt: "${preview}"`,
    statement: cleanText
  };
}

export default function App() {
  const [serverStatus, setServerStatus] = useState("checking");
  const [dbStatus, setDbStatus] = useState("checking");

  // Search state
  const [statement, setStatement] = useState("");
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchResults, setSearchResults] = useState(null);
  const [searchError, setSearchError] = useState("");

  const textareaRef = useRef(null);

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.max(140, textareaRef.current.scrollHeight)}px`;
    }
  }, [statement]);

  // Group and sort unique Laws (sections/rules) by their relevance score
  const lawsSummary = useMemo(() => {
    if (!searchResults || !searchResults.results) return [];

    return searchResults.results.map((item) => {
      const { section } = parseLawDetails(item.text);
      return {
        actName: item.act_name || "Statutory Act",
        section: section,
        score: item.faiss_score || 0
      };
    }).sort((a, b) => b.score - a.score);
  }, [searchResults]);

  // Check health on mount and periodically
  useEffect(() => {
    async function verifyHealth() {
      const health = await checkServerHealth();
      setServerStatus(health.status === "ok" ? "online" : "offline");
      setDbStatus(health.database || "unreachable");
    }
    verifyHealth();
    const interval = setInterval(verifyHealth, 15000);
    return () => clearInterval(interval);
  }, []);

  // Handle Search Submission
  const handleSearchSubmit = async (e) => {
    e.preventDefault();
    if (!statement.trim()) {
      setSearchError("Please enter a statement to query.");
      return;
    }

    setSearchLoading(true);
    setSearchError("");
    setSearchResults(null);

    try {
      const response = await searchActs(statement);
      if (response.status === "success") {
        setSearchResults(response.response);
      } else {
        setSearchError(response.message || "An unexpected error occurred during search.");
      }
    } catch (err) {
      setSearchError(err.message || "Could not reach the search API. Make sure the backend is running.");
    } finally {
      setSearchLoading(false);
    }
  };

  return (
    <div className="app-container">
      {/* Header */}
      <header className="app-header">
        <div className="brand">
          <Scale className="brand-icon" />
          <h1>Judicial AI — Acts Vector Search</h1>
        </div>
        <div className="server-status">
          <span className={`status-dot ${serverStatus}`}></span>
          <span>Backend: {serverStatus.toUpperCase()}</span>
          {serverStatus === "online" && (
            <span style={{ color: "rgba(255,255,255,0.4)", marginLeft: "0.5rem" }}>
              (DB: {dbStatus.toUpperCase()})
            </span>
          )}
        </div>
      </header>

      {/* Main Single Screen Grid */}
      <div className="main-grid search-view">
        {/* Query Composer Panel */}
        <section className="panel">
          <h2>Search Composer</h2>
          <form onSubmit={handleSearchSubmit} className="search-form">
            <div className="field-group">
              <label className="field-label">Statement</label>
              <textarea
                ref={textareaRef}
                className="textarea-input"
                placeholder="Paste or write your statement here..."
                value={statement}
                onChange={(e) => setStatement(e.target.value)}
              />
            </div>


            <button
              type="submit"
              className="btn"
              disabled={searchLoading || serverStatus === "offline"}
            >
              {searchLoading ? (
                <>
                  <span className="spinner"></span> Searching...
                </>
              ) : (
                <>
                  <Search size={18} /> Run Vector Search
                </>
              )}
            </button>
          </form>
        </section>

        {/* Results Visualizer Panel */}
        <section className="panel">
          <div className="results-header">
            <h2>Matching Statutory Clauses</h2>
            {searchResults && (
              <span className="results-badge">
                Returned {searchResults.results?.length || 0} chunks
              </span>
            )}
          </div>

          {searchError && (
            <div className="alert alert-error">
              <AlertCircle className="alert-icon" />
              <div>
                <strong>Search Failed</strong>
                <p>{searchError}</p>
              </div>
            </div>
          )}

          {/* Empty State */}
          {!searchResults && !searchLoading && !searchError && (
            <div className="empty-state">
              <BookOpen className="empty-icon" />
              <h3>No Query Executed</h3>
              <p>Provide a statement and hit "Run Vector Search" to extract matching statutory clauses from FAISS.</p>
            </div>
          )}

          {/* Results List */}
          {searchResults && searchResults.results?.length > 0 && (
            <>
              {searchResults.generated_answer && (
                <div className="generated-answer-panel" style={{ marginBottom: "1.5rem", padding: "1.5rem", background: "linear-gradient(145deg, rgba(30, 41, 59, 0.7), rgba(15, 23, 42, 0.9))", border: `1px solid ${searchResults.confidence === 'HIGH' ? 'var(--success)' : searchResults.confidence === 'MEDIUM' ? '#f59e0b' : 'var(--error)'}`, borderRadius: "12px", boxShadow: "0 4px 15px rgba(0, 0, 0, 0.2)" }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "1rem" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                      <Sparkles style={{ color: "var(--secondary)" }} size={20} />
                      <h3 style={{ fontSize: "1.1rem", fontWeight: 700, color: "#fff", fontFamily: "var(--font-title)", margin: 0 }}>
                        AI Legal Analysis
                      </h3>
                    </div>
                    {searchResults.confidence && (
                      <span style={{
                        padding: "0.25rem 0.75rem",
                        borderRadius: "9999px",
                        fontSize: "0.75rem",
                        fontWeight: 700,
                        fontFamily: "var(--font-title)",
                        letterSpacing: "0.5px",
                        background: searchResults.confidence === 'HIGH' ? 'rgba(48, 209, 88, 0.15)' : searchResults.confidence === 'MEDIUM' ? 'rgba(245, 158, 11, 0.15)' : 'rgba(255, 69, 58, 0.15)',
                        color: searchResults.confidence === 'HIGH' ? 'var(--success)' : searchResults.confidence === 'MEDIUM' ? '#f59e0b' : 'var(--error)',
                        border: `1px solid ${searchResults.confidence === 'HIGH' ? 'rgba(48, 209, 88, 0.3)' : searchResults.confidence === 'MEDIUM' ? 'rgba(245, 158, 11, 0.3)' : 'rgba(255, 69, 58, 0.3)'}`,
                      }}>
                        {searchResults.confidence} CONFIDENCE
                      </span>
                    )}
                  </div>
                  {/* Retrieval metadata */}
                  <div style={{ display: "flex", gap: "1rem", marginBottom: "1rem", flexWrap: "wrap" }}>
                    {searchResults.high_relevance_count != null && (
                      <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", background: "rgba(255,255,255,0.04)", padding: "0.2rem 0.5rem", borderRadius: "4px" }}>
                        📗 {searchResults.high_relevance_count} relevant clauses
                      </span>
                    )}
                    {searchResults.low_relevance_count != null && (
                      <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", background: "rgba(255,255,255,0.04)", padding: "0.2rem 0.5rem", borderRadius: "4px" }}>
                        📙 {searchResults.low_relevance_count} low-relevance clauses
                      </span>
                    )}
                    {searchResults.reformulated_query && (
                      <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", background: "rgba(255,255,255,0.04)", padding: "0.2rem 0.5rem", borderRadius: "4px" }}>
                        🔄 Reformulated: "{searchResults.reformulated_query}"
                      </span>
                    )}
                  </div>
                  <div className="markdown-content" style={{ color: "var(--text-primary)", fontSize: "0.95rem", lineHeight: "1.6" }}>
                    <ReactMarkdown>{searchResults.generated_answer}</ReactMarkdown>
                  </div>
                </div>
              )}

              {lawsSummary.length > 0 && (
                <div className="act-summary-panel" style={{ marginBottom: "1.5rem", paddingBottom: "1.5rem", borderBottom: "1px solid var(--border)" }}>
                  <h3 style={{ fontSize: "1rem", fontWeight: 600, color: "var(--text-secondary)", marginBottom: "0.75rem", fontFamily: "var(--font-title)" }}>
                    Related Laws Summary
                  </h3>
                  <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
                    {lawsSummary.map((law, index) => (
                      <div key={index} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", background: "rgba(255,255,255,0.02)", border: "1px solid var(--border)", padding: "0.75rem 1rem", borderRadius: "8px" }}>
                        <div style={{ flex: 1, paddingRight: "1rem" }}>
                          <span style={{ fontSize: "0.72rem", textTransform: "uppercase", color: "var(--text-muted)", display: "block", marginBottom: "0.15rem", letterSpacing: "0.5px" }}>
                            {law.actName}
                          </span>
                          <strong style={{ fontSize: "0.95rem", color: "#ffffff", fontFamily: "var(--font-title)" }}>{law.section}</strong>
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                          <span style={{ fontSize: "0.85rem", fontWeight: 700, color: "var(--secondary)" }}>
                            {(law.score * 100).toFixed(1)}% Match
                          </span>
                          <span className="relevance-score" style={{ fontSize: "0.8rem", padding: "0.2rem 0.5rem" }}>
                            {law.score.toFixed(4)} pts
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              <details className="raw-results-toggle" style={{ marginTop: "2rem", padding: "1rem", background: "rgba(255,255,255,0.02)", borderRadius: "8px", border: "1px solid var(--border)" }}>
                <summary style={{ cursor: "pointer", fontWeight: 600, color: "var(--text-secondary)", fontFamily: "var(--font-title)" }}>
                  View Raw Extracted Clauses (Advanced)
                </summary>
                <div className="results-list" style={{ marginTop: "1rem" }}>
                  {searchResults.results.map((result, idx) => {
                    const { section, statement } = parseLawDetails(result.text);
                    return (
                      <article key={idx} className="result-card">
                        <div className="result-card-header">
                          <h3 className="act-title">{result.act_name}</h3>
                          <span className="relevance-score">
                            Score: {result.faiss_score.toFixed(4)}
                          </span>
                        </div>

                        <div style={{ marginTop: "0.25rem", marginBottom: "0.5rem" }}>
                          <strong style={{ fontSize: "1.05rem", color: "var(--secondary)", fontFamily: "var(--font-title)" }}>
                            {section}
                          </strong>
                        </div>

                        <div className="result-meta">
                          <div className="meta-tag" title={result.document_name}>
                            <FileText className="meta-icon" />
                            <span>Doc: {result.document_name}</span>
                          </div>
                          <div className="meta-tag">
                            <FileText className="meta-icon" />
                            <span>File: {result.filename}</span>
                          </div>
                          <div className="meta-tag">
                            <Database className="meta-icon" />
                            <span>Page {result.page_num}</span>
                          </div>
                          <div className="meta-tag">
                            <Sparkles className="meta-icon" />
                            <span>Chunk #{result.chunk_index}</span>
                          </div>
                        </div>

                        <div className="result-snippet" style={{ fontStyle: "normal", whiteSpace: "pre-wrap" }}>
                          {result.text
                            ? result.text
                                .split(/\n{2,}/)
                                .map((para) => para.replace(/\n/g, " ").replace(/\s+/g, " ").trim())
                                .join("\n\n")
                            : ""}
                        </div>
                      </article>
                    );
                  })}
                </div>
              </details>
            </>
          )}

          {searchResults && searchResults.results?.length === 0 && (
            <div className="empty-state">
              <AlertCircle className="empty-icon" />
              <h3>No Matches Found</h3>
              <p>No matching act clauses were found. Make sure your Acts PDF database is ingested.</p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
