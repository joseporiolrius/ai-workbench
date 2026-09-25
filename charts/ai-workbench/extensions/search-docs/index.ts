/**
 * search_docs — course retrieval tool for the pi coding agent inside pi-web-ui (S12).
 *
 * The chart mounts this directory at $PI_CODING_AGENT_DIR/extensions/search-docs/ when
 * extensions.search_docs.enabled is true; pi loads index.ts at session start (no build step).
 * The MODEL decides whether to call the tool, so general questions are answered without it.
 *
 * Server-side only: the question is embedded through the course gateway with the fixed query
 * alias course-embed (COURSE_VIRTUAL_KEY from the pod environment, never sent to the browser
 * or printed), then searched in Qdrant through the LIVE alias (default study_guides).
 * Failures throw, so the UI shows a red tool call and the model is told retrieval failed.
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const QUERY_MODEL = "course-embed"; // fixed by the course contract, like the evaluator

interface Config {
  collection: string;      // live Qdrant alias
  qdrantUrl: string;       // e.g. http://workbench-qdrant:6333
  gatewayBaseUrl: string;  // OpenAI-compatible, e.g. https://litellm.joor.net/v1
  topK: number;
  keyEnv: string;          // env var holding the course key
}

function loadConfig(): Config {
  const dir = process.env.PI_CODING_AGENT_DIR ?? "/app/.pi-config";
  const path = process.env.SEARCH_DOCS_CONFIG ?? join(dir, "extensions", "search-docs", "config.json");
  const raw = JSON.parse(readFileSync(path, "utf8"));
  const config: Config = {
    collection: String(raw.collection ?? "study_guides"),
    qdrantUrl: String(raw.qdrantUrl ?? "http://127.0.0.1:6333").replace(/\/$/, ""),
    gatewayBaseUrl: String(raw.gatewayBaseUrl ?? "").replace(/\/$/, ""),
    topK: Number(raw.topK ?? 3),
    keyEnv: String(raw.keyEnv ?? "COURSE_VIRTUAL_KEY"),
  };
  if (!config.gatewayBaseUrl) throw new Error(`search_docs: gatewayBaseUrl missing in ${path}`);
  if (!Number.isInteger(config.topK) || config.topK < 1 || config.topK > 20) {
    throw new Error(`search_docs: topK must be an integer in 1..20, got ${raw.topK}`);
  }
  return config;
}

function mask(text: string, key: string): string {
  return key ? text.split(key).join("sk-***") : text;
}

async function call(url: string, body: unknown, what: string, key: string, signal?: AbortSignal,
                    headers: Record<string, string> = {}): Promise<any> {
  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST", signal,
      headers: { "content-type": "application/json", ...headers },
      body: JSON.stringify(body),
    });
  } catch (error) {
    throw new Error(`search_docs: ${what} unreachable (${(error as Error).message})`);
  }
  if (!response.ok) {
    const detail = mask(await response.text(), key).slice(0, 200);
    throw new Error(`search_docs: ${what} returned HTTP ${response.status}: ${detail}`);
  }
  return response.json();
}

export default function (pi: ExtensionAPI) {
  const config = loadConfig();

  pi.registerTool({
    name: "search_docs",
    label: "Search course docs",
    description:
      "Search the DBAI DevOps course study guides (sessions 1-12: labs, tools, commands, repositories, " +
      "policies and failure modes of THIS course). Returns the most relevant passages with their source " +
      "file. Use it for questions about the course; do not use it for general knowledge.",
    promptSnippet: "search_docs: search this course's study guides; returns cited passages",
    promptGuidelines: [
      "Call search_docs when the user asks about this DevOps course: its sessions, labs, repositories, tools, commands or policies.",
      "Answer general-knowledge questions directly, without calling search_docs.",
      "When you use search_docs results, cite the source path (docs/study-guides/...) of each passage you rely on; if the passages do not contain the answer, say so instead of guessing.",
    ],
    parameters: Type.Object({
      query: Type.String({ description: "The question or keywords to search for" }),
    }),
    async execute(_toolCallId, params, signal) {
      const key = process.env[config.keyEnv] ?? "";
      if (!key) throw new Error(`search_docs: ${config.keyEnv} is not set in the UI container`);

      const embedding = await call(`${config.gatewayBaseUrl}/embeddings`, { model: QUERY_MODEL, input: [params.query] },
        `gateway embeddings (${QUERY_MODEL})`, key, signal, { authorization: `Bearer ${key}` });
      const vector = embedding?.data?.[0]?.embedding;
      if (!Array.isArray(vector)) throw new Error("search_docs: gateway returned no embedding");

      const found = await call(`${config.qdrantUrl}/collections/${encodeURIComponent(config.collection)}/points/query`,
        { query: vector, limit: config.topK, with_payload: true },
        `Qdrant collection/alias '${config.collection}'`, key, signal);
      const points: any[] = found?.result?.points ?? [];
      if (points.length === 0) {
        return { content: [{ type: "text", text: `No passages found in '${config.collection}'.` }],
                 details: { collection: config.collection, hits: [] } };
      }
      const hits = points.map((p, i) => ({
        rank: i + 1,
        score: Math.round(p.score * 1000) / 1000,
        source: p.payload?.source,
        section: p.payload?.section,
        text: String(p.payload?.text ?? ""),
      }));
      const text = hits
        .map((h) => `[${h.rank}] ${h.source} § ${h.section} (score ${h.score})\n${h.text}`)
        .join("\n\n");
      return {
        content: [{ type: "text", text: `${text}\n\nCite the source path of every passage you use.` }],
        details: {
          collection: config.collection, queryModel: QUERY_MODEL,
          corpusRevision: points[0]?.payload?.corpus_revision, corpusHash: points[0]?.payload?.corpus_hash,
          hits: hits.map(({ text: _t, ...rest }) => rest),
        },
      };
    },
  });
}
