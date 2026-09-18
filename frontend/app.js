(() => {
  const $ = (id) => document.getElementById(id);

  const els = {
    status: $("status"),
    dropzone: $("dropzone"),
    dropzoneInner: $("dropzoneInner"),
    fileInput: $("fileInput"),
    thumb: $("thumb"),
    srcLang: $("srcLang"),
    tgtLang: $("tgtLang"),
    outline: $("outline"),
    btnRun: $("btnRun"),
    btnOcr: $("btnOcr"),
    btnDownload: $("btnDownload"),
    btnReset: $("btnReset"),
    hint: $("hint"),
    actions: $("actions"),
    placeholder: $("placeholder"),
    compare: $("compare"),
    imgBefore: $("imgBefore"),
    imgAfter: $("imgAfter"),
    handle: $("handle"),
    alert: $("alert"),
    lines: $("lines"),
    lineList: $("lineList"),
    lineCount: $("lineCount"),
    toast: $("toast"),
    ocrPanel: $("ocrPanel"),
    ocrList: $("ocrList"),
    ocrSummary: $("ocrSummary"),
    btnToggleAll: $("btnToggleAll"),
    termsList: $("termsList"),
  };

  let file = null;
  let originalUrl = null;
  let busy = false;
  let ocrId = null;
  let ocrLines = [];
  let terms = [];

  const REQUEST_TIMEOUT = 120000;

  async function postForm(url, fd) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), REQUEST_TIMEOUT);
    try {
      return await fetch(url, { method: "POST", body: fd, signal: ctrl.signal });
    } catch (e) {
      if (e.name === "AbortError") throw new Error("请求超时：服务响应过慢，可在 .env 里换 TRANSLATOR");
      throw e;
    } finally {
      clearTimeout(timer);
    }
  }

  async function getJson(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`${url} 返回 ${res.status}`);
    return res.json();
  }

  // ---------------- 通用 ----------------
  let toastTimer;
  function toast(msg, isError = false) {
    els.toast.textContent = msg;
    els.toast.classList.toggle("is-error", isError);
    els.toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (els.toast.hidden = true), 3200);
  }

  function setBusy(state, text) {
    busy = state;
    els.btnRun.disabled = state || !file;
    els.btnOcr.disabled = state || !file;
    els.hint.textContent = text || "";
  }

  function fillSelect(select, list, selected) {
    select.innerHTML = list
      .map((i) => `<option value="${i.code}"${i.code === selected ? " selected" : ""}>${i.name}</option>`)
      .join("");
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  async function loadLanguages() {
    try {
      const data = await getJson("/api/languages");
      const langs = data.languages || [];
      fillSelect(els.srcLang, [{ code: "auto", name: "自动检测" }, ...langs], "auto");
      fillSelect(els.tgtLang, langs, "zh");
    } catch (e) {
      els.status.textContent = "语言列表加载失败";
    }
    try {
      const s = await getJson("/api/status");
      els.status.textContent = `OCR: ${s.ocr} · 翻译: ${s.translator}`;
    } catch (e) {
      els.status.textContent = "服务未连接";
    }
  }

  // ---------------- 保护词 ----------------
  function matchTerm(text) {
    const low = (text || "").toLowerCase();
    return terms.find((t) => t.toLowerCase() && low.includes(t.toLowerCase())) || null;
  }

  function renderTerms() {
    els.termsList.innerHTML = "";
    if (!terms.length) {
      const empty = document.createElement("span");
      empty.className = "chip__empty";
      empty.textContent = "暂无，可在下方识别结果里点「保护」添加";
      els.termsList.appendChild(empty);
      return;
    }
    terms.forEach((t) => {
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.appendChild(document.createTextNode(t));
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = "×";
      btn.title = "移除";
      btn.addEventListener("click", () => removeTerm(t));
      chip.appendChild(btn);
      els.termsList.appendChild(chip);
    });
  }

  async function addTerm(text) {
    const fd = new FormData();
    fd.append("term", text);
    try {
      const res = await postForm("/api/terms/add", fd);
      terms = (await res.json()).terms || [];
      renderTerms();
      renderOcrList();
      toast(`已加入保护词：${text}`);
    } catch (e) {
      toast("添加保护词失败", true);
    }
  }

  async function removeTerm(t) {
    const fd = new FormData();
    fd.append("term", t);
    try {
      const res = await postForm("/api/terms/remove", fd);
      terms = (await res.json()).terms || [];
      renderTerms();
      renderOcrList();
    } catch (e) {
      toast("移除失败", true);
    }
  }

  async function loadTerms() {
    try {
      terms = (await getJson("/api/terms")).terms || [];
    } catch (e) {
      terms = [];
    }
    renderTerms();
  }

  // ---------------- 上传后自动识别 ----------------
  function updateSummary() {
    const cbs = checkboxes();
    const skipped = cbs.filter((c) => !c.checked).length;
    els.ocrSummary.textContent =
      `识别到 ${ocrLines.length} 行 · 已选 ${cbs.length - skipped} 行翻译` + (skipped ? `，${skipped} 行保留原文` : "");
    const allChecked = cbs.length > 0 && cbs.every((c) => c.checked);
    els.btnToggleAll.textContent = allChecked ? "全部不翻译" : "全部翻译";
  }

  function checkboxes() {
    return [...els.ocrList.querySelectorAll('input[type="checkbox"]')].filter((c) => !c.disabled);
  }

  function renderOcrList() {
    els.ocrList.innerHTML = "";
    ocrLines.forEach((l) => {
      const term = matchTerm(l.text);
      const li = document.createElement("li");
      li.className = "ocr__item" + (term ? " is-protected" : "");

      const label = document.createElement("label");
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.dataset.i = String(l.index);
      cb.checked = !term;
      cb.disabled = !!term;
      cb.addEventListener("change", updateSummary);
      const text = document.createElement("span");
      text.className = "ocr__text";
      text.textContent = l.text;
      const score = document.createElement("span");
      score.className = "ocr__score";
      score.textContent = `${(l.score * 100).toFixed(0)}%`;
      label.appendChild(cb);
      label.appendChild(text);
      label.appendChild(score);
      li.appendChild(label);

      if (term) {
        const badge = document.createElement("span");
        badge.className = "lock";
        badge.textContent = `保护词：${term}`;
        li.appendChild(badge);
      } else {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "linkbtn";
        btn.textContent = "保护";
        btn.title = "加入保护词，以后自动跳过翻译";
        btn.addEventListener("click", () => addTerm(l.text));
        li.appendChild(btn);
      }
      els.ocrList.appendChild(li);
    });
    updateSummary();
  }

  async function runOcr() {
    if (!file) return;
    els.ocrPanel.hidden = false;
    els.ocrSummary.textContent = "正在识别文字…";
    els.ocrList.innerHTML = "";
    setBusy(true, "正在识别可翻译的内容…");
    const fd = new FormData();
    fd.append("file", file);
    fd.append("src_lang", els.srcLang.value);
    try {
      const res = await postForm("/api/ocr", fd);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "识别失败");
      ocrId = data.ocr_id || null;
      ocrLines = data.lines || [];
      renderOcrList();
      setBusy(false, ocrLines.length ? "已识别，可取消勾选不翻译的内容" : "未识别到文字");
    } catch (e) {
      ocrLines = [];
      ocrId = null;
      els.ocrSummary.textContent = "识别失败，可直接点开始转换";
      setBusy(false, "");
      toast(e.message || "识别失败", true);
    }
  }

  els.btnToggleAll.addEventListener("click", () => {
    const cbs = checkboxes();
    if (!cbs.length) return;
    const allChecked = cbs.every((c) => c.checked);
    cbs.forEach((c) => (c.checked = !allChecked));
    updateSummary();
  });

  // ---------------- 上传 ----------------
  function resetOcrPanel() {
    ocrId = null;
    ocrLines = [];
    els.ocrList.innerHTML = "";
    els.ocrPanel.hidden = true;
  }

  function pickFile(f) {
    if (!f || !f.type.startsWith("image/")) {
      toast("请选择图片文件", true);
      return;
    }
    if (f.size > 20 * 1024 * 1024) {
      toast("图片不能超过 20MB", true);
      return;
    }
    file = f;
    if (originalUrl) URL.revokeObjectURL(originalUrl);
    originalUrl = URL.createObjectURL(f);
    els.thumb.src = originalUrl;
    els.thumb.hidden = false;
    els.dropzoneInner.hidden = true;
    els.btnRun.disabled = false;
    els.btnOcr.disabled = false;
    els.placeholder.hidden = true;
    els.compare.hidden = false;
    els.compare.classList.add("is-single");
    els.imgAfter.src = originalUrl;
    els.lines.hidden = true;
    els.actions.hidden = true;
    els.alert.hidden = true;
    resetOcrPanel();
    setBusy(false, `已选择：${f.name}`);
    runOcr();
  }

  els.dropzone.addEventListener("click", () => els.fileInput.click());
  els.fileInput.addEventListener("change", (e) => {
    if (e.target.files[0]) pickFile(e.target.files[0]);
  });
  ["dragenter", "dragover"].forEach((ev) =>
    els.dropzone.addEventListener(ev, (e) => {
      e.preventDefault();
      els.dropzone.classList.add("is-over");
    })
  );
  ["dragleave", "drop"].forEach((ev) =>
    els.dropzone.addEventListener(ev, (e) => {
      e.preventDefault();
      els.dropzone.classList.remove("is-over");
    })
  );
  els.dropzone.addEventListener("drop", (e) => {
    if (e.dataTransfer.files[0]) pickFile(e.dataTransfer.files[0]);
  });

  // ---------------- 对比滑块 ----------------
  function setPos(clientX) {
    const rect = els.compare.getBoundingClientRect();
    const pos = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    els.compare.style.setProperty("--pos", pos.toFixed(4));
  }
  let dragging = false;
  els.compare.addEventListener("pointerdown", (e) => {
    if (els.compare.classList.contains("is-single")) return;
    dragging = true;
    setPos(e.clientX);
    els.handle.setPointerCapture?.(e.pointerId);
  });
  els.compare.addEventListener("pointermove", (e) => dragging && setPos(e.clientX));
  els.compare.addEventListener("pointerup", () => (dragging = false));
  els.compare.addEventListener("pointercancel", () => (dragging = false));

  // ---------------- 主流程 ----------------
  function renderLines(lines) {
    els.lineCount.textContent = String(lines.length);
    els.lineList.innerHTML = lines
      .map((l) => {
        const tgt = l.skipped
          ? `<span class="src">${escapeHtml(l.tgt)}</span><span class="keep">已保留</span>`
          : `<span class="tgt">${escapeHtml(l.tgt)}</span>`;
        return `<li><span class="src">${escapeHtml(l.src)}</span><span class="arrow">→</span>${tgt}</li>`;
      })
      .join("");
    els.lines.hidden = lines.length === 0;
  }

  function showResult(url, isSingle = false) {
    els.imgBefore.src = originalUrl;
    els.imgAfter.src = url;
    els.compare.hidden = false;
    els.compare.classList.toggle("is-single", isSingle);
    els.compare.style.setProperty("--pos", "0.5");
    els.placeholder.hidden = true;
  }

  els.btnRun.addEventListener("click", async () => {
    if (!file || busy) return;
    const skip = [...els.ocrList.querySelectorAll('input[type="checkbox"]')]
      .filter((c) => !c.checked)
      .map((c) => Number(c.dataset.i));
    setBusy(true, "正在翻译并重绘，请稍候…");
    const fd = new FormData();
    fd.append("file", file);
    fd.append("src_lang", els.srcLang.value);
    fd.append("tgt_lang", els.tgtLang.value);
    fd.append("outline", els.outline.value);
    fd.append("skip", JSON.stringify(skip));
    if (ocrId) fd.append("ocr_id", ocrId);
    try {
      const res = await postForm("/api/translate", fd);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "转换失败");
      showResult(data.result_url);
      renderLines(data.lines || []);
      const meta = data.meta || {};
      if (meta.translation_failed > 0) {
        els.alert.innerHTML =
          `翻译接口不可用，<b>${meta.translation_failed}</b> 行保留了原文（图中文字仍是原语言）。<br>` +
          `在项目根目录的 <code>.env</code> 里检查 <code>TRANSLATOR</code> 配置后重启服务。`;
        els.alert.hidden = false;
      } else {
        els.alert.hidden = true;
      }
      els.btnDownload.href = data.result_url;
      els.btnDownload.download = `translated_${Date.now()}.png`;
      els.actions.hidden = false;
      const kept = (data.lines || []).filter((l) => l.skipped).length;
      setBusy(
        false,
        `完成，共 ${meta.total || 0} 行` +
          (kept ? `（${kept} 行按要求保留原文）` : "") +
          `，用时 ${data.elapsed_ms}ms`
      );
      if (!meta.total) toast("没有识别到文字，已返回原图");
    } catch (e) {
      setBusy(false, "");
      toast(e.message || "转换失败", true);
    }
  });

  els.btnOcr.addEventListener("click", () => {
    if (!file || busy) return;
    runOcr();
  });

  els.btnReset.addEventListener("click", () => {
    file = null;
    els.fileInput.value = "";
    els.thumb.hidden = true;
    els.dropzoneInner.hidden = false;
    els.actions.hidden = true;
    els.alert.hidden = true;
    els.lines.hidden = true;
    els.compare.hidden = true;
    els.placeholder.hidden = false;
    els.btnRun.disabled = true;
    els.btnOcr.disabled = true;
    els.hint.textContent = "";
    resetOcrPanel();
  });

  loadLanguages();
  loadTerms();
})();
