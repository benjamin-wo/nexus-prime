const transactionLedgerState = {
  rows: [],
  direction: "all",
  category: "all",
  search: "",
  sort: "latest",
  page: 1,
  pageSize: 10,
  editing: null,
  initialized: false,
};

function transactionElement(id) {
  return document.getElementById(id);
}

function transactionHtml(value) {
  return escapeHtml(String(value ?? ""));
}

function transactionActionIcon(action) {
  const icons = {
    edit: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20h9"></path><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L8 18l-4 1 1-4Z"></path></svg>',
    split: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="6" cy="6" r="2.5"></circle><circle cx="18" cy="18" r="2.5"></circle><path d="M8.5 6h3a4 4 0 0 1 4 4v5.5"></path><path d="m13 13 2.5 2.5L18 13"></path></svg>',
    delete: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18"></path><path d="M8 6V4h8v2"></path><path d="M19 6l-1 14H6L5 6"></path><path d="M10 11v5M14 11v5"></path></svg>',
  };
  return icons[action] || "";
}

function transactionDateValue(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset());
  return date.toISOString().slice(0, 16);
}

function transactionDirectionLabel(direction) {
  return direction === "incoming" ? "Money in" : "Money out";
}

function transactionStatusLabel(status) {
  const labels = {
    completed: "Recorded",
    pending: "Pending",
    partially_paid: "Partially paid",
    paid: "Settled",
  };
  return labels[status] || "Recorded";
}

function transactionStatusClass(status) {
  if (status === "pending" || status === "partially_paid") return "pending";
  if (status === "paid" || status === "completed") return "completed";
  return "completed";
}

function transactionPendingParticipants(transaction) {
  const split = transaction.split_data || {};
  const shareAmounts = split.share_amounts || split.custom_amounts || {};
  const paidStatus = split.paid_status || {};
  const paidAmounts = split.paid_amounts || {};
  return (split.friends || [])
    .filter((friend) => friend !== "Me" && !paidStatus[friend])
    .map((friend) => ({
      name: friend,
      amount: Math.max(0, Number(shareAmounts[friend] || 0) - Number(paidAmounts[friend] || 0)),
    }))
    .filter((friend) => friend.amount > 0.01);
}

function transactionSettlementActions(transaction) {
  if (transaction.direction !== "outgoing") return "";
  const pending = transactionPendingParticipants(transaction);
  if (!pending.length) return "";
  return `<div class="transaction-settlement-actions" aria-label="Pending IOUs">${pending.slice(0, 3).map((friend) => `
    <button type="button" class="transaction-settle-btn" data-action="settle" data-key="${encodeURIComponent(transaction.id)}" data-participant="${encodeURIComponent(friend.name)}">
      Mark ${transactionHtml(friend.name)} paid
    </button>`).join("")}</div>`;
}

