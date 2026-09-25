/* Suma PWA — vanilla JS, no build step.
   Talks to the FastAPI backend at the same origin (/api/...).
   Dev note: the API key here is the local dev key; real auth is a Phase 2 task. */

const API_KEY = "change-me-local-dev-key";
const HEADERS = { "X-API-Key": API_KEY, "Content-Type": "application/json" };

let locale = localStorage.getItem("suma_locale") || "es";
let strings = {};
let categories = [];
let txnKind = "money_out";
let sheetTarget = null;      // null: new entry · {review: receiptId} · {edit: txnId}
let reviewImageUrls = [];    // object URLs to revoke on re-render

const $ = (sel) => document.querySelector(sel);
const fmt = (n) =>
  new Intl.NumberFormat(locale === "es" ? "es-US" : "en-US",
    { style: "currency", currency: "USD" }).format(n);

/* ---------- i18n ---------- */
async function loadLocale() {
  strings = await (await fetch(`locales/${locale}.json`)).json();
  document.documentElement.lang = locale;
  document.querySelectorAll("[data-i18n]").forEach(el => {
    el.textContent = strings[el.dataset.i18n] ?? el.dataset.i18n;
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach(el => {
    el.placeholder = strings[el.dataset.i18nPlaceholder] ?? "";
  });
  $("#langToggle").textContent = locale === "es" ? "EN" : "ES";
  const now = new Date();
  $("#monthLabel").textContent =
    `${strings.this_month} — ` +
    now.toLocaleDateString(locale === "es" ? "es-US" : "en-US",
      { month: "long", year: "numeric" });
}

/* ---------- data ---------- */
async function api(path, opts = {}) {
  const res = await fetch(path, { headers: HEADERS, ...opts });
  if (!res.ok) {
    const err = new Error(await res.text());
    err.status = res.status;
    throw err;
  }
  return res.json();
}

async function refreshDashboard() {
  const d = await api("/api/dashboard");
  $("#numIn").textContent = fmt(d.money_in);
  $("#numIn").classList.toggle("positive", d.money_in > 0);
  $("#numOut").textContent = fmt(d.money_out);
  const left = $("#numLeft");
  left.textContent = fmt(d.net);
  left.classList.toggle("positive", d.net > 0);
  left.classList.toggle("negative", d.net < 0);
  $("#numTaxes").textContent = fmt(d.tax_set_aside);
  fitTileNumbers();
}

/* On a narrow phone an amount like $2,350.00 is wider than its tile. Keep the
   board's big size when it fits; otherwise shrink that one number just enough. */
function fitTileNumbers() {
  for (const el of document.querySelectorAll(".tile-num")) {
    el.style.fontSize = "";
    let size = parseFloat(getComputedStyle(el).fontSize);
    while (el.scrollWidth > el.clientWidth && size > 14) {
      el.style.fontSize = `${--size}px`;
    }
  }
}
window.addEventListener("resize", fitTileNumbers);
document.fonts?.ready.then(fitTileNumbers);  // the web font can arrive after the numbers

async function refreshTxns() {
  const txns = await api("/api/transactions?limit=25");
  const list = $("#txnList");
  list.innerHTML = "";
  $("#emptyState").hidden = txns.length > 0;
  for (const t of txns) {
    const cat = categories.find(c => c.id === t.category_account_id);
    const li = document.createElement("li");
    li.className = "txn" + (t.status === "voided" ? " voided" : "");
    li.innerHTML = `
      <div class="txn-main">
        <div class="txn-who"></div>
        <div class="txn-meta"></div>
      </div>
      <span class="txn-amt ${t.kind === "money_in" ? "in" : ""}">
        ${t.kind === "money_in" ? "+" : "−"}${fmt(t.amount)}
      </span>`;
    li.querySelector(".txn-who").textContent =
      t.counterparty || (cat ? catName(cat) : "");
    li.querySelector(".txn-meta").textContent =
      `${t.txn_date} · ${cat ? catName(cat) : ""}` +
      (t.is_business ? ` · ${strings.business}` : "");
    if (t.status === "posted") {
      const actions = document.createElement("div");
      actions.className = "txn-actions";
      const edit = document.createElement("button");
      edit.className = "btn btn-secondary txn-edit";
      edit.textContent = strings.edit;
      edit.onclick = () => openEditSheet(t);
      const undo = document.createElement("button");
      undo.className = "btn btn-secondary txn-void";
      undo.textContent = strings.void;
      undo.onclick = async () => {
        undo.disabled = edit.disabled = true;  // a double tap must not undo twice
        try {
          await api(`/api/transactions/${t.id}/void`, { method: "POST" }).catch((err) => {
            if (err.status !== 409) throw err;  // 409: already undone elsewhere — the goal
          });
          await refreshAll();
        } catch {
          undo.disabled = edit.disabled = false;
          alert(strings.error);
        }
      };
      actions.append(edit, undo);
      li.appendChild(actions);
    }
    list.appendChild(li);
  }
}

const catName = (c) => (locale === "es" ? c.name_es : c.name_en);

const refreshAll = () => Promise.all(
  [refreshDashboard(), refreshTxns(), refreshReview(), refreshHistory(), refreshTaxCard()]);

/* ---------- next tax payment ---------- */
// Not new Date("2027-01-15"): that's UTC midnight, still Jan 14 in US time zones.
const localDate = (iso) => {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
};

async function refreshTaxCard() {
  const t = await api("/api/tax-card");
  const intl = locale === "es" ? "es-US" : "en-US";
  const monthName = (iso) => localDate(iso).toLocaleDateString(intl, { month: "long" });
  $("#taxCardDate").textContent = localDate(t.due_date)
    .toLocaleDateString(intl, { day: "numeric", month: "long", year: "numeric" });
  $("#taxCardMonths").textContent = fillIn(strings.tax_card_months, {
    from: monthName(t.period_start), to: monthName(t.period_end),
    year: localDate(t.period_end).getFullYear(),
  });
  $("#taxCardAmount").textContent = fmt(t.set_aside);
  $("#taxCard").hidden = false;
}

/* ---------- earlier months ---------- */
async function refreshHistory() {
  const months = await api("/api/history");
  const list = $("#historyList");
  list.innerHTML = "";
  $("#historySection").hidden = months.length === 0;
  for (const m of months) {
    const li = document.createElement("li");
    li.className = "history-month";
    li.innerHTML = `<h3></h3><dl class="history-grid"></dl>`;
    li.querySelector("h3").textContent = new Date(m.year, m.month - 1, 1)
      .toLocaleDateString(locale === "es" ? "es-US" : "en-US", { month: "long", year: "numeric" });
    // Same four numbers, same labels, same order as the board.
    for (const [key, value] of [["in", m.money_in], ["out", m.money_out],
                                ["left", m.net], ["set_aside", m.tax_set_aside]]) {
      const cell = document.createElement("div");
      cell.className = `history-${key}`;
      cell.innerHTML = "<dt></dt><dd></dd>";
      cell.querySelector("dt").textContent = strings[key];
      const dd = cell.querySelector("dd");
      dd.textContent = fmt(value);
      dd.classList.toggle("positive", (key === "in" || key === "left") && value > 0);
      dd.classList.toggle("negative", key === "left" && value < 0);
      li.querySelector("dl").appendChild(cell);
    }
    list.appendChild(li);
  }
}

/* ---------- needs-review queue ---------- */
async function refreshReview() {
  const items = await api("/api/review");
  const list = $("#reviewList");
  reviewImageUrls.forEach((u) => URL.revokeObjectURL(u));
  reviewImageUrls = [];
  list.innerHTML = "";
  $("#reviewSection").hidden = items.length === 0;
  $("#reviewCount").textContent = items.length;
  for (const r of items) {
    const li = document.createElement("li");
    li.className = "review-item";
    li.innerHTML = `
      <div class="review-item-top">
        <img class="review-thumb" alt="" hidden />
        <div class="review-main">
          <div class="review-who"></div>
          <div class="review-note"></div>
        </div>
        <span class="review-amt"></span>
      </div>
      <div class="review-actions">
        <button class="btn btn-secondary review-discard"></button>
        <button class="btn btn-main review-open"></button>
      </div>`;
    const cat = categories.find((c) => c.code === r.draft.category_code);
    const readable = r.draft.amount > 0 || r.draft.merchant;
    li.querySelector(".review-who").textContent = readable
      ? r.draft.merchant || (cat ? catName(cat) : "")
      : strings.review_unreadable;
    li.querySelector(".review-amt").textContent =
      r.draft.amount > 0 ? `−${fmt(r.draft.amount)}` : "";
    li.querySelector(".review-note").textContent = r.draft.note || "";
    const open = li.querySelector(".review-open");
    open.textContent = strings.review_open;
    open.onclick = () => openReviewSheet(r);
    const discard = li.querySelector(".review-discard");
    discard.textContent = strings.review_discard;
    discard.onclick = () => discardReceipt(r.receipt_id);
    if (r.has_image) loadReviewThumb(r.receipt_id, li.querySelector(".review-thumb"));
    list.appendChild(li);
  }
}

async function discardReceipt(id) {
  if (!confirm(strings.review_discard_confirm)) return false;
  try {
    await api(`/api/review/${id}/reject`, { method: "POST" });
    await refreshReview();
    return true;
  } catch {
    alert(strings.error);
    return false;
  }
}

async function loadReviewThumb(id, img) {
  // <img src> can't send the API key header, so fetch the photo ourselves.
  try {
    const res = await fetch(`/api/review/${id}/image`, { headers: { "X-API-Key": API_KEY } });
    if (!res.ok) return;
    const url = URL.createObjectURL(await res.blob());
    reviewImageUrls.push(url);
    img.src = url;
    img.hidden = false;
  } catch { /* no thumbnail, the text still works */ }
}

function openReviewSheet(r) {
  openSheet("money_out");                 // resets the form, expense categories
  sheetTarget = { review: r.receipt_id }; // after openSheet, which clears it
  showMoneyOutNote("review_out_hint", true);
  const f = $("#txnForm");
  if (r.draft.amount > 0) f.amount.value = r.draft.amount;
  if (r.draft.merchant) f.counterparty.value = r.draft.merchant;
  if (r.draft.date) f.txn_date.value = r.draft.date;
  f.is_business.checked = !!r.draft.is_business;
  const match = categories.find((c) => c.code === r.draft.category_code);
  if (match) f.category_account_id.value = match.id;
}

/* Fixing a saved entry: the sheet opens with its values. The direction
   (money in / out) stays as it was; saving sends the fix, and the
   original stays visible in the list, crossed out. */
function openEditSheet(t) {
  openSheet(t.kind);
  sheetTarget = { edit: t.id };
  $("#sheetTitle").textContent = fillIn(strings.edit_title,
    { kind: t.kind === "money_in" ? strings.add_money_in : strings.add_money_out });
  showSheetNote(strings.edit_lead, strings.edit_hint, false);
  $("#btnSave").textContent = strings.edit_save;
  const f = $("#txnForm");
  f.amount.value = t.amount;
  f.counterparty.value = t.counterparty;
  f.txn_date.value = t.txn_date;
  f.category_account_id.value = t.category_account_id;
  f.is_business.checked = t.is_business;
}

function showSheetNote(lead, text, canDiscard) {
  $("#sheetNoteLead").textContent = lead;
  $("#sheetNoteText").textContent = text;
  $("#btnSheetDiscard").hidden = !canDiscard;
  $("#sheetNote").hidden = false;
}

/* Confirming an AI draft can only record money going out, so say so in
   the sheet itself — a photographed check must not slip in as spending. */
function showMoneyOutNote(hintKey, canDiscard) {
  showSheetNote(strings.review_out_lead,
    fillIn(strings[hintKey], { money_in: strings.add_money_in, cancel: strings.cancel }),
    canDiscard);
  $("#btnSave").textContent = strings.review_confirm_out;
}

const fillIn = (s, vars) => s.replace(/\{(\w+)\}/g, (m, k) => vars[k] ?? m);

$("#btnSheetDiscard").onclick = async () => {
  if (sheetTarget?.review != null && await discardReceipt(sheetTarget.review)) {
    $("#txnSheet").close();
    sheetTarget = null;
  }
};

async function loadCategories() {
  categories = await api("/api/categories");
}

function fillCategorySelect(kind) {
  const sel = $("#categorySelect");
  sel.innerHTML = "";
  sel.setCustomValidity("");
  if (kind === "money_out") {
    // No default here: a hurried save would be filed under whatever came
    // first, and that lands in the tax export. The select is required, so
    // this empty choice blocks saving until a real one is picked.
    const prompt = new Option(strings.category_pick, "", true, true);
    prompt.disabled = true;
    sel.appendChild(prompt);
  }
  const want = kind === "money_in" ? "income" : "expense";
  for (const c of categories.filter(c => c.type === want)) {
    const opt = document.createElement("option");
    opt.value = c.id;
    opt.textContent = catName(c);
    sel.appendChild(opt);
  }
}

/* ---------- add-transaction sheet ---------- */
function openSheet(kind) {
  txnKind = kind;
  sheetTarget = null;  // a new entry unless the caller says otherwise
  $("#sheetTitle").textContent =
    kind === "money_in" ? strings.add_money_in : strings.add_money_out;
  $("#sheetNote").hidden = true;
  $("#btnSheetDiscard").hidden = true;
  $("#btnSave").textContent = strings.save;
  fillCategorySelect(kind);
  const f = $("#txnForm");
  f.reset();
  f.txn_date.value = new Date().toISOString().slice(0, 10);
  $("#txnSheet").showModal();
}

// The browser's own "select an item" bubble would be in the phone's language,
// not the app's; say it with our words instead.
$("#categorySelect").addEventListener("invalid", (e) =>
  e.target.setCustomValidity(strings.category_required));
$("#categorySelect").addEventListener("change", (e) => e.target.setCustomValidity(""));

$("#btnIn").onclick = () => openSheet("money_in");
$("#btnOut").onclick = () => openSheet("money_out");
$("#btnCancel").onclick = () => $("#txnSheet").close();

$("#txnForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const values = {
    txn_date: f.txn_date.value,
    amount: f.amount.value,
    category_account_id: Number(f.category_account_id.value),
    counterparty: f.counterparty.value,
    is_business: f.is_business.checked,
  };
  const save = $("#btnSave");
  save.disabled = true;  // a double tap must not save twice
  try {
    if (sheetTarget?.review != null) {
      // Confirming a captured receipt: post it and clear it from the queue.
      await api(`/api/review/${sheetTarget.review}/confirm`, {
        method: "POST",
        body: JSON.stringify(values),
      });
    } else if (sheetTarget?.edit != null) {
      await api(`/api/transactions/${sheetTarget.edit}/correct`, {
        method: "POST",
        body: JSON.stringify(values),
      });
    } else {
      await api("/api/transactions", {
        method: "POST",
        body: JSON.stringify({ kind: txnKind, ...values }),
      });
    }
    $("#txnSheet").close();
    sheetTarget = null;
    await refreshAll();
  } catch (err) {
    alert(strings.error);
    if (err.status === 409) {  // handled elsewhere meanwhile; retrying can't work
      $("#txnSheet").close();
      sheetTarget = null;
      await refreshAll().catch(() => {});
    }
  } finally {
    save.disabled = false;
  }
});

