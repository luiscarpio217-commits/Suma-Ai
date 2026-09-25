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
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function refreshDashboard() {
  const d = await api("/api/dashboard");
  $("#numIn").textContent = fmt(d.money_in);
  $("#numOut").textContent = fmt(d.money_out);
  const left = $("#numLeft");
  left.textContent = fmt(d.net);
  left.classList.toggle("negative", d.net < 0);
  $("#numTaxes").textContent = fmt(d.tax_set_aside);
}

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
      edit.className = "txn-edit";
      edit.textContent = strings.edit;
      edit.onclick = () => openEditSheet(t);
      const undo = document.createElement("button");
      undo.className = "txn-void";
      undo.textContent = strings.void;
      undo.onclick = async () => {
        undo.disabled = edit.disabled = true;  // a double tap must not undo twice
        try {
          await api(`/api/transactions/${t.id}/void`, { method: "POST" });
          await Promise.all([refreshDashboard(), refreshTxns()]);
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
        <button class="btn btn-ghost review-discard"></button>
        <button class="btn btn-gold review-open"></button>
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
    await Promise.all([refreshDashboard(), refreshTxns(), refreshReview()]);
  } catch {
    alert(strings.error);
  } finally {
    save.disabled = false;
  }
});

/* ---------- quick text capture ---------- */
$("#quickForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("#quickText");
  const status = $("#quickStatus");
  if (!input.value.trim()) return;
  status.textContent = "…";
  try {
    const r = await api("/api/capture/text", {
      method: "POST",
      body: JSON.stringify({ text: input.value, locale }),
    });
    if (r.auto_posted) {
      status.textContent = `✓ ${strings.captured_auto} — ${r.note || ""}`;
      input.value = "";
      await Promise.all([refreshDashboard(), refreshTxns()]);
    } else {
      // Low confidence (or no API key): open the sheet pre-filled for review.
      status.textContent = strings.captured_review;
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
    status.textContent = strings.error;
  }
});

/* ---------- language toggle ---------- */
$("#langToggle").onclick = async () => {
  locale = locale === "es" ? "en" : "es";
  localStorage.setItem("suma_locale", locale);
  await loadLocale();
  await Promise.all([refreshTxns(), refreshReview()]);
};

/* ---------- boot ---------- */
(async function init() {
  await loadLocale();
  try {
    await loadCategories();
    await Promise.all([refreshDashboard(), refreshTxns(), refreshReview()]);
  } catch (err) {
    console.error("API unreachable — is the backend running?", err);
  }
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }
})();
