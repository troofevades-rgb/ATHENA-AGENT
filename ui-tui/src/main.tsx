/**
 * athena Ink TUI — entry point.
 *
 * Post step 8 (component refactor): App is a thin orchestrator.
 * It wires:
 *   - transport (gateway client) → events
 *   - events → reducer dispatch
 *   - reducer state → <Transcript> + <Composer>
 *   - keyboard → useLineEditor + dispatched UI actions
 *
 * The visual layout, transcript rendering, composer rendering, and
 * input editing all live in their own files (see ./components/ and
 * ./hooks/). This file should stay small (< 200 lines).
 */

import { Box, render, Text, useApp, useInput } from "ink";
import React, { useCallback, useEffect, useReducer, useRef, useState } from "react";

import { Composer } from "./components/Composer.js";
import { PulsingCursor } from "./components/PulsingCursor.js";
import { Transcript } from "./components/Transcript.js";
import { useInputHistory } from "./hooks/useInputHistory.js";
import { useLineEditor } from "./hooks/useLineEditor.js";
import {
  completionText, matchSlashCommands,
} from "./components/SlashPopup.js";
import {
  applyAtMentionCompletion, findActiveAtMention, matchWorkspaceFiles,
} from "./lib/workspaceFiles.js";
import { useBracketedPaste } from "./hooks/useBracketedPaste.js";
import { useStdoutSize } from "./hooks/useStdoutSize.js";
import { useTokenRate } from "./hooks/useTokenRate.js";
import { initialTuiState } from "./state/types.js";
import { reducer } from "./state/reducer.js";
import { connectGateway } from "./transport/client.js";
import type {
  ConfirmRequestEvent, Event, StatusFlashEvent,
} from "./transport/protocol.js";

