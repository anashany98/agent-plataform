/**
 * Sección Documentos: base de conocimiento (RAG) indexada en la instalación.
 *
 * Extraída de `App.tsx`; recibe `token` y `refreshRevision` como props.
 */

import { useEffect, useState } from "react";
import { api } from "../apiHelpers";
import { formatDate } from "../appFormat";
import type { DocumentRow } from "../appTypes";

export function DocumentsSection({
  token,
  refreshRevision,
}: {
  token: string;
  refreshRevision: number;
}) {
  const [rows, setRows] = useState<DocumentRow[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setError("");
    api<{ documents: DocumentRow[] }>("/rag/documents", token)
      .then((data) => {
        if (!cancelled) {
          setRows(data.documents);
          setError("");
        }
      })
      .catch((err) => {
        if (!cancelled)
          setError(
            err instanceof Error
              ? err.message
              : "No se pudieron cargar los documentos",
          );
      });
    return () => {
      cancelled = true;
    };
  }, [refreshRevision, token]);

  return (
    <section id="documentos" className="panel" aria-label="Documentos RAG">
      <div className="panel-heading">
        <div>
          <p>Conocimiento</p>
          <h2>Documentos</h2>
        </div>
        <span className="counter">{rows?.length ?? 0}</span>
      </div>
      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}
      {!error && rows === null && (
        <div className="empty-state">Cargando documentos…</div>
      )}
      {!error && rows !== null && rows.length === 0 && (
        <div className="empty-state">
          No hay documentos indexados en esta instalación.
        </div>
      )}
      {!error && rows !== null && rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <caption className="sr-only">Documentos indexados</caption>
            <thead>
              <tr>
                <th scope="col">Archivo</th>
                <th scope="col">Clasificación</th>
                <th scope="col">Hallazgos DLP</th>
                <th scope="col">Alta</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>{row.file_name}</td>
                  <td>{row.classification}</td>
                  <td>
                    {row.dlp_findings.length > 0
                      ? row.dlp_findings.join(", ")
                      : "—"}
                  </td>
                  <td>{formatDate(row.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
