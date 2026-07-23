/* Suma PWA — vanilla JS, no build step.
   Talks to the FastAPI backend at the same origin (/api/...).
   Dev note: the API key here is the local dev key; real auth is a Phase 2 task. */

const API_KEY = "change-me-local-dev-key";
const HEADERS = { "X-API-Key": API_KEY, "Content-Type": "application/json" };

let locale = localStorage.getItem("suma_locale") || "es";
let strings = {};
let categories = [];
let txnKind = "money_out";
let reviewingId = null;      // receipt being confirmed in the sheet, if any
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
      const btn = document.createElement("button");
      btn.className = "txn-void";
      btn.textContent = strings.void;
      btn.onclick = async () => {
        await api(`/api/transactions/${t.id}/void`, { method: "POST" });
        await Promise.all([refreshDashboard(), refreshTxns()]);
      };
      li.appendChild(btn);
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
      </div>
      <div class="review-actions">
        <button class="btn btn-ghost review-discard"></button>
        <button class="btn btn-gold review-open"></button>
      </div>`;
    const readable = r.draft.amount > 0 || r.draft.merchant;
    li.querySelector(".review-who").textContent = readable
      ? `${r.draft.merchant || "?"} · ${r.draft.amount > 0 ? fmt(r.draft.amount) : "?"}`
      : strings.review_unreadable;
    li.querySelector(".review-note").textContent = r.draft.note || "";
    const open = li.querySelector(".review-open");
    open.textContent = strings.review_open;
    open.onclick = () => openReviewSheet(r);
    const discard = li.querySelector(".review-discard");
    discard.textContent = strings.review_discard;
    discard.onclick = async () => {
      if (!confirm(strings.review_discard_confirm)) return;
      try {
        await api(`/api/review/${r.receipt_id}/reject`, { method: "POST" });
        await refreshReview();
      } catch {
        alert(strings.error);
      }
    };
    if (r.has_image) loadReviewThumb(r.receipt_id, li.querySelector(".review-thumb"));
    list.appendChild(li);
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
  reviewingId = r.receipt_id;             // after openSheet, which clears it
  $("#sheetTitle").textContent = strings.review_title;
  const f = $("#txnForm");
  if (r.draft.amount > 0) f.amount.value = r.draft.amount;
  if (r.draft.merchant) f.counterparty.value = r.draft.merchant;
  if (r.draft.date) f.txn_date.value = r.draft.date;
  f.is_business.checked = !!r.draft.is_business;
  const match = categories.find((c) => c.code === r.draft.category_code);
  if (match) f.category_account_id.value = match.id;
}

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
  reviewingId = null;  // manual entry unless openReviewSheet says otherwise
  $("#sheetTitle").textContent =
    kind === "money_in" ? strings.add_money_in : strings.add_money_out;
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
  try {
    if (reviewingId != null) {
      // Confirming a captured receipt: post it and clear it from the queue.
      await api(`/api/review/${reviewingId}/confirm`, {
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
    reviewingId = null;
    await Promise.all([refreshDashboard(), refreshTxns(), refreshReview()]);
  } catch {
    alert(strings.error);
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
