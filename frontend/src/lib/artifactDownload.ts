import { API_BASE, getAuthenticatedRequestHeaders } from "./api";

/**
 * Download an artifact as Markdown or PDF (same behavior as ArtifactViewer).
 */
export async function downloadArtifactAsFile(
  artifactId: string,
  format: "markdown" | "pdf",
  baseFilename: string,
): Promise<void> {
  const dlHeaders = await getAuthenticatedRequestHeaders();
  const response = await fetch(
    `${API_BASE}/artifacts/${artifactId}/download?format=${format}`,
    { headers: dlHeaders },
  );
  if (!response.ok) {
    throw new Error("Failed to download artifact");
  }

  const blob = await response.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  const extension = format === "pdf" ? ".pdf" : ".md";
  const stripped = baseFilename.replace(/\.[^/.]+$/, "");
  a.download = stripped + extension;
  document.body.appendChild(a);
  a.click();
  window.URL.revokeObjectURL(url);
  document.body.removeChild(a);
}
