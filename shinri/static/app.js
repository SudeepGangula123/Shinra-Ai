(() => {
  const $ = (id) => document.getElementById(id);
  const LABELS = {
    supported: ["Supported", "ok", "The evidence we found supports this claim."],
    contradicted: ["Contradicted", "bad", "The evidence we found contradicts this claim."],
    old_or_out_of_context: ["Old or out of context", "warn", "This appeared earlier or is shown with misleading context."],
    signs_of_editing: ["Signs of editing", "warn", "Checks found signs of editing. This is not proof."],
    possible_ai_generated: ["Possibly AI-generated", "warn", "A detector suggests AI generation. Detectors are often wrong."],
    not_enough_evidence: ["Not enough evidence", "neutral", "We could not find enough reliable evidence either way."],
  };
  const STEPS = ["Received", "Reading your input", "Running checks", "Verdict"];
  let poll = null, current = null;

  // ---- theme: follows the system until the user picks one ------------
  const root = document.documentElement;
  const systemDark = () => window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches;
  $("theme").addEventListener("click", () => {
    const now = root.getAttribute("data-theme") || (systemDark() ? "dark" : "light");
    const next = now === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try { localStorage.setItem("shinri-theme", next); } catch { /* private mode: fine */ }
  });

  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === "class") el.className = v; else if (k === "text") el.textContent = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v); else el.setAttribute(k, v);
    }
    for (const kid of kids.flat()) if (kid != null) el.append(kid.nodeType ? kid : document.createTextNode(kid));
    return el;
  }
  const safeUrl = (u) => /^https?:\/\//i.test(u || "") ? u : null;
  const fmtTime = (iso) => iso ? new Date(iso).toLocaleString([], {dateStyle: "medium", timeStyle: "short"}) : "";

  function showError(msg) { const e = $("err"); e.textContent = msg || ""; e.hidden = !msg; }

  // ---- submit -------------------------------------------------------
  $("file").addEventListener("change", () => {
    const f = $("file").files[0];
    $("file-label").textContent = f ? `${f.name} (${(f.size / 1048576).toFixed(1)} MB)` : "＋ Add image, video or voice note";
  });
  const drop = $("drop");
  ["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("drag"); }));
  ["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("drag"); }));
  drop.addEventListener("drop", e => { if (e.dataTransfer.files.length) { $("file").files = e.dataTransfer.files; $("file").dispatchEvent(new Event("change")); } });

  $("form").addEventListener("submit", async (e) => {
    e.preventDefault(); showError("");
    const fd = new FormData();
    fd.append("text", $("text").value);
    const f = $("file").files[0]; if (f) fd.append("file", f);
    $("go").disabled = true;
    try {
      const r = await fetch("/checks", {method: "POST", body: fd});
      const j = await r.json().catch(() => ({}));
      if (!r.ok) { showError(j.error || j.detail || "Something went wrong. Please try again."); return; }
      track(j.checkId);
    } catch { showError("Could not reach the server. Check your connection and try again."); }
    finally { $("go").disabled = false; }
  });

  // ---- polling & rendering -----------------------------------------
  function track(id) {
    current = id; clearInterval(poll);
    $("result").hidden = false; $("out").replaceChildren(h("p", {class: "muted", text: "Starting…"}));
    $("result").scrollIntoView({behavior: "smooth", block: "start"});
    const tick = async () => {
      try {
        const r = await fetch(`/checks/${id}`); if (!r.ok) return;
        const rec = await r.json(); if (current !== id) return;
        render(rec);
        if (rec.status === "done" || rec.status === "failed") { clearInterval(poll); loadSide(); }
      } catch { /* keep polling */ }
    };
    tick(); poll = setInterval(tick, 1500);
  }

  function stepState(rec) {
    if (rec.status === "done") return 4;
    if (rec.status === "failed") return -1;
    const runs = rec.engineRuns.length;
    if (rec.status === "received") return 0;
    if (runs === 0) return 1;
    return 2;
  }

  function renderSteps(rec) {
    const s = stepState(rec);
    $("steps").replaceChildren(...STEPS.map((t, i) => h("span", {class: "step" + (s === 4 || i < s ? " done" : i === s ? " on" : ""), text: t})));
  }

  function signalRow(c) {
    const pct = Math.min(100, Math.abs(c.contribution) / 3 * 100) / 2;  // scale: ±3 fills half the bar
    return h("div", {class: "sig"},
      h("div", {}, h("div", {class: "t", text: c.summary || c.kind}),
        h("div", {class: "k", text: `${c.engine} · ${c.kind} · strength ${c.strength} × weight ${c.weight} = ${c.contribution > 0 ? "+" : ""}${c.contribution}`})),
      h("div", {}, h("div", {class: "bar2"}, h("i", {class: c.contribution < 0 ? "neg" : "pos", style: `width:${pct}%`})),
        h("div", {class: "legend"}, h("span", {text: "against"}), h("span", {text: "for"}))));
  }

  function render(rec) {
    renderSteps(rec);
    const out = [];
    if (rec.status === "failed") {
      out.push(h("p", {class: "error", text: rec.error || "This check could not be completed."}));
    } else if (!rec.verdict) {
      out.push(h("p", {class: "muted", text: "Checking claims, media and where this first appeared…"}));
    } else {
      const v = rec.verdict, [name, tone] = LABELS[v.label] || [v.label, "neutral"];
      out.push(h("div", {class: "verdict"},
        h("span", {class: `chip ${tone}`, text: name}),
        v.label === "not_enough_evidence" ? null :
          h("span", {class: "conf"}, `Confidence ${Math.round(v.confidence * 100)}%`, h("span", {class: "meter"}, h("i", {style: `width:${Math.round(v.confidence * 100)}%`})))));
      if (rec.explanation) out.push(h("p", {class: "expl", text: rec.explanation.text}));
      if (v.contributions.length) {
        out.push(h("h3", {text: "Why we reached this"}), ...v.contributions.map(signalRow));
      }
    }
    if (rec.input.type === "image" && rec.input.mediaRef) out.push(h("img", {class: "thumb", src: `/media/${rec.checkId}`, alt: "The image you sent"}));
    if (rec.claims.length) {
      out.push(h("h3", {text: "Claims we checked"}), ...rec.claims.map(c => h("div", {class: "claim", text: c.text})));
    }
    const cites = ((rec.explanation && rec.explanation.citations) || []).map(safeUrl).filter(Boolean);
    if (cites.length) {
      out.push(h("h3", {text: "Sources"}), h("ul", {class: "list src"}, ...cites.map(u => h("li", {}, h("a", {href: u, target: "_blank", rel: "noopener noreferrer", text: u})))));
    }
    const limits = rec.engineRuns.flatMap(r => r.notes || []);
    if (limits.length) out.push(h("h3", {text: "Limits"}), h("ul", {class: "list"}, ...limits.map(n => h("li", {text: n}))));
    if (rec.engineRuns.length) {
      out.push(h("h3", {text: "Checks that ran"}), h("div", {class: "runs"}, ...rec.engineRuns.map(r =>
        h("span", {class: "run " + (r.mock ? "mock" : r.status === "ok" ? "ok" : r.status === "failed" ? "failed" : ""),
                   title: r.error || "", text: `${r.engine}: ${r.mock ? "placeholder" : r.status}`}))));
    }
    if (rec.status === "done") out.push(h("p", {class: "muted small", text: `Checked ${fmtTime(rec.completedAt)} · id ${rec.checkId}`}));
    $("out").replaceChildren(...out);
  }

  // ---- history & trending ------------------------------------------
  async function loadSide() {
    try {
      const hist = await (await fetch("/checks?limit=8")).json();
      if (hist.length) $("history").replaceChildren(...hist.map(c => h("li", {},
        h("button", {class: "link", onclick: () => track(c.checkId), text: c.preview || `(${c.type})`}),
        h("span", {class: "meta", text: `${c.label ? (LABELS[c.label] || [c.label])[0] : c.status} · ${c.type} · ${fmtTime(c.receivedAt)}`}))));
      const tr = await (await fetch("/trending")).json();
      if (tr.items.length) $("trending").replaceChildren(...tr.items.map(t => h("li", {},
        t.claim, h("span", {class: "meta", text: `${t.checks} checks · last ${fmtTime(t.lastSeen)}`}))));
    } catch { /* side panels are optional */ }
  }
  loadSide();
})();
