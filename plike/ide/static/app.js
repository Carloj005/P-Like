/* P-Like Studio Frontend Logic (Zero external deps) */

(() => {
  const $ = (id) => document.getElementById(id);

  const editor = $("codeEditor");
  const highlightPre = $("codeHighlight");
  const highlightInner = $("codeHighlightInner");
  const lineGutter = $("lineGutter");
  const cursorPos = $("cursorPos");
  const filenameInput = $("filenameInput");
  const dirtyDot = $("dirtyDot");
  const stdinInput = $("stdinInput");

  const napoliModeSelect = $("napoliModeSelect");
  const noLuckCheck = $("noLuckCheck");
  const seedInput = $("seedInput");
  const napoliScoreboard = $("napoliScoreboard");
  const napoliMeta = $("napoliMeta");
  const napoliOutcomeBadge = $("napoliOutcomeBadge");
  const moodPill = $("moodPill");
  const moodTrack = $("moodTrack");

  const verdictCard = $("verdictCard");
  const verdictStatus = $("verdictStatus");
  const gradeStamp = $("gradeStamp");
  const verdictQuote = $("verdictQuote");
  const verdictStats = $("verdictStats");

  const consoleOutput = $("consoleOutput");
  const execMeta = $("execMeta");
  const diagList = $("diagList");
  const diagCountBadge = $("diagCountBadge");
  const bytecodeOutput = $("bytecodeOutput");
  const c99Output = $("c99Output");
  const pythonOutput = $("pythonOutput");
  const astOutput = $("astOutput");
  const statusMessage = $("statusMessage");
  const examplesList = $("examplesList");

  let examples = [];
  let canSaveDisk = false;
  let lastCompiled = { bytecode_json: "", c_code: "", py_code: "", ast_json: "" };
  let lineDiagMap = new Map(); // line -> 'err' | 'warn' | 'forgiven'

  // ------------------------------------------------------------------
  // HTML escaping & Syntax Highlighting (P-Like, C99, Python)
  // ------------------------------------------------------------------

  function escapeHtml(s) {
    return s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  const PLIKE_KW = new Set([
    "begin", "end", "var", "type", "record", "endrecord", "array", "of",
    "procedure", "endprocedure", "function", "endfunction", "return",
    "if", "then", "else", "elseif", "endif", "for", "to", "downto", "step",
    "do", "endfor", "while", "endwhile", "repeat", "until", "read", "print",
    "write", "allocate", "alloca", "deallocate", "dealloca", "free",
    "in", "out", "in/out", "input", "output", "inout", "and", "or", "not", "mod", "div"
  ]);

  const PLIKE_TYPES = new Set([
    "integer", "real", "character", "char", "string", "logical", "boolean",
    "list_pointer", "stack_pointer", "queue_pointer", "comb_pointer"
  ]);

  const PLIKE_CONSTS = new Set(["true", "false", "null", "nil"]);

  function highlightPLike(src) {
    const tokenRe = /(\(\*[\s\S]*?\*\)|\/\*[\s\S]*?\*\/|\/\/[^\n]*|'(?:''|[^'\n])*'|"(?:\\.|[^"\n])*"|\.(?:TRUE|FALSE|AND|OR|NOT)\.|\bin\/out\b|\b\d+\.(?!\.)\d*(?:[eE][+-]?\d+)?|\b\d+\b|:=|!=|<>|<=|>=|\*\*|[+\-*/=<>^!]|\b[A-Za-z_][A-Za-z0-9_]*\b)/gi;
    let out = "";
    let last = 0;
    let m;
    while ((m = tokenRe.exec(src)) !== null) {
      if (m.index > last) out += escapeHtml(src.slice(last, m.index));
      const tok = m[0];
      const low = tok.toLowerCase();
      let cls = "";
      if (tok.startsWith("(*") || tok.startsWith("/*") || tok.startsWith("//")) {
        cls = "tok-cmt";
      } else if (tok.startsWith("'") || tok.startsWith('"')) {
        cls = "tok-str";
      } else if (low === ".true." || low === ".false." || PLIKE_CONSTS.has(low)) {
        cls = "tok-const";
      } else if (low === ".and." || low === ".or." || low === ".not.") {
        cls = "tok-op";
      } else if (/^\d/.test(tok)) {
        cls = "tok-num";
      } else if (PLIKE_TYPES.has(low)) {
        cls = "tok-type";
      } else if (PLIKE_KW.has(low)) {
        cls = "tok-kw";
      } else if (/^(:=|!=|<>|<=|>=|\*\*|[+\-*/=<>^!])$/.test(tok)) {
        cls = "tok-op";
      }
      out += cls ? `<span class="${cls}">${escapeHtml(tok)}</span>` : escapeHtml(tok);
      last = tokenRe.lastIndex;
    }
    if (last < src.length) out += escapeHtml(src.slice(last));
    // Trailing newline keeps pre height synced with textarea
    return out + "\n";
  }

  function highlightGenericCode(src, lang) {
    const kwSet = lang === "c"
      ? new Set(["#include", "typedef", "struct", "static", "void", "int", "double", "char", "bool", "if", "else", "for", "while", "do", "return", "true", "false", "NULL", "sizeof"])
      : new Set(["import", "class", "def", "return", "if", "elif", "else", "while", "for", "in", "break", "pass", "not", "and", "or", "True", "False", "None", "raise", "try", "except", "lambda"]);
    const re = lang === "c"
      ? /(\/\*[\s\S]*?\*\/|\/\/[^\n]*|"(?:\\.|[^"\n])*"|\b\d+(?:\.\d+)?\b|#[a-z]+|\b[A-Za-z_][A-Za-z0-9_]*\b)/g
      : /(#[^\n]*|"""[\s\S]*?"""|'(?:\\.|[^'\n])*'|"(?:\\.|[^"\n])*"|\b\d+(?:\.\d+)?\b|\b[A-Za-z_][A-Za-z0-9_]*\b)/g;

    let out = "";
    let last = 0;
    let m;
    while ((m = re.exec(src)) !== null) {
      if (m.index > last) out += escapeHtml(src.slice(last, m.index));
      const tok = m[0];
      let cls = "";
      if (tok.startsWith("/*") || tok.startsWith("//") || (lang === "py" && tok.startsWith("#"))) cls = "tok-cmt";
      else if (tok.startsWith('"') || tok.startsWith("'")) cls = "tok-str";
      else if (/^\d/.test(tok)) cls = "tok-num";
      else if (kwSet.has(tok)) cls = "tok-kw";
      out += cls ? `<span class="${cls}">${escapeHtml(tok)}</span>` : escapeHtml(tok);
      last = re.lastIndex;
    }
    if (last < src.length) out += escapeHtml(src.slice(last));
    return out;
  }

  // ------------------------------------------------------------------
  // Editor rendering, gutter, cursor & scroll sync
  // ------------------------------------------------------------------

  function updateEditorVisuals() {
    const code = editor.value;
    highlightInner.innerHTML = highlightPLike(code);
    renderGutter(code);
    updateCursorPosition();
  }

  function renderGutter(code) {
    const count = code.split("\n").length;
    let html = "";
    for (let i = 1; i <= count; i++) {
      const marker = lineDiagMap.get(i);
      const dot = marker ? `<span class="gutter-dot ${marker}"></span>` : "";
      html += `<div class="gutter-line">${dot}<span>${i}</span></div>`;
    }
    lineGutter.innerHTML = html;
  }

  function syncScroll() {
    highlightPre.scrollTop = editor.scrollTop;
    highlightPre.scrollLeft = editor.scrollLeft;
    lineGutter.scrollTop = editor.scrollTop;
  }

  function updateCursorPosition() {
    const pos = editor.selectionStart || 0;
    const before = editor.value.slice(0, pos);
    const lines = before.split("\n");
    cursorPos.textContent = `Ln ${lines.length}, Col ${lines[lines.length - 1].length + 1}`;
  }

  function jumpToLineCol(line, col) {
    const lines = editor.value.split("\n");
    const targetLine = Math.max(1, Math.min(line, lines.length));
    let offset = 0;
    for (let i = 0; i < targetLine - 1; i++) {
      offset += lines[i].length + 1;
    }
    offset += Math.max(0, Math.min((col || 1) - 1, lines[targetLine - 1].length));
    editor.focus();
    editor.setSelectionRange(offset, offset);
    // Scroll approximate line into view
    const lineHeight = 20.925;
    editor.scrollTop = Math.max(0, (targetLine - 5) * lineHeight);
    syncScroll();
    updateCursorPosition();
  }

  function markDirty(isDirty) {
    dirtyDot.classList.toggle("dirty", isDirty);
  }

  // ------------------------------------------------------------------
  // Napoli Widget
  // ------------------------------------------------------------------

  function renderNapoliMatch(match) {
    if (!match) return;
    const mood = match.mood;
    const outcome = match.outcome;

    document.body.classList.remove("mood-win", "mood-draw", "mood-loss", "mood-standard");
    napoliOutcomeBadge.className = "napoli-badge";

    let level = 3;
    let segClass = "active-draw";

    if (mood === "ESTASI_AZZURRA") {
      document.body.classList.add("mood-win");
      napoliOutcomeBadge.classList.add("win");
      napoliOutcomeBadge.textContent = "VITTORIA TOP";
      level = 5; segClass = "active-win";
    } else if (mood === "OTTIMO_UMORE") {
      document.body.classList.add("mood-win");
      napoliOutcomeBadge.classList.add("win");
      napoliOutcomeBadge.textContent = "VITTORIA";
      level = 4; segClass = "active-win";
    } else if (mood === "NEUTRO") {
      document.body.classList.add("mood-draw");
      napoliOutcomeBadge.classList.add("draw");
      napoliOutcomeBadge.textContent = "PAREGGIO";
      level = 3; segClass = "active-draw";
    } else if (mood === "NERVOSO") {
      document.body.classList.add("mood-loss");
      napoliOutcomeBadge.classList.add("loss");
      napoliOutcomeBadge.textContent = "SCONFITTA";
      level = 2; segClass = "active-loss";
    } else if (mood === "FURIA_POST_PARTITA") {
      document.body.classList.add("mood-loss");
      napoliOutcomeBadge.classList.add("loss");
      napoliOutcomeBadge.textContent = "DISASTRO";
      level = 1; segClass = "active-loss";
    } else {
      document.body.classList.add("mood-standard");
      napoliOutcomeBadge.textContent = "STANDARD";
      level = 3; segClass = "active-draw";
    }

    if (outcome === "DISABLED") {
      napoliScoreboard.textContent = "Variabile Napoli disattivata";
      napoliMeta.textContent = "Compilatore P-Like deterministico standard";
    } else {
      napoliScoreboard.textContent = match.scoreboard;
      napoliMeta.textContent = `${match.competition} · ${match.date} [${match.source}]`;
    }

    moodPill.textContent = mood.replace(/_/g, " ");
    const segs = moodTrack.querySelectorAll(".mood-seg");
    segs.forEach((seg, idx) => {
      seg.className = "mood-seg";
      if (idx < level) seg.classList.add(segClass);
    });
  }

  async function fetchNapoliStatus(refresh = false) {
    const mode = napoliModeSelect.value;
    statusMessage.textContent = "Aggiornamento risultato SSC Napoli...";
    try {
      const resp = await fetch(`/api/napoli?mode=${encodeURIComponent(mode)}&refresh=${refresh ? "1" : "0"}`);
      const data = await resp.json();
      if (data.match) {
        renderNapoliMatch(data.match);
        statusMessage.textContent = `SSC Napoli aggiornato: ${data.match.scoreboard}`;
      }
    } catch (err) {
      statusMessage.textContent = `Errore rete Napoli: ${err}`;
    }
  }

  // ------------------------------------------------------------------
  // Run & Check Compiler API
  // ------------------------------------------------------------------

  async function runOrCheck(execute) {
    const btnRun = $("btnRun");
    const btnCheck = $("btnCheck");
    btnRun.disabled = true;
    btnCheck.disabled = true;
    statusMessage.textContent = execute ? "Compilazione ed esecuzione in corso..." : "Verifica compilatore in corso...";

    const payload = {
      code: editor.value,
      filename: filenameInput.value || "programma.plike",
      stdin: stdinInput.value,
      napoli_mode: napoliModeSelect.value,
      allow_luck: !noLuckCheck.checked,
      seed: seedInput.value.trim() === "" ? null : Number(seedInput.value),
    };

    try {
      const resp = await fetch(execute ? "/api/run" : "/api/check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      if (!resp.ok) {
        statusMessage.textContent = data.error || "Errore dal server";
        return;
      }
      renderResult(data, execute);
    } catch (err) {
      statusMessage.textContent = `Errore di connessione al backend: ${err}`;
    } finally {
      btnRun.disabled = false;
      btnCheck.disabled = false;
    }
  }

  function renderResult(data, executed) {
    const v = data.verdict;
    renderNapoliMatch(v.match);

    // Verdict card
    verdictCard.className = "verdict-card " + (data.success ? "passed" : "failed");
    verdictStatus.textContent = data.success
      ? (executed ? "COMPILAZIONE ED ESECUZIONE RIUSCITE" : "COMPILAZIONE RIUSCITA")
      : "COMPILAZIONE FALLITA";
    gradeStamp.textContent = v.grade_label;
    verdictQuote.textContent = v.prof_comment;

    let chips = `<span class="stat-chip">${data.elapsed_ms} ms</span>`;
    if (executed && data.success) {
      chips += `<span class="stat-chip">${data.steps.toLocaleString()} passi VM</span>`;
    }
    if (v.forgiven_count > 0) {
      chips += `<span class="stat-chip forgiven">${v.forgiven_count} sviste perdonate (Napoli)</span>`;
    }
    if (v.promoted_count > 0) {
      chips += `<span class="stat-chip promoted">${v.promoted_count} pignolerie promosse a errore</span>`;
    }
    if (v.bad_luck_rejection) {
      chips += `<span class="stat-chip promoted">Malumore post-sconfitta!</span>`;
    }
    verdictStats.innerHTML = chips;

    // Diagnostics & gutter dots
    const diags = data.diagnostics || [];
    lineDiagMap = new Map();
    let errCount = 0;
    let warnCount = 0;

    for (const d of diags) {
      let kind = "warn";
      if (d.forgiven_by_napoli) {
        kind = "forgiven";
      } else if (d.promoted_by_napoli || d.severity === "FATAL" || d.severity === "ERROR" || (d.severity === "RECOVERABLE" && !data.success)) {
        kind = "err";
        errCount++;
      } else {
        warnCount++;
      }
      const prev = lineDiagMap.get(d.line);
      if (!prev || kind === "err") lineDiagMap.set(d.line, kind);
    }
    renderGutter(editor.value);

    diagCountBadge.textContent = String(diags.length);
    diagCountBadge.className = "tab-count" + (errCount > 0 ? " has-err" : warnCount > 0 ? " has-warn" : "");

    if (diags.length === 0) {
      diagList.innerHTML = '<div class="empty-state">Zero errori e zero pignolerie: P-Like canonico da 30 e Lode!</div>';
    } else {
      diagList.innerHTML = "";
      for (const d of diags) {
        let cls = "sev-warn";
        let tagCls = "warn";
        let tagText = `${d.severity} ${d.code}`;
        if (d.forgiven_by_napoli) {
          cls = "sev-forgiven"; tagCls = "forgiven"; tagText = `PERDONATO (NAPOLI) ${d.code}`;
        } else if (d.promoted_by_napoli) {
          cls = "sev-err"; tagCls = "err"; tagText = `ERRORE (SCONFITTA NAPOLI) ${d.code}`;
        } else if (d.severity === "FATAL" || d.severity === "ERROR") {
          cls = "sev-err"; tagCls = "err";
        } else if (d.severity === "RECOVERABLE") {
          cls = data.success ? "sev-forgiven" : "sev-err";
          tagCls = data.success ? "forgiven" : "err";
          tagText = `RECUPERABILE ${d.code}`;
        }

        const card = document.createElement("div");
        card.className = `diag-card ${cls}`;
        card.innerHTML = `
          <div class="diag-head">
            <span class="diag-tag ${tagCls}">${escapeHtml(tagText)}</span>
            <span class="diag-loc">Riga ${d.line}, Col ${d.col}</span>
          </div>
          <div class="diag-msg">${escapeHtml(d.message)}</div>
          ${d.hint ? `<div class="diag-hint">&#128161; ${escapeHtml(d.hint)}</div>` : ""}
        `;
        card.addEventListener("click", () => jumpToLineCol(d.line, d.col));
        diagList.appendChild(card);
      }
    }

    // Console Output
    if (!data.success) {
      execMeta.textContent = `Compilazione fallita (${diags.length} segnalazioni)`;
      consoleOutput.innerHTML = `<span class="runtime-err">Compilazione bloccata (${escapeHtml(v.grade_label)}).\nControlla la scheda Diagnostiche per i dettagli!</span>`;
      if (diags.length > 0) switchTab("diagnostics");
    } else if (!executed) {
      execMeta.textContent = `Verifica completata in ${data.elapsed_ms} ms`;
      consoleOutput.textContent = "Verifica completata con successo! Premi 'Esegui' per avviare sulla Virtual Machine P-Like.";
    } else {
      execMeta.textContent = `Completato in ${data.elapsed_ms} ms · ${data.steps.toLocaleString()} passi VM`;
      let outHtml = escapeHtml(data.stdout || "(Nessun output stampato su console)");
      if (data.runtime_error) {
        outHtml += `<span class="runtime-err">${escapeHtml(data.runtime_error)}</span>`;
      }
      consoleOutput.innerHTML = outHtml;
      switchTab("console");
    }

    // Transpiler & Bytecode tabs
    lastCompiled = {
      bytecode_json: data.bytecode_json || "",
      c_code: data.c_code || "",
      py_code: data.py_code || "",
      ast_json: data.ast_json || "",
    };
    bytecodeOutput.textContent = data.disasm || "// Nessun bytecode generato (compilazione fallita)";
    c99Output.innerHTML = data.c_code ? highlightGenericCode(data.c_code, "c") : "/* Compilazione fallita */";
    pythonOutput.innerHTML = data.py_code ? highlightGenericCode(data.py_code, "py") : "# Compilazione fallita";
    astOutput.textContent = data.ast_json || "{}";

    statusMessage.textContent = data.success
      ? `Successo (${v.grade_label}) — ${v.match.scoreboard}`
      : `Compilazione fallita (${v.grade_label}) — ${v.match.scoreboard}`;
  }

  // ------------------------------------------------------------------
  // Tabs, Examples, File Open/Save/Download, Splitters
  // ------------------------------------------------------------------

  function switchTab(name) {
    document.querySelectorAll(".tab-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.tab === name);
    });
    document.querySelectorAll(".tab-panel").forEach((p) => {
      p.classList.toggle("active", p.id === `panel-${name}`);
    });
  }

  function loadCodeIntoEditor(name, code, defaultStdin = "", allowDiskSave = false) {
    filenameInput.value = name;
    editor.value = code;
    stdinInput.value = defaultStdin;
    canSaveDisk = allowDiskSave;
    lineDiagMap = new Map();
    markDirty(false);
    updateEditorVisuals();
    editor.scrollTop = 0;
    syncScroll();
  }

  function renderExamplesSidebar(activeFile) {
    examplesList.innerHTML = "";
    const grouped = new Map();
    for (const ex of examples) {
      if (!grouped.has(ex.category)) grouped.set(ex.category, []);
      grouped.get(ex.category).push(ex);
    }
    for (const [cat, list] of grouped.entries()) {
      const hdr = document.createElement("div");
      hdr.className = "example-cat";
      hdr.textContent = cat;
      examplesList.appendChild(hdr);

      for (const ex of list) {
        const btn = document.createElement("button");
        btn.className = "example-item" + (ex.filename === activeFile ? " active" : "");
        btn.innerHTML = `<span class="ex-title">${escapeHtml(ex.title)}</span><span class="ex-file">${escapeHtml(ex.filename)}</span>`;
        btn.addEventListener("click", () => {
          loadCodeIntoEditor(ex.filename, ex.code, ex.default_stdin || "", false);
          renderExamplesSidebar(ex.filename);
          statusMessage.textContent = `Caricato esempio: ${ex.filename}`;
        });
        examplesList.appendChild(btn);
      }
    }
  }

  function triggerDownload(filename, content) {
    const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  async function saveCurrentFile() {
    if (canSaveDisk) {
      const resp = await fetch("/api/save-local", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: editor.value }),
      });
      const data = await resp.json();
      if (data.saved) {
        markDirty(false);
        statusMessage.textContent = `Salvato su disco: ${data.path}`;
        return;
      }
    }
    let name = filenameInput.value.trim() || "programma.plike";
    if (!name.endsWith(".plike")) name += ".plike";
    triggerDownload(name, editor.value);
    markDirty(false);
    statusMessage.textContent = `Scaricato file: ${name}`;
  }

  function setupSplitters() {
    function bindDrag(splitterEl, onMove) {
      let dragging = false;
      splitterEl.addEventListener("mousedown", (e) => {
        dragging = true;
        splitterEl.classList.add("dragging");
        e.preventDefault();
      });
      window.addEventListener("mousemove", (e) => {
        if (!dragging) return;
        onMove(e.clientX);
      });
      window.addEventListener("mouseup", () => {
        if (!dragging) return;
        dragging = false;
        splitterEl.classList.remove("dragging");
      });
    }

    const sidebar = $("sidebar");
    const inspector = $("inspectorPane");
    bindDrag($("splitSidebar"), (x) => {
      const w = Math.max(170, Math.min(380, x));
      sidebar.style.width = `${w}px`;
    });
    bindDrag($("splitInspector"), (x) => {
      const rightW = Math.max(290, Math.min(window.innerWidth - 360, window.innerWidth - x));
      inspector.style.flex = "none";
      inspector.style.width = `${rightW}px`;
    });
  }

  // ------------------------------------------------------------------
  // Event bindings
  // ------------------------------------------------------------------

  editor.addEventListener("input", () => {
    markDirty(true);
    updateEditorVisuals();
  });
  editor.addEventListener("scroll", syncScroll);
  editor.addEventListener("click", updateCursorPosition);
  editor.addEventListener("keyup", updateCursorPosition);

  editor.addEventListener("keydown", (e) => {
    // Tab -> inserisce 4 spazi
    if (e.key === "Tab") {
      e.preventDefault();
      const s = editor.selectionStart;
      const end = editor.selectionEnd;
      if (e.shiftKey) {
        const lineStart = editor.value.lastIndexOf("\n", s - 1) + 1;
        if (editor.value.slice(lineStart, lineStart + 4) === "    ") {
          editor.value = editor.value.slice(0, lineStart) + editor.value.slice(lineStart + 4);
          editor.selectionStart = Math.max(lineStart, s - 4);
          editor.selectionEnd = Math.max(lineStart, end - 4);
        }
      } else {
        editor.value = editor.value.slice(0, s) + "    " + editor.value.slice(end);
        editor.selectionStart = editor.selectionEnd = s + 4;
      }
      markDirty(true);
      updateEditorVisuals();
    }
  });

  window.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      runOrCheck(true);
    } else if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === "b") {
      e.preventDefault();
      runOrCheck(false);
    } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
      e.preventDefault();
      saveCurrentFile();
    } else if (e.key === "Escape") {
      $("cheatsheetModal").classList.add("hidden");
    }
  });

  $("btnRun").addEventListener("click", () => runOrCheck(true));
  $("btnCheck").addEventListener("click", () => runOrCheck(false));
  $("btnRefreshNapoli").addEventListener("click", () => fetchNapoliStatus(true));
  napoliModeSelect.addEventListener("change", () => fetchNapoliStatus(false));

  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });

  $("btnNewFile").addEventListener("click", () => {
    loadCodeIntoEditor(
      "nuovo_algoritmo.plike",
      "(* Nuovo algoritmo P-Like *)\nbegin mio_programma\n    var: x: integer\n    x := 42\n    print 'Valore:', x\nend mio_programma\n",
      "",
      false
    );
    renderExamplesSidebar("");
    statusMessage.textContent = "Creato nuovo file P-Like";
  });

  $("btnOpenFile").addEventListener("click", () => $("hiddenFileInput").click());
  $("hiddenFileInput").addEventListener("change", async (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    const text = await file.text();
    loadCodeIntoEditor(file.name, text, "", false);
    renderExamplesSidebar("");
    statusMessage.textContent = `Aperto file locale: ${file.name}`;
    e.target.value = "";
  });

  $("btnSaveFile").addEventListener("click", saveCurrentFile);

  $("btnCopyConsole").addEventListener("click", () => {
    navigator.clipboard.writeText(consoleOutput.textContent || "");
    statusMessage.textContent = "Output console copiato negli appunti";
  });

  document.querySelectorAll("[data-copy]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = $(btn.dataset.copy);
      navigator.clipboard.writeText(target.textContent || "");
      statusMessage.textContent = "Codice copiato negli appunti";
    });
  });

  function baseStem() {
    return (filenameInput.value.trim() || "programma").replace(/\.plike$/i, "");
  }
  $("btnDownloadBc").addEventListener("click", () => {
    if (lastCompiled.bytecode_json) triggerDownload(baseStem() + ".plbc", lastCompiled.bytecode_json);
  });
  $("btnDownloadC").addEventListener("click", () => {
    if (lastCompiled.c_code) triggerDownload(baseStem() + ".c", lastCompiled.c_code);
  });
  $("btnDownloadPy").addEventListener("click", () => {
    if (lastCompiled.py_code) triggerDownload(baseStem() + ".py", lastCompiled.py_code);
  });

  $("btnCheatsheet").addEventListener("click", () => $("cheatsheetModal").classList.remove("hidden"));
  $("btnCloseModal").addEventListener("click", () => $("cheatsheetModal").classList.add("hidden"));
  $("cheatsheetModal").addEventListener("click", (e) => {
    if (e.target === $("cheatsheetModal")) $("cheatsheetModal").classList.add("hidden");
  });

  // ------------------------------------------------------------------
  // Bootstrap iniziale
  // ------------------------------------------------------------------

  async function init() {
    setupSplitters();
    try {
      const [infoRes, exRes] = await Promise.all([
        fetch("/api/info").then((r) => r.json()),
        fetch("/api/examples").then((r) => r.json()),
      ]);

      examples = exRes.examples || [];
      if (infoRes.default_napoli) {
        napoliModeSelect.value = infoRes.default_napoli;
      }

      if (infoRes.initial_file) {
        loadCodeIntoEditor(
          infoRes.initial_file.filename,
          infoRes.initial_file.code,
          "",
          Boolean(infoRes.initial_file.can_save_disk)
        );
        renderExamplesSidebar("");
      } else if (examples.length > 0) {
        const first = examples[0];
        loadCodeIntoEditor(first.filename, first.code, first.default_stdin || "", false);
        renderExamplesSidebar(first.filename);
      } else {
        updateEditorVisuals();
      }
    } catch (err) {
      statusMessage.textContent = `Errore avvio IDE: ${err}`;
    }

    await fetchNapoliStatus(false);
  }

  init();
})();