function App(): React.JSX.Element {
  const { exit } = useApp();
  // useStdoutSize subscribes to stdout's 'resize' event so the whole
  // tree re-renders when the terminal resizes; useStdout alone would
  // give a stale snapshot until something else triggered a re-render.
  const { cols, rows } = useStdoutSize();
  const [state, dispatch] = useReducer(reducer, initialTuiState);
  const editor = useLineEditor();
  const history = useInputHistory();
  const [client] = useState(() => connectGateway());
  // Slash-completion popup selection index. Reset whenever the
  // popup opens or the filter shrinks the match set.
  const [slashSelectedIdx, setSlashSelectedIdx] = useState(0);
  // Reverse-search state. When non-null we're in search mode:
  // the composer shows the query + best match; typing extends
  // the query; Ctrl+R steps to the next older match.
  const [reverseSearch, setReverseSearch] = useState<{
    query: string; match: string | null;
  } | null>(null);

  // Replace the editor buffer with ``text`` (used by history nav).
  // Pure operation on the existing editor API: clear then insert.
  const setEditorTo = (text: string): void => {
    editor.clear();
    if (text) editor.insert(text);
  };

  // Derived: is the slash popup open right now?
  const slashOpen = editor.text.startsWith("/");
  const slashMatches = slashOpen ? matchSlashCommands(editor.text) : [];

  // Derived: is the user typing an @-mention right now?
  const atMention = findActiveAtMention(editor.text, editor.cursor);
  const cwd = state.banner?.cwd ?? "";
  const atMatches = atMention !== null && cwd
    ? matchWorkspaceFiles(cwd, atMention.query, 8)
    : [];
  const atOpen = atMention !== null && atMatches.length > 0;
  const [atSelectedIdx, setAtSelectedIdx] = useState(0);

  // AskUserQuestion overlay — per-question selection + focus index.
  // Reset whenever a new ask request arrives (new request_id).
  const [askFocusedIdx, setAskFocusedIdx] = useState(0);
  const [askSelections, setAskSelections] = useState<Array<number | number[] | null>>([]);
  const lastAskReqId = useRef<string | null>(null);
  if (state.askReq && state.askReq.request_id !== lastAskReqId.current) {
    lastAskReqId.current = state.askReq.request_id;
    setAskFocusedIdx(0);
    setAskSelections(
      state.askReq.questions.map(
        (q) => (q.multiSelect ? [] : null),
      ),
    );
  } else if (!state.askReq && lastAskReqId.current !== null) {
    lastAskReqId.current = null;
  }
  // Token-per-second tracker for the StatusBar sparkline. Sum
  // upload + download tokens for total throughput; useTokenRate
  // computes rolling deltas over a 30s window.
  const totalTokens =
    (state.status?.tokens_up ?? 0) + (state.status?.tokens_down ?? 0);
  const tokenRate = useTokenRate(totalTokens, { buckets: 16, windowSec: 30 });

  // Flash queue: rapid ui.info() bursts used to overwrite each
  // other; queue them with a minimum dwell time per entry.
  const flashQueue = useRef<StatusFlashEvent[]>([]);
  const flashTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const FLASH_MIN_DWELL_MS = 800;
  const pumpFlashQueue = (): void => {
    if (flashTimer.current !== null) return;
    const next = flashQueue.current.shift();
    if (!next) return;
    const ttl = Math.max(FLASH_MIN_DWELL_MS, (next.ttl_seconds ?? 3) * 1000);
    flashTimer.current = setTimeout(() => {
      flashTimer.current = null;
      dispatch({ type: "DISMISS_FLASH" });
      pumpFlashQueue();
    }, ttl);
  };

  // Last stream.delta arrival timestamp — drives the pulsing cursor.
  const lastDeltaAt = useRef<number | null>(null);

  // ----- gateway events ---------------------------------------------
  useEffect(() => {
    const unsub = client.onEvent((event: Event) => {
      if (event.type === "exit") {
        unsub();
        process.exit(0);
      }
      if (event.type === "status.flash") {
        flashQueue.current.push(event as StatusFlashEvent);
        pumpFlashQueue();
      }
      if (event.type === "confirm.request") {
        process.stderr.write("\x07");
      }
      if (event.type === "stream.delta") {
        lastDeltaAt.current = performance.now();
      }
      if (event.type === "stream.end" || event.type === "stream.start") {
        lastDeltaAt.current = event.type === "stream.start"
          ? performance.now() : null;
      }
      dispatch({ type: "EVENT", event });
    });
    const unsubErr = client.onProtocolError((event) => {
      dispatch({ type: "SET_PROTOCOL_ERROR", event });
    });
    return () => {
      unsub();
      unsubErr();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);

  // ----- resize → gateway -----
  // When the terminal resizes, tell the gateway so it can re-render
  // the owl photo at the new width. The owl pixels are baked
  // Python-side at build_banner() time; the rest of the layout is
  // sized client-side from termCols and reflows for free.
  //
  // Debounced 250ms so dragging the window edge doesn't fire a
  // banner-rebuild per intermediate width. The first send is
  // skipped on initial mount (the gateway already shipped a banner
  // for the spawn-time size; we only want to send when the size
  // actually CHANGES).
  const lastSentSize = useRef<{ cols: number; rows: number } | null>(null);
  const resizeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    // Skip the initial render — gateway already has the right
    // banner for the spawn-time size. Record current so we only
    // send on actual change.
    if (lastSentSize.current === null) {
      lastSentSize.current = { cols, rows };
      return;
    }
    // No-op when nothing changed (e.g. unrelated re-render).
    if (
      lastSentSize.current.cols === cols
      && lastSentSize.current.rows === rows
    ) {
      return;
    }
    if (resizeTimer.current !== null) clearTimeout(resizeTimer.current);
    resizeTimer.current = setTimeout(() => {
      resizeTimer.current = null;
      lastSentSize.current = { cols, rows };
      client.sendCommand({ type: "resize", cols, rows });
    }, 250);
    return () => {
      if (resizeTimer.current !== null) {
        clearTimeout(resizeTimer.current);
        resizeTimer.current = null;
      }
    };
  }, [cols, rows, client]);

  // Scrolling is handled by the terminal's native scrollback — the
  // transcript renders through Ink's <Static> (see Transcript.tsx), so
  // there's no app-managed scroll offset, no mouse capture, and no
  // ConPTY raw-mode hazard. Mouse wheel / selection / copy / find all
  // work because the content lives in the terminal, not a viewport.

  // Bracketed paste: pasted content arrives as one insertion instead
  // of being fed through useInput as N keystrokes. Critical for
  // multi-line pastes — without it, a stray "/" or "\n" mid-paste
  // would fire commands.
  useBracketedPaste((pasted) => {
    // Drop into the editor as a single insert. Normalize CRLF so
    // Windows clipboard contents don't pepper the buffer with extra
    // carriage returns.
    const normalized = pasted.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    history.reset();
    setSlashSelectedIdx(0);
    editor.insert(normalized);
  });

  // ----- keyboard ----------------------------------------------------
  useInput((typedChar, key) => {
    // AskUserQuestion overlay claims the entire keyboard until
    // the user answers or cancels. Handled BEFORE confirm because
    // both can theoretically be active; ask is rarer + more
    // disruptive when missed.
    if (state.askReq) {
      const req = state.askReq;
      const qIdx = Math.min(askFocusedIdx, req.questions.length - 1);
      const focusedQ = req.questions[qIdx];
      const optCount = focusedQ.options.length + 1;  // +1 for "Other"
      const multi = !!focusedQ.multiSelect;

      if (key.escape) {
        client.sendCommand({
          type: "ask_question.reply",
          request_id: req.request_id,
          answers: [],
          cancelled: true,
        });
        dispatch({ type: "DISMISS_ASK" });
        return;
      }
      if (key.return) {
        // Build the answers list — one entry per question, formatted
        // using the selection state.
        const answers = req.questions.map((q, i) => {
          const sel = askSelections[i];
          const q_text = q.question;
          if (sel === null || sel === undefined) return { question: q_text, answer: "(no answer)" };
          const labelFor = (idx: number): string => {
            if (idx < q.options.length) return q.options[idx].label;
            return "Other";  // custom slot, no free-form input today
          };
          if (Array.isArray(sel)) {
            if (sel.length === 0) return { question: q_text, answer: "(no answer)" };
            return { question: q_text, answer: sel.map(labelFor).join(", ") };
          }
          return { question: q_text, answer: labelFor(sel) };
        });
        client.sendCommand({
          type: "ask_question.reply",
          request_id: req.request_id,
          answers,
          cancelled: false,
        });
        dispatch({ type: "DISMISS_ASK" });
        return;
      }
      if (key.tab) {
        setAskFocusedIdx((i) => (i + 1) % req.questions.length);
        return;
      }
      if (key.upArrow) {
        setAskSelections((prev) => {
          const next = [...prev];
          const cur = next[qIdx];
          if (multi) {
            // Up/down on multi doesn't move selection; use Space to toggle
            return prev;
          }
          const curIdx = typeof cur === "number" ? cur : 0;
          next[qIdx] = (curIdx - 1 + optCount) % optCount;
          return next;
        });
        return;
      }
      if (key.downArrow) {
        setAskSelections((prev) => {
          const next = [...prev];
          const cur = next[qIdx];
          if (multi) return prev;
          const curIdx = typeof cur === "number" ? cur : -1;
          next[qIdx] = (curIdx + 1) % optCount;
          return next;
        });
        return;
      }
      if (multi && typedChar === " ") {
        // Space toggles the currently-highlighted option in
        // multi-select. We track the "cursor" inside the array's
        // first entry — simpler model than separate focus.
        // Actually: for multi we let number keys do the toggling.
        return;
      }
      // 1-9: pick option (single-select) or toggle (multi-select)
      if (typedChar && /^[1-9]$/.test(typedChar)) {
        const n = parseInt(typedChar, 10) - 1;
        if (n < optCount) {
          setAskSelections((prev) => {
            const next = [...prev];
            const cur = next[qIdx];
            if (multi) {
              const arr = Array.isArray(cur) ? [...cur] : [];
              const at = arr.indexOf(n);
              if (at >= 0) arr.splice(at, 1);
              else arr.push(n);
              next[qIdx] = arr;
            } else {
              next[qIdx] = n;
            }
            return next;
          });
        }
        return;
      }
      // Swallow any other key — ask overlay is exclusive while open
      return;
    }
    // Confirm overlay claims all keys until answered.
    if (state.confirmReq) {
      const ch = (typedChar || "").toLowerCase();
      let accepted: boolean | null = null;
      if (ch === "y") accepted = true;
      else if (ch === "n") accepted = false;
      else if (key.return) accepted = state.confirmReq.default;
      else if (key.escape) accepted = false;
      if (accepted !== null) {
        const req: ConfirmRequestEvent = state.confirmReq;
        client.sendCommand({
          type: "confirm.reply",
          request_id: req.request_id,
          accepted,
        });
        dispatch({ type: "DISMISS_CONFIRM" });
      }
      return;
    }

    // Reverse-search mode owns the entire keyboard until accepted
    // or cancelled. Handled here, before any other binding, so
    // Esc / Enter / typed chars / backspace all do search-specific
    // things instead of their normal action.
    if (reverseSearch !== null) {
      if (key.escape) {
        const draftRestored = history.cancelSearch();
        setReverseSearch(null);
        editor.clear();
        if (draftRestored) editor.insert(draftRestored);
        return;
      }
      if (key.return) {
        // Accept the current match (or fall back to the query if
        // no match was found — same as shell behavior).
        const text = reverseSearch.match ?? reverseSearch.query;
        history.acceptSearch();
        setReverseSearch(null);
        editor.clear();
        if (text) editor.insert(text);
        return;
      }
      if (key.backspace || key.delete) {
        const newQuery = reverseSearch.query.slice(0, -1);
        if (!newQuery) {
          // Empty query → exit search, restore draft
          const draftRestored = history.cancelSearch();
          setReverseSearch(null);
          editor.clear();
          if (draftRestored) editor.insert(draftRestored);
          return;
        }
        const match = history.searchPrev(newQuery, editor.text);
        setReverseSearch({ query: newQuery, match });
        return;
      }
      if (typedChar && !key.ctrl && !key.meta) {
        const newQuery = reverseSearch.query + typedChar;
        const match = history.searchPrev(newQuery, editor.text);
        setReverseSearch({ query: newQuery, match });
        return;
      }
      // Ctrl+R re-handled below (steps to next older match); fall
      // through so the existing binding fires.
    }

    // Scrollback is the terminal's job now (Static render) — no
    // PageUp/PageDown/Shift+arrow scroll bindings. Ctrl+U with a
    // non-empty buffer still falls through to the readline kill-to-start
    // binding below.

    // Tab — when the slash popup is open with at least one match,
    // accept the selected completion. Replaces the buffer with the
    // full command name + a space so the user can keep typing args.
    if (key.tab && slashOpen && slashMatches.length > 0) {
      const pick = slashMatches[Math.min(slashSelectedIdx, slashMatches.length - 1)];
      setEditorTo(completionText(pick));
      setSlashSelectedIdx(0);
      return;
    }
    // Tab — when the @-mention popup is open, accept the selected
    // file path. Replaces the @partial fragment with @<full-path>.
    if (key.tab && atOpen && atMention !== null) {
      const pick = atMatches[Math.min(atSelectedIdx, atMatches.length - 1)];
      const { text: nt, cursor: nc } = applyAtMentionCompletion(
        editor.text, editor.cursor, pick,
      );
      editor.clear();
      if (nt) editor.insert(nt);
      // After clear+insert the cursor is at the END of the inserted
      // text. That happens to match ``nc`` for our completion shape
      // (we always insert at the cursor and advance past the
      // replacement), so no extra cursor adjustment is needed.
      void nc;
      setAtSelectedIdx(0);
      return;
    }

    if (key.return) {
      // Shift+Enter inserts a literal newline so the user can
      // compose multi-line prompts. Plain Enter still sends. This
      // matches Claude Code semantics.
      if (key.shift) {
        editor.insert("\n");
        history.reset();
        setSlashSelectedIdx(0);
        return;
      }
      if (editor.text.length > 0) {
        client.sendCommand({ type: "user.input", text: editor.text });
        dispatch({ type: "USER_INPUT_SENT" });
        dispatch({ type: "APPEND_SEPARATOR", content: turnSeparator() });
        history.commit(editor.text);
        editor.clear();
        setSlashSelectedIdx(0);
      }
      return;
    }
    // Up/down arrow without shift: popups get priority when open;
    // otherwise navigate input history. Shift+arrow is already bound
    // to scrollback above. Priority: slash popup > @-mention popup
    // > history.
    if (key.upArrow) {
      if (slashOpen && slashMatches.length > 0) {
        setSlashSelectedIdx((i) =>
          (i - 1 + slashMatches.length) % slashMatches.length,
        );
        return;
      }
      if (atOpen) {
        setAtSelectedIdx((i) =>
          (i - 1 + atMatches.length) % atMatches.length,
        );
        return;
      }
      const recalled = history.navigatePrev(editor.text);
      if (recalled !== null) setEditorTo(recalled);
      return;
    }
    if (key.downArrow) {
      if (slashOpen && slashMatches.length > 0) {
        setSlashSelectedIdx((i) => (i + 1) % slashMatches.length);
        return;
      }
      if (atOpen) {
        setAtSelectedIdx((i) => (i + 1) % atMatches.length);
        return;
      }
      const recalled = history.navigateNext();
      if (recalled !== null) setEditorTo(recalled);
      return;
    }
    if (key.escape) {
      // Interrupt the in-flight turn but stay in the session — the
      // Python side raises KeyboardInterrupt on the main thread,
      // run_turn unwinds, and the REPL returns to recv_command()
      // ready for the next prompt. Ctrl+C is what actually exits.
      client.sendCommand({ type: "interrupt" });
      return;
    }
    if (key.ctrl && typedChar === "c") {
      client.sendCommand({ type: "interrupt" });
      exit();
      return;
    }
    // Ctrl+D at empty buffer exits the session -- standard
    // POSIX-shell convention (bash, python REPL, node). The earlier
    // Ctrl+D-empty-buffer binding (scroll-down at line 415) only
    // fires when text is non-empty after this guard, so the
    // pageDown binding above already covers the scroll case via
    // PageDown directly.
    if (key.ctrl && typedChar === "d" && editor.text === "") {
      client.sendCommand({ type: "interrupt" });
      exit();
      return;
    }

    // Cursor / editing dispatched via useLineEditor.
    if (key.leftArrow) return editor.moveLeft();
    if (key.rightArrow) return editor.moveRight();
    if ((key.ctrl && typedChar === "a") || (key as { home?: boolean }).home) {
      return editor.toStart();
    }
    if ((key.ctrl && typedChar === "e") || (key as { end?: boolean }).end) {
      return editor.toEnd();
    }
    if (key.ctrl && typedChar === "u") return editor.killToStart();
    if (key.ctrl && typedChar === "k") return editor.killToEnd();
    if (key.ctrl && typedChar === "w") return editor.killWordLeft();
    // Ctrl+R — reverse-incremental history search. First press
    // enters search mode with whatever's in the buffer as the
    // initial query. Subsequent Ctrl+R presses step to the
    // next-older match for the same query.
    if (key.ctrl && typedChar === "r") {
      const q = reverseSearch?.query ?? editor.text;
      const match = history.searchPrev(q, editor.text);
      setReverseSearch({ query: q, match });
      return;
    }
    // Backspace: handle both BS (0x08) and DEL (0x7F). Many
    // Windows terminals (Windows Terminal, PowerShell, conhost)
    // send DEL for the Backspace key, which Ink reports as
    // key.delete. Forward-delete is rarely used in a one-line
    // prompt, and sacrificing it for working backspace on
    // Windows is the right tradeoff.
    if (key.backspace || key.delete) {
      history.reset();
      return editor.backspace();
    }
    if (typedChar && !key.ctrl && !key.meta) {
      // Any user-typed character drops us out of history-nav mode so
      // the next ↑ re-stashes the new draft.
      history.reset();
      // Also reset the popup selections — the filter is about to
      // change, so keeping a stale index would be confusing.
      setSlashSelectedIdx(0);
      setAtSelectedIdx(0);
      editor.insert(typedChar);
    }
  });

  // ----- layout -----
  // cols/rows come from useStdoutSize() at the top of the component
  // so they're always current (subscribes to 'resize' + post-mount
  // re-sync for the Windows spawn-timing case).
  //
  // No windowing / visibleBudget: committed history flows into the
  // terminal via <Static> (Transcript.tsx) and the composer follows the
  // live content inline. Only the in-progress stream needs bounding so a
  // very long mid-stream message doesn't outgrow the screen before it
  // commits — show its trailing rows here (the full text lands in
  // scrollback on stream.end). Trailing blank rows from a buffer ending
  // in "\n" are trimmed so we don't float a lone cursor.
  const streamRows: string[] = (() => {
    if (state.streamId === null || !state.streaming) return [];
    const r = state.streaming.split("\n");
    let end = r.length;
    while (end > 0 && r[end - 1] === "") end--;
    return r.slice(0, end).slice(-Math.max(3, rows - 8));
  })();

  return (
    <Box flexDirection="column" paddingX={1}>
      <Transcript
        banner={state.banner}
        lines={state.lines}
        termCols={cols}
        termRows={rows}
      />
      {streamRows.length > 0 && (
        <Box flexDirection="column">
          {streamRows.map((row, i) => (
            <Text key={`s${i}`} color="white">
              {i === 0 ? "" : "   "}{row}
            </Text>
          ))}
        </Box>
      )}
      {state.streamId !== null && (
        <PulsingCursor lastDeltaAtMs={lastDeltaAt.current} color="white" />
      )}
      <Composer
        banner={state.banner}
        status={state.status}
        toolLane={state.toolLane}
        flash={state.flash}
        confirmReq={state.confirmReq}
        inputText={editor.text}
        cursorPos={editor.cursor}
        tpsHistory={tokenRate.history}
        tpsCurrent={tokenRate.current}
        state={state}
        slashSelectedIdx={slashSelectedIdx}
        termCols={cols}
        atMatches={atMatches}
        atSelectedIdx={atSelectedIdx}
        reverseSearch={reverseSearch}
        askFocusedIdx={askFocusedIdx}
        askSelections={askSelections}
      />
    </Box>
  );
}

function turnSeparator(): string {
  const now = new Date();
  const hh = String(now.getHours()).padStart(2, "0");
  const mm = String(now.getMinutes()).padStart(2, "0");
  const ss = String(now.getSeconds()).padStart(2, "0");
  return `── ${hh}:${mm}:${ss} ──`;
}

render(<App />);