/* ---------- quick text capture ---------- */
// The line under the capture buttons; red only for an error (bad news only).
function setStatus(text, isError = false) {
  $("#quickStatus").textContent = text;
  $("#quickStatus").classList.toggle("is-error", isError);
}

$("#quickForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("#quickText");
  if (!input.value.trim()) return;
  setStatus("…");
  try {
    const r = await api("/api/capture/text", {
      method: "POST",
      body: JSON.stringify({ text: input.value, locale }),
    });
    if (r.auto_posted) {
      setStatus(`✓ ${strings.captured_auto} — ${r.note || ""}`);
      input.value = "";
      await refreshAll();
    } else {
      // Low confidence (or no API key): open the sheet pre-filled for review.
      setStatus(strings.captured_review);
      openSheet("money_out");
      showMoneyOutNote("quick_out_hint", false);
      const f = $("#txnForm");
      if (r.amount > 0) f.amount.value = r.amount;
      if (r.merchant) f.counterparty.value = r.merchant;
      f.is_business.checked = r.is_business;
      const match = categories.find(c => c.code === r.category_code);
      if (match) f.category_account_id.value = match.id;
    }
  } catch {
    setStatus(strings.error, true);
  }
});

/* ---------- receipt photo ---------- */
const PHOTO_MAX_EDGE = 1600;  // plenty to read a receipt