function renderUnifiedTransactions() {
  const body = transactionElement("expenses-table-body");
  const totalInfo = transactionElement("pagination-total-info");
  const navigation = transactionElement("pagination-nav-container");
  if (!body) return;

  let rows = [...transactionLedgerState.rows];
  if (transactionLedgerState.direction === "pending") {
    rows = rows.filter((row) => row.status === "pending" || row.status === "partially_paid");
  }
  if (transactionLedgerState.sort === "highest") {
    rows.sort((a, b) => Number(b.amount) - Number(a.amount));
  } else if (transactionLedgerState.sort === "oldest") {
    rows.sort((a, b) => new Date(a.date || 0) - new Date(b.date || 0));
  } else {
    rows.sort((a, b) => new Date(b.date || 0) - new Date(a.date || 0));
  }

  const totalPages = Math.max(1, Math.ceil(rows.length / transactionLedgerState.pageSize));
  transactionLedgerState.page = Math.min(Math.max(transactionLedgerState.page, 1), totalPages);
  const start = (transactionLedgerState.page - 1) * transactionLedgerState.pageSize;
  const pageRows = rows.slice(start, start + transactionLedgerState.pageSize);
  if (totalInfo) totalInfo.textContent = `of ${rows.length} records`;

  if (!rows.length) {
    const hasFilter = transactionLedgerState.search || transactionLedgerState.category !== "all" || transactionLedgerState.direction !== "all";
    body.innerHTML = `<tr><td colspan="7" class="transaction-empty-cell"><strong>${hasFilter ? "No matching transactions" : "No transactions yet"}</strong><span>${hasFilter ? "Try a different filter or clear your search." : "Log money in or money out to start your ledger."}</span></td></tr>`;
    if (navigation) navigation.innerHTML = `<button class="page-num-btn active" disabled>1</button>`;
    return;
  }

  body.innerHTML = pageRows.map((transaction) => {
    const isIncoming = transaction.direction === "incoming";
    const directionClass = isIncoming ? "incoming" : "outgoing";
    const amount = `${isIncoming ? "+" : "-"}${transactionHtml(transaction.currency)} ${Number(transaction.amount || 0).toFixed(2)}`;
    const pendingLabel = transaction.pending_iou_count > 0
      ? `${transaction.pending_iou_count} IOU${transaction.pending_iou_count === 1 ? "" : "s"} pending`
      : transactionStatusLabel(transaction.status);
    return `<tr data-key="${encodeURIComponent(transaction.id)}" class="transaction-row ${directionClass}">
      <td data-label="ID" class="td-txn-id">${transactionHtml(transaction.id)}</td>
      <td data-label="Transaction"><div class="td-payment-name-cell"><span class="transaction-direction-mark ${directionClass}" aria-hidden="true">${isIncoming ? "↑" : "↓"}</span><div class="transaction-title-stack"><strong class="merchant-title-text">${transactionHtml(transaction.title)}</strong><span class="transaction-meta-line">${transactionHtml(transaction.category)} · ${transactionHtml(transaction.source)}</span></div></div></td>
      <td data-label="Direction"><span class="transaction-direction-label ${directionClass}">${transactionDirectionLabel(transaction.direction)}</span></td>
      <td data-label="Amount" class="td-amount-figure ${isIncoming ? "credit" : "debit"}">${amount}</td>
      <td data-label="Date" class="td-date-cell">${transactionHtml(formatExpenseDateTime(transaction.date))}</td>
      <td data-label="Status" class="transaction-status-cell"><span class="status-badge-pill ${transactionStatusClass(transaction.status)}">${transactionHtml(pendingLabel)}</span>${transactionSettlementActions(transaction)}</td>
      <td data-label="Actions" class="transaction-actions-cell"><button type="button" class="row-action-btn" data-action="edit" data-key="${encodeURIComponent(transaction.id)}" aria-label="Edit ${transactionHtml(transaction.title)}" title="Edit transaction">${transactionActionIcon("edit")}<span class="row-action-label">Edit</span></button>${!isIncoming && transaction.split_data && transaction.split_data.friends ? `<button type="button" class="row-action-btn" data-action="details" data-record-id="${transaction.record_id}" aria-label="Open details for ${transactionHtml(transaction.title)}" title="Split details">${transactionActionIcon("split")}<span class="row-action-label">Split</span></button>` : ""}</td>
    </tr>`;
  }).join("");

  if (navigation) {
    navigation.innerHTML = `<button class="page-nav-btn" data-page="${transactionLedgerState.page - 1}" ${transactionLedgerState.page === 1 ? "disabled" : ""} aria-label="Previous page">&lsaquo;</button><span class="transaction-page-label">${transactionLedgerState.page} / ${totalPages}</span><button class="page-nav-btn" data-page="${transactionLedgerState.page + 1}" ${transactionLedgerState.page === totalPages ? "disabled" : ""} aria-label="Next page">&rsaquo;</button>`;
  }
}

window.loadUnifiedTransactions = async function loadUnifiedTransactions() {
  const params = new URLSearchParams({ direction: transactionLedgerState.direction === "pending" ? "all" : transactionLedgerState.direction, limit: "200" });
  if (transactionLedgerState.category !== "all") params.set("category", transactionLedgerState.category);
  if (transactionLedgerState.search) params.set("search", transactionLedgerState.search);
  const body = transactionElement("expenses-table-body");
  if (body && !transactionLedgerState.rows.length) body.innerHTML = `<tr><td colspan="7" class="transaction-empty-cell"><span>Loading transactions...</span></td></tr>`;
  try {
    const response = await fetch(getApiUrl(`/api/dashboard/transactions?${params.toString()}`));
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `Server returned ${response.status}`);
    transactionLedgerState.rows = data.transactions || [];
    transactionLedgerState.page = 1;
    renderUnifiedTransactions();
  } catch (error) {
    if (body) body.innerHTML = `<tr><td colspan="7" class="transaction-empty-cell error"><strong>Could not load transactions</strong><span>${transactionHtml(error.message)}</span></td></tr>`;
  }
};

