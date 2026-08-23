const outgoingTransactionTypes = ["Dining", "Groceries", "Transport", "Shopping", "Bills", "General"];
const incomingTransactionTypes = ["Salary", "Friend Repayment", "Reimbursement", "Claim Payout", "Transfer", "Other"];

function setTransactionDirection(direction) {
  const isIncoming = direction === "incoming";
  document.querySelectorAll(".transaction-direction-btn").forEach((button) => {
    const active = button.dataset.direction === direction;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
    button.disabled = Boolean(transactionLedgerState.editing);
  });
  const category = transactionElement("transaction-category");
  const categories = isIncoming ? incomingTransactionTypes : outgoingTransactionTypes;
  if (category) {
    const previous = category.value;
    category.innerHTML = categories.map((value) => `<option value="${transactionHtml(value)}">${transactionHtml(value)}</option>`).join("");
    category.value = categories.includes(previous) ? previous : categories[0];
  }
  const label = transactionElement("transaction-counterparty-label");
  const input = transactionElement("transaction-counterparty");
  const hint = transactionElement("transaction-entry-hint");
  if (label) label.textContent = isIncoming ? "Received from" : "Merchant";
  if (input) input.placeholder = isIncoming ? "Employer, Loren, insurer..." : "FairPrice, Grab, or Amoy Hawker Centre";
  if (hint) hint.textContent = isIncoming ? "Record salary, repayments, reimbursements, or claim payouts." : "Record a purchase, bill, or other spending.";
}

function closeTransactionEntry() {
  const modal = transactionElement("modal-add-transaction");
  if (modal) modal.style.display = "none";
  transactionLedgerState.editing = null;
}

function openTransactionEntry(direction = "outgoing", transaction = null) {
  const modal = transactionElement("modal-add-transaction");
  const form = transactionElement("form-create-transaction");
  if (!modal || !form) return;
  transactionLedgerState.editing = transaction;
  form.reset();
  transactionElement("transaction-edit-id").value = transaction ? transaction.id : "";
  setTransactionDirection(transaction ? transaction.direction : direction);
  if (transaction) {
    transactionElement("transaction-amount").value = transaction.amount;
    transactionElement("transaction-currency").value = transaction.currency || "SGD";
    transactionElement("transaction-counterparty").value = transaction.counterparty || "";
    transactionElement("transaction-category").value = transaction.category || "Other";
    transactionElement("transaction-date").value = transactionDateValue(transaction.date);
    transactionElement("transaction-notes").value = transaction.notes || "";
  } else {
    transactionElement("transaction-date").value = localDateTimeValue();
  }
  transactionElement("transaction-entry-title").textContent = transaction ? "Edit transaction" : "Log transaction";
  transactionElement("transaction-entry-subtitle").textContent = transaction ? "Correct the record without changing its direction." : "Keep money in and money out in one timeline.";
  transactionElement("btn-submit-transaction").textContent = transaction ? "Save changes" : "Save transaction";
  transactionElement("btn-delete-transaction").style.display = transaction ? "inline-flex" : "none";
  transactionElement("transaction-form-error").textContent = "";
  modal.style.display = "flex";
  transactionElement("transaction-amount").focus();
}

async function saveUnifiedTransaction(event) {
  event.preventDefault();
  const direction = transactionLedgerState.editing?.direction || document.querySelector(".transaction-direction-btn.active")?.dataset.direction || "outgoing";
  const amount = Number(transactionElement("transaction-amount").value);
  const counterparty = transactionElement("transaction-counterparty").value.trim();
  const errorBox = transactionElement("transaction-form-error");
  if (!(amount > 0) || !counterparty) {
    errorBox.textContent = "Enter an amount and who the transaction is with.";
    return;
  }
  const payload = {
    direction,
    amount,
    currency: transactionElement("transaction-currency").value,
    counterparty,
    category: transactionElement("transaction-category").value,
    date: transactionElement("transaction-date").value ? new Date(transactionElement("transaction-date").value).toISOString() : null,
    notes: transactionElement("transaction-notes").value.trim() || null,
  };
  const button = transactionElement("btn-submit-transaction");
  const key = transactionLedgerState.editing?.id;
  button.disabled = true;
  button.textContent = "Saving...";
  try {
    const url = key ? `/api/dashboard/transactions/${encodeURIComponent(key)}` : "/api/dashboard/transactions";
    const response = await fetch(getApiUrl(url), { method: key ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `Server returned ${response.status}`);
    closeTransactionEntry();
    showToast(key ? "Transaction updated." : "Transaction saved.");
    loadDashboardSummary();
    window.loadUnifiedTransactions();
  } catch (error) {
    errorBox.textContent = `Could not save transaction: ${error.message}`;
  } finally {
    button.disabled = false;
    button.textContent = key ? "Save changes" : "Save transaction";
  }
}

async function deleteUnifiedTransaction(transaction) {
  if (!transaction || !confirm(`Delete ${transaction.title} ${transaction.id}?`)) return;
  try {
    const response = await fetch(getApiUrl(`/api/dashboard/transactions/${encodeURIComponent(transaction.id)}`), { method: "DELETE" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `Server returned ${response.status}`);
    closeTransactionEntry();
    showToast("Transaction deleted.", "danger");
    loadDashboardSummary();
    window.loadUnifiedTransactions();
  } catch (error) {
    showToast(`Could not delete transaction: ${error.message}`, "danger");
  }
}

window.openExpenseModal = () => openTransactionEntry("outgoing");
window.openIncomeModal = () => openTransactionEntry("incoming");
window.openEditExpenseModal = (id) => openTransactionEntry("outgoing", transactionLedgerState.rows.find((row) => row.record_id === id && row.direction === "outgoing"));
window.openEditIncomeModal = (id) => openTransactionEntry("incoming", transactionLedgerState.rows.find((row) => row.record_id === id && row.direction === "incoming"));
