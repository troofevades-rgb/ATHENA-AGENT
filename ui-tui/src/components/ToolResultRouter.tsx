/**
 * Per-tool result renderers.
 *
 * The transcript stores tool results as ``"{toolName} → {payload}"``.
 * By default we render the raw payload. For tools where we KNOW the
 * payload shape (search_x returns a list of posts, Read returns
 * numbered file lines, etc.) we can do much better than dumping the
 * JSON inline.
 *
 * Add new renderers to ``_REGISTRY`` keyed by tool name. Each
 * renderer takes the raw payload (post-arrow) and returns either
 * JSX or ``null`` to fall through to the default plain render.
 *
 * Design choice: parsing is best-effort. If a payload doesn't match
 * the expected shape (e.g. search_x returned ``{"available":false}``
 * with an error), the renderer returns ``null`` and the default
 * renderer takes over. Never crash the transcript on a malformed
 * tool result.
 */

import React from "react";
import { Box, Text } from "ink";

import type { ThemePalette } from "../transport/protocol.js";

interface RouteContext {
  palette: ThemePalette | undefined;
}

type ToolRenderer = (
  payload: string,
  ctx: RouteContext,
) => React.JSX.Element | null;

// ---------------------------------------------------------------------------
// search_x — render social-search results as a compact feed
// ---------------------------------------------------------------------------

interface SearchXPayload {
  available: boolean;
  provider?: string | null;
  results?: Array<{
    author?: string;
    text?: string;
    timestamp?: string;
    url?: string;
  }>;
  reason?: string | null;
}

const _renderSearchX: ToolRenderer = (payload, { palette }) => {
  let data: SearchXPayload;
  try {
    data = JSON.parse(payload);
  } catch {
    return null; // fall through to default
  }
  if (!data.available) {
    return (
      <Box flexDirection="column">
        <Text color={palette?.accent_dim ?? "yellow"}>
          ↳  search_x  <Text color={palette?.primary_faint ?? "gray"}>
            (unavailable: {data.reason || "no reason given"})
          </Text>
        </Text>
      </Box>
    );
  }
  const results = data.results || [];
  const accent = palette?.accent ?? "cyan";
  const dim = palette?.primary_dim ?? "gray";
  const faint = palette?.primary_faint ?? "gray";
  return (
    <Box flexDirection="column">
      <Box>
        <Text color={palette?.accent_dim ?? "yellow"}>↳  search_x</Text>
        <Text color={faint}>
          {"  "}
          {results.length} result{results.length === 1 ? "" : "s"}
          {data.provider ? ` via ${data.provider}` : ""}
        </Text>
      </Box>
      {results.slice(0, 8).map((post, i) => {
        const author = post.author ? `@${post.author}` : "(unknown)";
        const ts = _formatTimestamp(post.timestamp);
        const text = (post.text || "").replace(/\s+/g, " ").trim();
        return (
          <Box key={i} flexDirection="column" marginTop={i === 0 ? 0 : 0}>
            <Box>
              <Text color={accent} bold>{author}</Text>
              {ts && <Text color={faint}>{"  "}{ts}</Text>}
            </Box>
            <Text color={dim}>
              {"   "}
              {_truncate(text, 200)}
            </Text>
          </Box>
        );
      })}
      {results.length > 8 && (
        <Text color={faint}>
          {"   "}
          … +{results.length - 8} more
        </Text>
      )}
    </Box>
  );
};

// ---------------------------------------------------------------------------
// Read — render file content with subtle line-number styling
// ---------------------------------------------------------------------------

const _renderRead: ToolRenderer = (payload, { palette }) => {
  // Read output is formatted as ``\t1\tline content\n  2\tline content\n...``
  // (cat -n style). Render the line numbers in dim color, content in default.
  // Bail if it doesn't match the expected shape.
  const lines = payload.split("\n");
  const matched = lines.filter((ln) => /^\s*\d+\t/.test(ln));
  if (matched.length === 0 || matched.length < lines.length * 0.7) {
    return null; // not the expected shape, let default render
  }
  const faint = palette?.primary_faint ?? "gray";
  const accent_dim = palette?.accent_dim ?? "yellow";
  return (
    <Box flexDirection="column">
      <Text color={accent_dim}>↳  Read</Text>
      {lines.slice(0, 30).map((ln, i) => {
        const m = ln.match(/^(\s*\d+)\t(.*)$/);
        if (!m) {
          return <Text key={i} color={faint}>{ln}</Text>;
        }
        return (
          <Box key={i}>
            <Text color={faint}>{m[1]}{"  "}</Text>
            <Text>{m[2]}</Text>
          </Box>
        );
      })}
      {lines.length > 30 && (
        <Text color={faint}>… +{lines.length - 30} more lines</Text>
      )}
    </Box>
  );
};

// ---------------------------------------------------------------------------
// Registry + entry point
// ---------------------------------------------------------------------------

const _REGISTRY: Record<string, ToolRenderer> = {
  search_x: _renderSearchX,
  Read: _renderRead,
};

/**
 * Render a tool result with a per-tool renderer if one is registered;
 * otherwise return ``null`` so the caller falls back to its default
 * plain-text rendering.
 *
 * The line ``content`` shape is ``"{toolName} → {payload}"``.
 */
export function renderToolResult(
  content: string,
  ctx: RouteContext,
): React.JSX.Element | null {
  const arrowIdx = content.indexOf(" → ");
  if (arrowIdx < 0) return null;
  const toolName = content.slice(0, arrowIdx);
  const payload = content.slice(arrowIdx + 3);
  const renderer = _REGISTRY[toolName];
  if (!renderer) return null;
  try {
    return renderer(payload, ctx);
  } catch {
    // A buggy renderer must never break the transcript — fall
    // through to the default plain render.
    return null;
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _truncate(s: string, max: number): string {
  if (s.length <= max) return s;
  return s.slice(0, max - 1) + "…";
}

function _formatTimestamp(ts: string | undefined): string {
  if (!ts) return "";
  // Try to extract just date + HH:MM from ISO timestamps;
  // pass through otherwise.
  const m = ts.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/);
  if (m) return `${m[1]} ${m[2]}`;
  return ts.slice(0, 30);
}