window.settleUnifiedIou = async function settleUnifiedIou(key, participant) {
  try {
    const response = await fetch(getApiUrl(`/api/dashboard/transactions/${encodeURIComponent(key)}/settle`), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ participant }) });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `Server returned ${response.status}`);
    const settlement = data.settlement || {};
    showToast(`${participant} marked paid. ${settlement.currency || "SGD"} ${Number(settlement.amount_received || 0).toFixed(2)} added to money in.`);
    loadDashboardSummary();
    window.loadUnifiedTransactions();
    return true;
  } catch (error) {
    showToast(`Could not settle ${participant}: ${error.message}`, "danger");
    return false;
  }
};

function initUnifiedTransactions() {
  if (transactionLedgerState.initialized || !transactionElement("expenses-table-body")) return;
  transactionLedgerState.initialized = true;
  transactionElement("btn-open-add-transaction")?.addEventListener("click", () => openTransactionEntry());
  transactionElement("btn-refresh-expenses")?.addEventListener("click", () => window.loadUnifiedTransactions());
  transactionElement("tx-direction-filter")?.addEventListener("change", (event) => { transactionLedgerState.direction = event.target.value; transactionLedgerState.page = 1; window.loadUnifiedTransactions(); });
  transactionElement("tx-category-filter")?.addEventListener("change", (event) => { transactionLedgerState.category = event.target.value; transactionLedgerState.page = 1; window.loadUnifiedTransactions(); });
  transactionElement("tx-sort-select")?.addEventListener("change", (event) => { transactionLedgerState.sort = event.target.value; renderUnifiedTransactions(); });
  transactionElement("tx-search-input")?.addEventListener("input", (event) => { clearTimeout(transactionLedgerState.searchTimer); transactionLedgerState.search = event.target.value.trim(); transactionLedgerState.searchTimer = setTimeout(() => window.loadUnifiedTransactions(), 250); });
  transactionElement("page-size-select")?.addEventListener("change", (event) => { transactionLedgerState.pageSize = Number(event.target.value) || 10; transactionLedgerState.page = 1; renderUnifiedTransactions(); });
  transactionElement("expenses-table-body").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const key = decodeURIComponent(button.dataset.key || "");
    if (button.dataset.action === "settle") window.settleUnifiedIou(key, decodeURIComponent(button.dataset.participant || ""));
    if (button.dataset.action === "edit") openTransactionEntry("outgoing", transactionLedgerState.rows.find((row) => row.id === key));
    if (button.dataset.action === "details") window.openTransactionDetailsModal(Number(button.dataset.recordId));
  });
  transactionElement("pagination-nav-container")?.addEventListener("click", (event) => { const button = event.target.closest("button[data-page]"); if (button && !button.disabled) { transactionLedgerState.page = Number(button.dataset.page); renderUnifiedTransactions(); } });
  document.querySelectorAll(".transaction-direction-btn").forEach((button) => button.addEventListener("click", () => setTransactionDirection(button.dataset.direction)));
  transactionElement("btn-close-transaction-modal")?.addEventListener("click", closeTransactionEntry);
  transactionElement("btn-cancel-transaction")?.addEventListener("click", closeTransactionEntry);
  transactionElement("modal-add-transaction")?.addEventListener("click", (event) => { if (event.target === event.currentTarget) closeTransactionEntry(); });
  transactionElement("form-create-transaction")?.addEventListener("submit", saveUnifiedTransaction);
  transactionElement("btn-delete-transaction")?.addEventListener("click", () => deleteUnifiedTransaction(transactionLedgerState.editing));
  setTransactionDirection("outgoing");
  window.loadUnifiedTransactions();
}

window.initUnifiedTransactions = initUnifiedTransactions;