/* Phone photos run 3–12 MB. Re-encoding at a readable size uploads fast on a
   phone connection, stays under the reader's size limit, turns formats the
   server doesn't take (iPhone HEIC, WebP) into JPEG, and drops hidden photo
   data such as location. */
async function shrinkPhoto(file) {
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    const scale = Math.min(1, PHOTO_MAX_EDGE / Math.max(img.naturalWidth, img.naturalHeight));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(img.naturalWidth * scale);
    canvas.height = Math.round(img.naturalHeight * scale);
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#fff";  // JPEG has no transparency; see-through turns white, not black
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    return await new Promise((done) => canvas.toBlob((b) => done(b || file), "image/jpeg", 0.85));
  } catch {
    return file;  // this browser can't open it; the server says whether it can
  } finally {
    URL.revokeObjectURL(url);
  }
}

$("#btnPhoto").onclick = () => $("#photoInput").click();

$("#photoInput").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  e.target.value = "";  // so the same photo can be chosen again
  if (!file) return;
  const btn = $("#btnPhoto");
  btn.disabled = true;
  $("#btnPhotoLabel").textContent = strings.photo_reading;
  setStatus("");
  try {
    const photo = await shrinkPhoto(file);
    const form = new FormData();
    form.append("file", photo, photo === file ? file.name : "receipt.jpg");
    const r = await api("/api/capture/photo", {
      method: "POST", body: form, headers: { "X-API-Key": API_KEY },
    });
    if (r.auto_posted) {
      setStatus(`✓ ${strings.captured_auto} — ${r.note || ""}`);
      await refreshAll();
    } else {
      // Unsure (or no AI key): straight to the confirm sheet. It also waits
      // in the review list if the user closes the sheet.
      setStatus(strings.captured_review);
      await refreshReview();
      openReviewSheet({ receipt_id: r.receipt_id, draft: r });
    }
  } catch (err) {
    alert(err.status === 413 || err.status === 415 ? strings.photo_unusable : strings.error);
  } finally {
    btn.disabled = false;
    $("#btnPhotoLabel").textContent = strings.photo;
  }
});

/* ---------- language toggle ---------- */
$("#langToggle").onclick = async () => {
  locale = locale === "es" ? "en" : "es";
  localStorage.setItem("suma_locale", locale);
  await loadLocale();
  await refreshAll();  // lists hold translated labels and month names
};

/* ---------- boot ---------- */
(async function init() {
  await loadLocale();
  try {
    await loadCategories();
    await refreshAll();
  } catch (err) {
    console.error("API unreachable — is the backend running?", err);
  }
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }
})();
