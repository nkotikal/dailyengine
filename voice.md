# Voice Mode — Design Notes (considered approaches)

> Status: **planning only, not built.** This captures the options we weighed for an
> optional voice mode so we can pick a direction later.

## Goal
Let a user record their **end-of-day summary** (and eventually other input) by
speaking instead of typing an email reply. Reflecting by voice should take ~20
seconds instead of composing a paragraph.

## Key insight — reuse the existing pipeline
The reflection pipeline already turns free-form text into structured updates:

```
free-form text  ->  inbox_commands.PARSE_SYSTEM (LLM)  ->  actions{}  ->  _apply()
```

`_apply()` already updates tasks, reminders, reflections (blockers/mood/progress),
weekly goals, tomorrow's schedule, and long-term memory. It is currently fed by
**email replies** (`process_replies`).

**Voice mode is just a second input source that produces the same text (a
transcript).** Everything downstream is reused. So the feature reduces to:

```
capture speech -> transcript -> existing reflection pipeline -> show what was applied
```

## UX sketch
1. A "Reflect" panel in the Digest tab: a mic button, a live transcript area, an
   editable text box, and an "Apply" button.
2. User speaks naturally (accomplishments, blockers, mood, tomorrow's plan,
   deadlines).
3. Transcript appears and is **editable** (fix any mis-hearing).
4. User confirms -> runs through the parser -> shows a summary of what was applied
   ("1 task completed, 1 blocker, 1 reminder due Fri, tomorrow's plan set…").
5. **Nothing is applied until confirmed** — voice is lossy, so never auto-commit.

## Transcription options

| Tier | Approach | Cost | Privacy | Offline | Accuracy | Effort |
|------|----------|------|---------|---------|----------|--------|
| **A** | Browser Web Speech API (live dictation) | Free | Audio goes to Google/Apple | No | Good for clear speech | Low (client-side JS, no deps) |
| **B** | OpenAI Whisper (reuse existing key) | ~$0.006/min (~$0.10/mo) | Audio -> OpenAI | No | Excellent (accents/noise/jargon) | Medium (record + relay endpoint) |
| **C** | Local Whisper (whisper.cpp / faster-whisper) | Free | Fully on-device | Yes | Excellent | High (native binary + large model; bloats exe) |

### Trade-off summary
- **Tier A** — fastest/cheapest and zero dependencies (fits the stdlib-only ethos),
  but audio leaves the machine to Google/Apple (contradicts the "nothing leaves your
  machine" promise unless disclosed), is browser-dependent (great in Chrome/Edge,
  weak in Firefox), and can't be tuned for technical vocabulary. Still needs
  internet, so it doesn't buy offline capability.
- **Tier B** — much better accuracy and consistent across browsers, which matters
  because this input **rewrites tasks/deadlines** (a dropped word = a dropped
  deadline). Reuses infrastructure already in place (OpenAI key, base URL, CA
  handling) and is a smaller marginal privacy step since the app already sends text
  to OpenAI. Costs a trivial amount and has a ~1–3s post-speech wait.
- **Tier C** — best alignment with local/private ethos, but ships a native binary +
  hundreds of MB of model, blowing up the currently-clean exe and installer. Over-
  engineered for a nightly 30-second convenience unless full offline privacy becomes
  a hard requirement.

### Leaning
Build the pipeline **transcription-agnostic**. Ship **Tier A as the no-key default**
and offer **Tier B as a toggle** when an OpenAI key is present. They share the same
transcript interface, so supporting both is only marginally more work than Tier B
alone, and it degrades gracefully: Whisper (if key) -> Web Speech (if supported) ->
typing (always).

## Architecture / data flow
```
[Browser mic]
   |- Tier A: Web Speech API   -> transcript (client-side)
   |- Tier B: MediaRecorder    -> audio blob -> POST /api/digest/transcribe
   |                                              -> relay to OpenAI Whisper -> transcript
   v
Editable transcript textarea
   |  (user confirms)
   v
POST /api/digest/reflect  { text }
   v
inbox_commands.apply_freeform_text(text)   <- NEW thin wrapper reusing PARSE_SYSTEM + _apply()
   v
returns the same "applied" summary the email path produces
```

## Concrete changes (when we build it)
- **Backend**
  - Refactor `inbox_commands.py`: extract the parse+apply logic (currently inline in
    `process_replies`) into `apply_freeform_text(text, model=...)`. Email and voice
    paths both call it. Low risk.
  - New endpoint `POST /api/digest/reflect` -> `{ text }` -> returns `applied` dict.
  - *(Tier B only)* `POST /api/digest/transcribe` -> accepts audio, relays to OpenAI
    `/v1/audio/transcriptions` via stdlib `http.client`, returns text.
- **Frontend**
  - A `VoiceReflect` panel: mic button, live transcript, editable box, Apply button,
    applied-summary readout (~150 lines vanilla JS, matching existing style).
  - Web Speech wiring with feature detection + typed fallback.
- **No new Python dependencies** for Tier A. Tier B uses stdlib `http.client`.

## Things to get right
- **Confirm before apply** — always show the transcript for editing; never auto-commit.
- **Localization** — honor `ui_lang`: Web Speech `lang` = `ko-KR` vs `en-US`; Whisper
  auto-detects.
- **Deadline safety** — the existing prompt already treats deadlines as critical and
  resolves relative dates; spoken "by next Friday" flows through unchanged.
- **Privacy disclosure** — one-line note that audio is sent to Google/OpenAI,
  consistent with how the LLM/email calls are disclosed.
- **Frozen-exe compatibility** — mic works over `http://127.0.0.1` (secure context),
  so no HTTPS needed.

## Suggested phasing
1. **Phase 1 (MVP):** extract `apply_freeform_text`, add `/api/digest/reflect`, build
   the voice panel with Web Speech + editable transcript + typed fallback. Delivers
   the whole feature for Chrome/Edge users, free.
2. **Phase 2 (optional):** add `/api/digest/transcribe` (Whisper) as a higher-accuracy
   toggle for users with an OpenAI key.
3. **Phase 3 (optional):** a "voice-first" quick flow — one tap, speak, auto-apply
   with an undo — once transcription is trusted in practice.

## Open decision
The main fork: optimize for **"free + instant + zero setup"** (lean Tier A) vs
**"accurate + reliable across browsers"** (lean Tier B). Everything else follows.
