// The LLM space that lives inside a single task. Ask mode answers questions; Edit
// mode lets the model change the task's fields, add subtasks, and save progress notes.
// Threads persist per task in the Home Base side-car.

import * as data from "./data.js";
import { showError, toast } from "./ui.js";

const $ = (id) => document.getElementById(id);

const state = { id: null, mode: "ask", sending: false };

function bubble(role, text) {
  const el = document.createElement("div");
  el.className = `hb-msg ${role}`;
  el.textContent = text;
  return el;
}

function thinking() {
  const el = document.createElement("div");
  el.className = "hb-msg assistant";
  const dots = document.createElement("span");
  dots.className = "hb-dots";
  dots.innerHTML = "<span></span><span></span><span></span>";
  el.appendChild(dots);
  return el;
}

function scrollDown() {
  const box = $("hb-thread");
  box.scrollTop = box.scrollHeight;
}

function renderThread(app) {
  const box = $("hb-thread");
  box.textContent = "";
  const meta = data.metaOf(state.id);
  const messages = meta.chat || [];
  if (!messages.length) {
    const empty = document.createElement("div");
    empty.className = "hb-empty";
    empty.textContent = app.llmReady
      ? "Ask what's left, what's blocking it, or how to start. Switch to Edit and it can move the due date, change priority, tick it off, or add the steps it suggests."
      : "No model is reachable right now - turn off Offline mode in Daily Digest, or set an API key in .env.";
    box.appendChild(empty);
    return;
  }
  messages.forEach((m) => box.appendChild(bubble(m.role === "user" ? "user" : "assistant", m.text)));
  scrollDown();
}

export function openChat(app, id) {
  const node = id ? data.nodeById(id) : null;
  if (!node) return;
  state.id = id;
  $("hb-chat").hidden = false;
  $("hb-chat-title").textContent = node.text;
  showError($("hb-chat-err"), "");
  renderThread(app);
  $("hb-chat-input").focus();
}

export function refreshChat(app) {
  if ($("hb-chat").hidden || !state.id) return;
  if (!data.nodeById(state.id)) { $("hb-chat").hidden = true; return; }
  renderThread(app);
}

async function send(app) {
  if (state.sending || !state.id) return;
  const input = $("hb-chat-input");
  const text = input.value.trim();
  if (!text) return;
  const err = $("hb-chat-err");
  showError(err, "");

  state.sending = true;
  $("hb-chat-send").disabled = true;
  input.value = "";

  const box = $("hb-thread");
  if (box.querySelector(".hb-empty")) box.textContent = "";
  box.appendChild(bubble("user", text));
  const pending = thinking();
  box.appendChild(pending);
  scrollDown();

  try {
    const res = await data.req("/api/homebase/chat", { id: state.id, text, mode: state.mode });
    pending.remove();
    box.appendChild(bubble("assistant", res.reply));
    if (res.applied && res.applied.length) {
      const note = document.createElement("div");
      note.className = "hb-msg applied";
      note.textContent = "Applied: " + res.applied.join(", ");
      box.appendChild(note);
    }
    scrollDown();
    app.absorb(res, res.changed);
  } catch (e) {
    pending.remove();
    showError(err, e.message);
  } finally {
    state.sending = false;
    $("hb-chat-send").disabled = false;
  }
}

export function initChat(app) {
  $("hb-chat-close").addEventListener("click", () => { $("hb-chat").hidden = true; });
  $("hb-chat-send").addEventListener("click", () => send(app));

  $("hb-chat-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(app); }
  });

  $("hb-chat-modes").querySelectorAll(".hb-mini").forEach((b) => {
    b.addEventListener("click", () => {
      $("hb-chat-modes").querySelectorAll(".hb-mini").forEach((o) => o.classList.remove("active"));
      b.classList.add("active");
      state.mode = b.dataset.mode;
      toast(state.mode === "edit"
        ? "Edit mode: it can change this task"
        : "Ask mode: nothing will change");
    });
  });

  $("hb-chat-reset").addEventListener("click", async () => {
    if (!state.id) return;
    try {
      const res = await data.req("/api/homebase/chat/reset", { id: state.id });
      if (res.meta) data.store.meta = res.meta;
      renderThread(app);
    } catch (e) {
      showError($("hb-chat-err"), e.message);
    }
  });
}
