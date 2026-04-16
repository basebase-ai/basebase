/**
 * Utilities for parsing document/artifact responses when API proxies
 * accidentally return a SPA HTML shell instead of direct JSON/text.
 */

type JsonRecord = Record<string, unknown>;

function tryParseJson(raw: string): unknown | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  if (!(trimmed.startsWith("{") || trimmed.startsWith("["))) return null;
  try {
    return JSON.parse(trimmed) as unknown;
  } catch {
    return null;
  }
}

function extractJsonFromHtmlCandidates(html: string): unknown | null {
  if (typeof window === "undefined" || typeof DOMParser === "undefined") {
    return null;
  }
  const doc = new DOMParser().parseFromString(html, "text/html");
  const candidates: string[] = [];

  const scriptNodes = Array.from(doc.querySelectorAll("script"));
  for (const script of scriptNodes) {
    const scriptType = (script.getAttribute("type") ?? "").toLowerCase();
    if (script.src) continue;
    if (scriptType === "" || scriptType === "application/json") {
      candidates.push(script.textContent ?? "");
    }
  }

  const preNodes = Array.from(doc.querySelectorAll("pre"));
  for (const pre of preNodes) {
    candidates.push(pre.textContent ?? "");
  }

  for (const candidate of candidates) {
    const parsed = tryParseJson(candidate);
    if (parsed !== null) {
      return parsed;
    }
  }

  return null;
}

export function parsePossiblySpaWrappedJson(rawBody: string): unknown | null {
  const direct = tryParseJson(rawBody);
  if (direct !== null) {
    return direct;
  }
  const lower = rawBody.toLowerCase();
  const looksLikeHtml = lower.includes("<html") || lower.includes("<!doctype html");
  if (!looksLikeHtml) {
    return null;
  }
  return extractJsonFromHtmlCandidates(rawBody);
}

function extractContentFromJsonPayload(payload: unknown): string | null {
  if (!payload || typeof payload !== "object") return null;
  const obj = payload as JsonRecord;
  if (typeof obj.content === "string") return obj.content;
  if (obj.data && typeof obj.data === "object") {
    const nested = obj.data as JsonRecord;
    if (typeof nested.content === "string") return nested.content;
  }
  return null;
}

export function extractDocumentTextFromBody(rawBody: string): string {
  const parsed = parsePossiblySpaWrappedJson(rawBody);
  const extracted = extractContentFromJsonPayload(parsed);
  if (extracted !== null) {
    console.info("[documentPayload] Extracted artifact content from JSON/SPA wrapper payload.");
    return extracted;
  }
  return rawBody;
}

