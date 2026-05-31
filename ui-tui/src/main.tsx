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

import { Box, render, useApp, useInput } from "ink";
import React, { useCallback, useEffect, useReducer, useRef, useState } from "react";

import { Composer } from "./components/Composer.js";
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
import { useMouseWheel } from "./hooks/useMouseWheel.js";
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

  // Track latest scroll position via ref (read inside event handlers
  // without forcing useEffect re-subscription on every state change).
  const scrollOffsetRef = useRef(state.scrollOffset);
  useEffect(() => {
    scrollOffsetRef.current = state.scrollOffset;
  }, [state.scrollOffset]);

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

  // ----- mouse wheel scrolling ----------------------------------------
  // Off on Windows (ConPTY sends phantom mouse events). On elsewhere.
  const mouseEnabled = process.platform !== "win32";
  const handleWheel = useCallback((delta: number) => {
    dispatch({ type: "SET_SCROLL", offset: state.scrollOffset + delta });
  }, [state.scrollOffset]);
  useMouseWheel(handleWheel, mouseEnabled);

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

    // Scrollback — multiple keybindings for terminal compatibility.
    // PageUp/PageDown work on Linux/macOS but Windows Terminal
    // often intercepts them for its own scrollback. Ctrl+U/D are
    // the reliable fallback (vim-style half-page scroll) — BUT
    // only when the input buffer is empty. With text in the buffer,
    // Ctrl+U falls through to the readline-style kill-to-start
    // binding below (matches bash/zsh convention; without this
    // guard the kill-to-start binding was unreachable dead code).
    if (key.pageUp || (key.ctrl && typedChar === "u" && editor.text === "")) {
      const vb = computeVisibleBudget();
      dispatch({ type: "SET_SCROLL", offset: state.scrollOffset + vb });
      return;
    }
    // Ctrl+D-empty-buffer is bound to exit below (POSIX-shell
    // convention). PageDown covers the scroll case directly so we
    // don't need the Ctrl+D fallback that previously lived here.
    if (key.pageDown) {
      const vb = computeVisibleBudget();
      dispatch({ type: "SET_SCROLL", offset: state.scrollOffset - vb });
      return;
    }
    if (key.shift && key.upArrow) {
      dispatch({ type: "SET_SCROLL", offset: state.scrollOffset + 1 });
      return;
    }
    if (key.shift && key.downArrow) {
      dispatch({ type: "SET_SCROLL", offset: state.scrollOffset - 1 });
      return;
    }

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
      if (scrollOffsetRef.current > 0) {
        dispatch({ type: "SET_SCROLL", offset: 0 });
        return;
      }
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

  function computeVisibleBudget(): number {
    // Reserved rows the transcript can't use (in order, top → bottom):
    //   nameplate                       1
    //   transcript spacer / margin      1
    //   tool lane (when present)        N + 1  (rows + bottom margin)
    //   composer border top             1   ← bordered card around prompt
    //   composer prompt line            1
    //   composer border bottom          1
    //   status bar                      1
    //   outer paddingX (vertical = 0)   0
    //   safety slack                    1
    // ─────────────────────────────────
    //                                 = 7 + N (base) when no tool lane
    //
    // The +2 above the original baseline accounts for the bordered
    // composer card added in the same iteration that fixed the
    // composer to look like a proper input field. Without bumping
    // this, the transcript renders 2 extra lines that get pushed
    // above the visible viewport, making mid-stream agent output
    // invisible until the user scrolls back.
    //
    // When a confirm overlay is active, the composer is taller:
    // bordered box with 2 content lines (prompt + hint) = 4 rows
    // vs. normal bordered input = 3 rows. Add 1 extra reserved.
    const COMPOSER_BORDER = 2;
    // Confirm overlay is taller when it carries a rich preview
    // (tool_name header + preview body + 1-row margin). Cap the
    // preview row count to MATCH the renderer's MAX (15) plus 2
    // for tool header + margin.
    let CONFIRM_EXTRA = 0;
    if (state.confirmReq) {
      CONFIRM_EXTRA = 1;
      if (state.confirmReq.tool_name) CONFIRM_EXTRA += 1;
      if (state.confirmReq.preview) {
        const previewLines = state.confirmReq.preview.split("\n").length;
        CONFIRM_EXTRA += Math.min(previewLines, 15) + 2;  // body + margin
      }
    }
    // Plan-mode banner row above the composer (1 row), only when
    // not in a confirm flow (the confirm box hides the composer).
    const PLAN_MODE_BANNER = (!state.confirmReq && state.status?.plan_mode)
      ? 1 : 0;
    // Multi-line input: every \n in the buffer adds another visible
    // row to the composer. Without compensating here, those extra
    // rows push transcript content off the top of the viewport.
    const EDITOR_LINES = state.confirmReq
      ? 0  // composer hidden behind the confirm box; doesn't grow
      : Math.max(0, editor.text.split("\n").length - 1);
    // Slash popup adds rows when open with matches.
    const SLASH_POPUP_LINES = (!state.confirmReq && editor.text.startsWith("/"))
      ? Math.min(7, matchSlashCommands(editor.text).length)
      : 0;
    // @-mention popup adds rows similarly.
    const AT_POPUP_LINES = (!state.confirmReq && atOpen)
      ? Math.min(8, atMatches.length)
      : 0;
    const base = 5 + COMPOSER_BORDER + CONFIRM_EXTRA
      + EDITOR_LINES + SLASH_POPUP_LINES + AT_POPUP_LINES
      + PLAN_MODE_BANNER;
    const reserved =
      base + (state.toolLane.length > 0 ? state.toolLane.length + 1 : 0);
    return Math.max(4, rows - reserved - 1);
  }
  const visibleBudget = computeVisibleBudget();

  return (
    <Box flexDirection="column" height={rows} paddingX={1}>
      <Transcript
        banner={state.banner}
        lines={state.lines}
        streaming={state.streaming}
        streamId={state.streamId}
        scrollOffset={state.scrollOffset}
        visibleBudget={visibleBudget}
        termCols={cols}
        termRows={rows}
        lastDeltaAtMs={lastDeltaAt.current}
      />
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
