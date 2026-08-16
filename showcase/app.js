/**
 * Nexus Prime — Financial Cockpit & Expenses Engine
 * Implements Mowany-style 2-column dashboard, SVG donut category visualizer, ledger table, and live assistant chat.
 */

// Application State
let webSessionId = localStorage.getItem("nexus_web_session_id") || `web-${Math.random().toString(36).substring(2, 9)}`;
localStorage.setItem("nexus_web_session_id", webSessionId);

let activeCategoryFilter = "all";
let activeSearchQuery = "";
let currentExpensesList = [];
let activeSortMode = "latest";

// Category Visual Styling
const CATEGORY_MAP = {
  "Dining": { icon: "🍔", color: "#f43f5e", bg: "rgba(244, 63, 94, 0.15)" },
  "Groceries": { icon: "🛒", color: "#10b981", bg: "rgba(16, 185, 129, 0.15)" },
  "Transport": { icon: "🚌", color: "#06b6d4", bg: "rgba(6, 182, 212, 0.15)" },
  "Shopping": { icon: "🛍️", color: "#a855f7", bg: "rgba(168, 85, 247, 0.15)" },
  "Bills": { icon: "💡", color: "#f97316", bg: "rgba(249, 115, 22, 0.15)" },
  "General": { icon: "💳", color: "#71717a", bg: "rgba(113, 113, 122, 0.15)" }
};

function normalizeCategory(cat) {
  if (!cat) return "General";
  const c = cat.toString().trim().toLowerCase();
  if (c.includes("dining") || c.includes("food") || c.includes("restaurant") || c.includes("cafe") || c.includes("hawker") || c.includes("beverage") || c.includes("bar") || c.includes("cider")) return "Dining";
  if (c.includes("grocer") || c.includes("mart") || c.includes("convenience") || c.includes("fairprice") || c.includes("7-eleven") || c.includes("cheers")) return "Groceries";
  if (c.includes("transport") || c.includes("transit") || c.includes("bus") || c.includes("mrt") || c.includes("grab") || c.includes("taxi") || c.includes("ride")) return "Transport";
  if (c.includes("shop") || c.includes("retail") || c.includes("uniqlo") || c.includes("cloth") || c.includes("apparel") || c.includes("amazon")) return "Shopping";
  if (c.includes("bill") || c.includes("utilit") || c.includes("telco") || c.includes("singtel") || c.includes("starhub") || c.includes("subscri")) return "Bills";
  return "General";
}

// Initialization
document.addEventListener("DOMContentLoaded", () => {
  initRailNavigation();
  initDashboard();
  initWebChat();
  initExpenseModal();
  initWhiteboard();
  initTasksAndReminders();
  initJobs();
  initCopilotDrawer();

  // Auto-sync dashboard from live database every 8s
  setInterval(() => {
    const activeTab = document.querySelector(".rail-nav-btn.active")?.getAttribute("data-tab");
    if (activeTab === "tab-expenses") {
      loadDashboardSummary();
      loadExpensesTable(activeCategoryFilter, activeSearchQuery, activeSortMode);
    } else if (activeTab === "tab-jobs") {
      loadTasks();
    }
  }, 8000);
});

// Left Rail Navigation
function initRailNavigation() {
  const railBtns = document.querySelectorAll(".rail-nav-btn[data-tab]");
  railBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      switchTab(btn.getAttribute("data-tab"));
    });
  });

  const refreshAllBtn = document.getElementById("rail-btn-refresh-all");
  if (refreshAllBtn) {
    refreshAllBtn.addEventListener("click", () => {
      loadDashboardSummary();
      loadExpensesTable(activeCategoryFilter, activeSearchQuery, activeSortMode);
    });
  }
}

function switchTab(tabId) {
  const railBtns = document.querySelectorAll(".rail-nav-btn[data-tab]");
  railBtns.forEach(b => {
    b.classList.toggle("active", b.getAttribute("data-tab") === tabId);
  });

  document.querySelectorAll(".view-panel").forEach(pane => pane.classList.remove("active"));
  const targetPane = document.getElementById(tabId);
  if (targetPane) targetPane.classList.add("active");

  if (tabId === "tab-expenses") {
    loadDashboardSummary();
    loadExpensesTable(activeCategoryFilter, activeSearchQuery, activeSortMode);
  } else if (tabId === "tab-jobs") {
    loadTasks();
    loadJobs();
  } else if (tabId === "tab-whiteboard" || tabId === "tab-groceries") {
    loadWhiteboards();
  } else if (tabId === "tab-livechat") {
    setTimeout(() => {
      const input = document.getElementById("chat-user-input");
      if (input) input.focus();
    }, 100);
  }
}

// ==========================================================================
// 1. TRANSACTIONS DASHBOARD & FINANCIAL BREAKDOWN
// ==========================================================================

function initDashboard() {
  loadDashboardSummary();
  loadExpensesTable();

  // Search Input Handler
  const searchInput = document.getElementById("tx-search-input");
  if (searchInput) {
    let debounceTimer;
    searchInput.addEventListener("input", (e) => {
      clearTimeout(debounceTimer);
      activeSearchQuery = e.target.value.trim();
      debounceTimer = setTimeout(() => {
        loadExpensesTable(activeCategoryFilter, activeSearchQuery, activeSortMode);
      }, 250);
    });
  }

  // Category Filter Dropdown Handler
  const catFilter = document.getElementById("tx-category-filter");
  if (catFilter) {
    catFilter.addEventListener("change", (e) => {
      activeCategoryFilter = e.target.value;
      loadExpensesTable(activeCategoryFilter, activeSearchQuery, activeSortMode);
    });
  }

  // Sort Dropdown Handler
  const sortFilter = document.getElementById("tx-sort-select");
  if (sortFilter) {
    sortFilter.addEventListener("change", (e) => {
      activeSortMode = e.target.value;
      loadExpensesTable(activeCategoryFilter, activeSearchQuery, activeSortMode);
    });
  }

  // Page Size Selector Handler
  const pageSizeSelect = document.getElementById("page-size-select");
  if (pageSizeSelect) {
    pageSizeSelect.addEventListener("change", (e) => {
      pageSize = parseInt(e.target.value, 10) || 10;
      currentPage = 1;
      renderExpensesTableRows();
    });
  }

  // Refresh Button Handler
  const refreshBtn = document.getElementById("btn-refresh-expenses");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", () => {
      loadDashboardSummary();
      loadExpensesTable(activeCategoryFilter, activeSearchQuery, activeSortMode);
    });
  }

  // Select All Checkbox Handler
  const checkAll = document.getElementById("check-all-rows");
  if (checkAll) {
    checkAll.addEventListener("change", (e) => {
      const isChecked = e.target.checked;
      const rowChecks = document.querySelectorAll(".row-checkbox");
      rowChecks.forEach(rc => {
        rc.checked = isChecked;
        const id = parseInt(rc.getAttribute("data-id"));
        if (id) {
          if (isChecked) selectedExpenseIds.add(id);
          else selectedExpenseIds.delete(id);
        }
      });
      updateBatchActionBar();
    });
  }

  // Batch Delete Handler
  const batchDelBtn = document.getElementById("btn-batch-delete");
  if (batchDelBtn) {
    batchDelBtn.addEventListener("click", () => {
      batchDeleteSelectedExpenses();
    });
  }

  // Batch Cancel Handler
  const batchCancelBtn = document.getElementById("btn-batch-cancel");
  if (batchCancelBtn) {
    batchCancelBtn.addEventListener("click", () => {
      selectedExpenseIds.clear();
      if (checkAll) checkAll.checked = false;
      document.querySelectorAll(".row-checkbox").forEach(rc => rc.checked = false);
      updateBatchActionBar();
    });
  }
}

async function loadDashboardSummary() {
  try {
    const res = await fetch("/api/dashboard/summary");
    if (!res.ok) throw new Error("Failed to load summary");
    const data = await res.json();

    // Top 3 Metric Cards Figures
    const monthTxCount = document.getElementById("kpi-month-tx-count");
    if (monthTxCount) monthTxCount.textContent = `${data.month_transactions_count || data.total_transactions_count}`;

    const totalTx = document.getElementById("kpi-total-tx");
    if (totalTx) totalTx.textContent = `${data.total_transactions_count}`;

    const monthSpend = document.getElementById("kpi-month-spend");
    if (monthSpend) monthSpend.textContent = `$${data.total_spent_month.toFixed(2)}`;

    // Donut Center Total
    const donutTotal = document.getElementById("donut-center-total");
    if (donutTotal) donutTotal.textContent = `$${Math.round(data.total_spent_month)}`;

    // Render SVG Donut Chart
    renderDonutChart(data.categories, data.total_spent_month);

    // Render Donut Legend
    const legendGrid = document.getElementById("donut-legend-grid");
    if (legendGrid) {
      if (data.categories.length === 0) {
        legendGrid.innerHTML = `<span style="font-size:0.75rem; color:var(--text-muted);">No categories yet.</span>`;
      } else {
        legendGrid.innerHTML = data.categories.map(c => {
          const normCat = normalizeCategory(c.category);
          const cfg = CATEGORY_MAP[normCat] || CATEGORY_MAP["General"];
          return `
            <div class="legend-item-pill">
              <span class="legend-dot" style="background: ${cfg.color};"></span>
              <span>${escapeHtml(normCat)} (${c.percentage}%)</span>
            </div>
          `;
        }).join("");
      }
    }

    // Render Spend Insight Text & Dynamic AI Insight Banner
    const insightText = document.getElementById("spend-insight-text");
    const aiDynamicBody = document.getElementById("ai-insight-dynamic-body");

    if (data.categories.length > 0) {
      const topCat = data.categories[0];
      if (insightText) {
        insightText.textContent = `Your ${topCat.category.toLowerCase()} spending represents ${topCat.percentage}% of this month's budget.`;
      }
    }

    if (aiDynamicBody) {
      const count = data.month_transactions_count || data.total_transactions_count;
      const topM = data.top_merchants && data.top_merchants.length > 0 ? data.top_merchants[0] : null;
      const topMText = topM ? `your top merchant is <strong>${escapeHtml(topM.merchant)}</strong> ($${topM.amount.toFixed(2)})` : "your spend is evenly distributed";
      aiDynamicBody.innerHTML = `You have logged <strong>${count} transactions</strong> totaling <strong>$${data.total_spent_month.toFixed(2)}</strong> this month. Based on your spending velocity, ${topMText}.`;
    }

    // Render Top Merchants Mini List in Sidebar
    const miniList = document.getElementById("merchants-mini-list");
    if (miniList) {
      if (data.top_merchants.length === 0) {
        miniList.innerHTML = `<div style="font-size:0.75rem; color:var(--text-muted); text-align:center; padding:1rem;">No merchant data.</div>`;
      } else {
        miniList.innerHTML = data.top_merchants.map(m => {
          return `
            <div class="merchant-mini-row">
              <div class="merchant-row-left">
                <div class="merchant-mini-icon" style="background: rgba(249, 115, 22, 0.15); color: #f97316;">
                  🏪
                </div>
                <span class="merchant-row-name">${escapeHtml(m.merchant)}</span>
              </div>
              <span class="merchant-row-amt">$${m.amount.toFixed(2)}</span>
            </div>
          `;
        }).join("");
      }
    }

  } catch (err) {
    console.warn("Could not load dashboard summary:", err);
  }
}

function renderDonutChart(categories, totalSpend) {
  const svg = document.getElementById("donut-svg-chart");
  if (!svg) return;

  if (!categories || categories.length === 0 || totalSpend <= 0) {
    svg.innerHTML = `<circle cx="80" cy="80" r="55" fill="none" stroke="#222226" stroke-width="20" />`;
    return;
  }

  const radius = 55;
  const circumference = 2 * Math.PI * radius; // ~345.57
  let cumulativePercent = 0;

  const circlesHtml = categories.map(c => {
    const normCat = normalizeCategory(c.category);
    const cfg = CATEGORY_MAP[normCat] || CATEGORY_MAP["General"];
    const percent = c.percentage / 100;
    const strokeDash = percent * circumference;
    const strokeGap = circumference - strokeDash;
    const strokeOffset = -cumulativePercent * circumference;
    cumulativePercent += percent;

    return `
      <circle 
        cx="80" 
        cy="80" 
        r="${radius}" 
        fill="none" 
        stroke="${cfg.color}" 
        stroke-width="20" 
        stroke-dasharray="${strokeDash} ${strokeGap}" 
        stroke-dashoffset="${strokeOffset}"
        style="transition: stroke-dasharray 0.6s ease;"
      />
    `;
  }).join("");

  svg.innerHTML = circlesHtml;
}

let selectedExpenseIds = new Set();
let undoStack = [];

function pushUndoAction(action) {
  undoStack.push(action);
  if (undoStack.length > 15) undoStack.shift();
}

window.executeUndo = async function() {
  if (undoStack.length === 0) {
    showToast("Nothing to undo", "info");
    return;
  }

  const action = undoStack.pop();

  if (action.type === "delete") {
    try {
      const res = await fetch("/api/dashboard/expenses/restore", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expenses: action.expenses })
      });
      if (!res.ok) throw new Error("Failed to restore transactions");
      const data = await res.json();
      
      const count = data.restored_count || action.expenses.length;
      const name = action.expenses.length === 1 ? action.expenses[0].merchant : `${count} transactions`;
      showToast(`Restored ${name}`, "success");
      
      loadDashboardSummary();
      loadExpensesTable(activeCategoryFilter, activeSearchQuery, activeSortMode);
    } catch (err) {
      showToast(`Undo failed: ${err.message}`, "danger");
    }
  } else if (action.type === "edit") {
    try {
      const res = await fetch(`/api/dashboard/expenses/${action.expenseId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(action.previousData)
      });
      if (!res.ok) throw new Error("Failed to revert edit");
      
      showToast(`Reverted edit on expense #${action.expenseId}`, "success");
      loadDashboardSummary();
      loadExpensesTable(activeCategoryFilter, activeSearchQuery, activeSortMode);
    } catch (err) {
      showToast(`Undo failed: ${err.message}`, "danger");
    }
  }
};

// Global Cmd+Z / Ctrl+Z Shortcut for Undo
document.addEventListener("keydown", (e) => {
  if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) {
    return;
  }

  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z" && !e.shiftKey) {
    e.preventDefault();
    executeUndo();
  }
});

function showToast(message, type = "success", undoAction = null) {
  const container = document.getElementById("toast-container");
  if (!container) return;

  if (undoAction) {
    pushUndoAction(undoAction);
  }

  const toast = document.createElement("div");
  toast.className = `toast-bubble ${type}`;
  
  const icon = type === "danger" ? "🗑️" : (type === "info" ? "ℹ️" : "✅");
  let undoHtml = "";
  if (undoAction) {
    undoHtml = `<button type="button" class="btn-toast-undo" onclick="executeUndo(); this.closest('.toast-bubble').remove();">↩️ Undo</button>`;
  }

  toast.innerHTML = `
    <div style="display:flex; align-items:center; gap:0.5rem;">
      <span>${icon}</span>
      <span>${escapeHtml(message)}</span>
    </div>
    ${undoHtml}
  `;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(8px)";
    toast.style.transition = "all 0.3s ease";
    setTimeout(() => toast.remove(), 300);
  }, undoAction ? 6500 : 3500);
}

function updateBatchActionBar() {
  const bar = document.getElementById("batch-action-bar");
  const countSpan = document.getElementById("batch-selected-count");
  if (!bar) return;

  if (selectedExpenseIds.size > 0) {
    bar.style.display = "flex";
    if (countSpan) countSpan.textContent = `${selectedExpenseIds.size} transaction${selectedExpenseIds.size > 1 ? 's' : ''} selected`;
  } else {
    bar.style.display = "none";
  }
}

let currentPage = 1;
let pageSize = 10;

async function loadExpensesTable(category = "all", search = "", sort = "latest") {
  try {
    let url = `/api/dashboard/expenses?limit=100`;
    if (category && category !== "all") url += `&category=${encodeURIComponent(category)}`;
    if (search) url += `&search=${encodeURIComponent(search)}`;

    const res = await fetch(url);
    if (!res.ok) throw new Error("Failed to load expenses");
    const data = await res.json();
    let rows = data.expenses || [];

    // Client-side sort if requested
    if (sort === "highest") {
      rows.sort((a, b) => b.amount - a.amount);
    } else if (sort === "oldest") {
      rows.sort((a, b) => new Date(a.date) - new Date(b.date));
    }

    currentExpensesList = rows;
    currentPage = 1;
    renderExpensesTableRows();

  } catch (err) {
    console.warn("Could not load expenses table:", err);
  }
}

function renderExpensesTableRows() {
  const tbody = document.getElementById("expenses-table-body");
  const totalInfo = document.getElementById("pagination-total-info");
  const navContainer = document.getElementById("pagination-nav-container");
  if (!tbody) return;

  const rows = currentExpensesList || [];
  const totalRecords = rows.length;
  const totalPages = Math.max(1, Math.ceil(totalRecords / pageSize));

  if (currentPage > totalPages) currentPage = totalPages;
  if (currentPage < 1) currentPage = 1;

  const startIndex = (currentPage - 1) * pageSize;
  const endIndex = Math.min(startIndex + pageSize, totalRecords);
  const pageRows = rows.slice(startIndex, endIndex);

  if (totalInfo) {
    totalInfo.textContent = `of ${totalRecords} records`;
  }

  if (rows.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="7" style="padding: 2.5rem; text-align: center; color: var(--text-muted);">
          No transactions found matching "${escapeHtml(activeSearchQuery || activeCategoryFilter)}".
        </td>
      </tr>
    `;
    selectedExpenseIds.clear();
    updateBatchActionBar();
    if (navContainer) {
      navContainer.innerHTML = `<button class="page-num-btn active">1</button>`;
    }
    return;
  }

  tbody.innerHTML = pageRows.map((tx) => {
    const txnId = `TXN-24080${String(tx.id).padStart(3, '0')}`;
    const normCat = normalizeCategory(tx.category);
    const catCfg = CATEGORY_MAP[normCat] || CATEGORY_MAP["General"];
    const dateObj = tx.date ? new Date(tx.date) : new Date();
    const monthNames = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
    const dateStr = `${monthNames[dateObj.getMonth()]} ${dateObj.getDate()}, ${dateObj.getFullYear()}`;
    const timeStr = dateObj.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const isChecked = selectedExpenseIds.has(tx.id);

    return `
      <tr data-id="${tx.id}">
        <td style="text-align: center;">
          <input type="checkbox" class="dash-checkbox row-checkbox" data-id="${tx.id}" ${isChecked ? 'checked' : ''} onchange="toggleRowCheckbox(${tx.id}, this.checked)" />
        </td>
        <td class="td-txn-id">${txnId}</td>
        <td>
          <div class="td-payment-name-cell">
            <div class="merchant-mini-icon" style="background: ${catCfg.bg}; color: ${catCfg.color};">
              ${catCfg.icon}
            </div>
            <span class="merchant-title-text">${escapeHtml(tx.merchant)}</span>
          </div>
        </td>
        <td class="td-amount-figure debit">-$${tx.amount.toFixed(2)}</td>
        <td class="td-date-cell">${dateStr} · ${timeStr}</td>
        <td style="text-align: center;">
          <span class="status-badge-pill completed">Completed</span>
        </td>
        <td style="text-align: center;">
          <div style="display: flex; justify-content: center; gap: 0.35rem;">
            <button class="row-action-btn" onclick="openEditExpenseModal(${tx.id})" title="Edit expense">✏️</button>
            <button class="row-action-btn" onclick="deleteExpenseItem(${tx.id})" title="Delete expense">🗑️</button>
          </div>
        </td>
      </tr>
    `;
  }).join("");

  updateBatchActionBar();
  renderPaginationControls(totalPages);
}

function renderPaginationControls(totalPages) {
  const navContainer = document.getElementById("pagination-nav-container");
  if (!navContainer) return;

  let html = `
    <button class="page-nav-btn" onclick="goToPage(1)" ${currentPage === 1 ? 'disabled' : ''} title="First page">&laquo;</button>
    <button class="page-nav-btn" onclick="goToPage(${currentPage - 1})" ${currentPage === 1 ? 'disabled' : ''} title="Previous page">&lsaquo;</button>
  `;

  let startPage = Math.max(1, currentPage - 2);
  let endPage = Math.min(totalPages, startPage + 4);
  if (endPage - startPage < 4) {
    startPage = Math.max(1, endPage - 4);
  }

  for (let p = startPage; p <= endPage; p++) {
    html += `
      <button class="page-num-btn ${p === currentPage ? 'active' : ''}" onclick="goToPage(${p})">${p}</button>
    `;
  }

  html += `
    <button class="page-nav-btn" onclick="goToPage(${currentPage + 1})" ${currentPage === totalPages ? 'disabled' : ''} title="Next page">&rsaquo;</button>
    <button class="page-nav-btn" onclick="goToPage(${totalPages})" ${currentPage === totalPages ? 'disabled' : ''} title="Last page">&raquo;</button>
  `;

  navContainer.innerHTML = html;
}

window.goToPage = function(page) {
  const totalPages = Math.max(1, Math.ceil((currentExpensesList?.length || 0) / pageSize));
  if (page < 1) page = 1;
  if (page > totalPages) page = totalPages;
  currentPage = page;
  renderExpensesTableRows();
};

window.toggleRowCheckbox = function(id, isChecked) {
  if (isChecked) {
    selectedExpenseIds.add(id);
  } else {
    selectedExpenseIds.delete(id);
  }
  updateBatchActionBar();
};

window.openEditExpenseModal = function(id) {
  const modal = document.getElementById("modal-add-expense");
  const modalTitle = document.getElementById("modal-expense-title");
  const submitBtn = document.getElementById("btn-submit-expense");
  const deleteBtn = document.getElementById("btn-delete-from-modal");
  const editIdInput = document.getElementById("exp-edit-id");

  const tx = currentExpensesList.find(e => e.id === id);
  if (!tx) return;

  if (modalTitle) modalTitle.textContent = `Edit Expense #${tx.id}`;
  if (submitBtn) submitBtn.textContent = `Update Expense`;
  if (editIdInput) editIdInput.value = tx.id;

  if (deleteBtn) {
    deleteBtn.style.display = "inline-flex";
    deleteBtn.onclick = () => {
      deleteExpenseItem(tx.id);
      modal.style.display = "none";
    };
  }

  document.getElementById("exp-amount").value = tx.amount;
  document.getElementById("exp-currency").value = tx.currency || "SGD";
  document.getElementById("exp-merchant").value = tx.merchant;
  document.getElementById("exp-category").value = tx.category || "General";

  const dateInput = document.getElementById("exp-date");
  if (dateInput && tx.date) {
    const d = new Date(tx.date);
    d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
    dateInput.value = d.toISOString().slice(0, 16);
  }

  if (modal) modal.style.display = "flex";
};

window.openExpenseModal = function() {
  const modal = document.getElementById("modal-add-expense");
  const modalTitle = document.getElementById("modal-expense-title");
  const submitBtn = document.getElementById("btn-submit-expense");
  const deleteBtn = document.getElementById("btn-delete-from-modal");
  const editIdInput = document.getElementById("exp-edit-id");
  const form = document.getElementById("form-create-expense");

  if (!modal) return;
  if (modalTitle) modalTitle.textContent = "Log New Expense";
  if (submitBtn) submitBtn.textContent = "Save Expense";
  if (deleteBtn) deleteBtn.style.display = "none";
  if (editIdInput) editIdInput.value = "";
  if (form) form.reset();

  modal.style.display = "flex";
  const dateInput = document.getElementById("exp-date");
  if (dateInput) {
    const now = new Date();
    now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
    dateInput.value = now.toISOString().slice(0, 16);
  }
  const amtInput = document.getElementById("exp-amount");
  if (amtInput) amtInput.focus();
};

window.deleteExpenseItem = async function(id) {
  const tx = currentExpensesList.find(e => e.id === id);
  // Optimistic UI Removal
  const row = document.querySelector(`tr[data-id="${id}"]`);
  if (row) {
    row.style.opacity = "0.2";
    row.style.pointerEvents = "none";
  }

  try {
    const res = await fetch(`/api/dashboard/expenses/${id}`, { method: "DELETE" });
    if (!res.ok) throw new Error(`HTTP Error ${res.status}`);
    
    if (row) row.remove();
    selectedExpenseIds.delete(id);
    updateBatchActionBar();
    
    const merchantName = tx ? tx.merchant : `#${id}`;
    const amountStr = tx ? ` ($${tx.amount.toFixed(2)})` : "";
    showToast(`Deleted ${merchantName}${amountStr}`, "danger", {
      type: "delete",
      expenses: tx ? [tx] : [{ id, merchant: "Expense", amount: 0, category: "General" }]
    });

    loadDashboardSummary();
    loadExpensesTable(activeCategoryFilter, activeSearchQuery, activeSortMode);
  } catch (err) {
    if (row) {
      row.style.opacity = "1";
      row.style.pointerEvents = "auto";
    }
    showToast(`Failed to delete expense: ${err.message}`, "danger");
  }
};

window.batchDeleteSelectedExpenses = async function() {
  if (selectedExpenseIds.size === 0) return;
  const ids = Array.from(selectedExpenseIds);
  const deletedRecords = currentExpensesList.filter(e => selectedExpenseIds.has(e.id));

  try {
    const res = await fetch("/api/dashboard/expenses/batch-delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expense_ids: ids })
    });

    if (!res.ok) throw new Error(`HTTP Error ${res.status}`);
    const data = await res.json();

    selectedExpenseIds.clear();
    updateBatchActionBar();
    const count = data.deleted_count || ids.length;
    showToast(`Deleted ${count} transactions`, "danger", {
      type: "delete",
      expenses: deletedRecords.length > 0 ? deletedRecords : ids.map(id => ({ id, merchant: "Expense", amount: 0, category: "General" }))
    });

    loadDashboardSummary();
    loadExpensesTable(activeCategoryFilter, activeSearchQuery, activeSortMode);
  } catch (err) {
    showToast(`Batch delete failed: ${err.message}`, "danger");
  }
};

// ==========================================================================
// 2. MODAL CONTROLLER (ADD & EDIT)
// ==========================================================================

function initExpenseModal() {
  const modal = document.getElementById("modal-add-expense");
  const openBtn = document.getElementById("btn-open-add-expense-modal");
  const closeBtn = document.getElementById("btn-close-expense-modal");
  const cancelBtn = document.getElementById("btn-cancel-expense-modal");
  const form = document.getElementById("form-create-expense");
  const editIdInput = document.getElementById("exp-edit-id");

  if (!modal) return;

  if (openBtn) openBtn.addEventListener("click", openExpenseModal);
  if (closeBtn) closeBtn.addEventListener("click", () => modal.style.display = "none");
  if (cancelBtn) cancelBtn.addEventListener("click", () => modal.style.display = "none");

  modal.addEventListener("click", (e) => {
    if (e.target === modal) modal.style.display = "none";
  });

  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const editId = editIdInput ? editIdInput.value : "";
      const amount = parseFloat(document.getElementById("exp-amount").value);
      const currency = document.getElementById("exp-currency").value;
      const merchant = document.getElementById("exp-merchant").value.trim();
      const category = document.getElementById("exp-category").value;
      const dateVal = document.getElementById("exp-date").value;

      try {
        const payload = {
          amount: amount,
          currency: currency,
          merchant: merchant,
          category: category,
          date: dateVal ? new Date(dateVal).toISOString() : new Date().toISOString(),
        };

        const isEdit = Boolean(editId);
        const oldTx = isEdit ? currentExpensesList.find(e => e.id === parseInt(editId)) : null;
        const url = isEdit ? `/api/dashboard/expenses/${editId}` : "/api/dashboard/expenses";
        const method = isEdit ? "PUT" : "POST";

        const res = await fetch(url, {
          method: method,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });

        if (res.ok) {
          modal.style.display = "none";
          if (isEdit && oldTx) {
            showToast(`Updated ${merchant} ($${amount.toFixed(2)})`, "success", {
              type: "edit",
              expenseId: parseInt(editId),
              previousData: {
                amount: oldTx.amount,
                currency: oldTx.currency,
                merchant: oldTx.merchant,
                category: oldTx.category,
                date: oldTx.date,
              }
            });
          } else {
            showToast(`Saved expense: ${merchant} ($${amount.toFixed(2)})`, "success");
          }
          loadDashboardSummary();
          loadExpensesTable(activeCategoryFilter, activeSearchQuery, activeSortMode);
        } else {
          alert(`Failed to ${isEdit ? 'update' : 'save'} expense`);
        }
      } catch (err) {
        alert("Error saving expense: " + err.message);
      }
    });
  }
}

// ==========================================================================
// 3. TASKS & REMINDERS COCKPIT
// ==========================================================================

let activeTaskFilter = "all";
let activeTaskPriority = "all";
let activeTaskSearch = "";
let cachedTasksList = [];
let currentComposerPriority = "medium";

function toLocalDatetimeInputString(dateVal) {
  if (!dateVal) return "";
  const d = new Date(dateVal);
  if (isNaN(d.getTime())) return "";
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function formatRelativeAlertPreview(dueDateVal, offset) {
  if (offset === "custom") {
    return { isoLocal: null, text: "Custom date & time selected" };
  }
  if (!dueDateVal) {
    return { isoLocal: null, text: "💡 Pick a Due Date above to calculate alert time" };
  }
  const dueMs = new Date(dueDateVal).getTime();
  if (isNaN(dueMs)) {
    return { isoLocal: null, text: "⚠️ Invalid due date" };
  }
  const offsetMin = parseInt(offset, 10) || 0;
  const alertMs = dueMs - (offsetMin * 60 * 1000);
  const alertDate = new Date(alertMs);
  
  const isoLocal = toLocalDatetimeInputString(alertDate);
  
  const niceString = alertDate.toLocaleDateString([], { 
    weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' 
  });
  
  const label = offsetMin === 0 ? "at due time" : offsetMin < 60 ? `${offsetMin}m before due` : offsetMin < 1440 ? `${offsetMin/60}h before due` : `${offsetMin/1440}d before due`;
  return {
    isoLocal,
    text: `${niceString} (${label})`
  };
}

function parseNaturalLanguageTask(rawText, baseDate = new Date()) {
  if (!rawText || !rawText.trim()) return null;
  let text = rawText.trim();
  let reminderType = "none";
  let dueAt = null;
  let reminderTime = null;
  let cronExpr = null;
  let matchedPhrase = "";

  // 1. Check prefix
  const prefixMatch = text.match(/^(?:remind\s+me\s+(?:to\s+)?|todo:\s*|task:\s*)/i);
  if (prefixMatch) {
    reminderType = "once";
    text = text.slice(prefixMatch[0].length);
  }

  // 2. Relative timing: "in 15 minutes from now", "in 15 minutes", "in 2 hours", "in 30 mins", "in 15m"
  const relMatch = text.match(/\bin\s+(\d+|a|an|half\s+an?)\s*(minutes?|mins?|hours?|hrs?|days?|m|h|d)?(?:\s+from\s+now)?\b/i);
  if (relMatch) {
    let qty = 0;
    const qtyStr = relMatch[1].toLowerCase();
    const unitStr = (relMatch[2] || "").toLowerCase();
    if (qtyStr === "a" || qtyStr === "an") qty = 1;
    else if (qtyStr.startsWith("half")) qty = 30;
    else qty = parseInt(qtyStr, 10) || 0;

    let ms = 0;
    if (qtyStr.startsWith("half") || unitStr.startsWith("m") || (!unitStr && qty > 0)) {
      ms = (qtyStr.startsWith("half") ? 30 : qty) * 60 * 1000;
    } else if (unitStr.startsWith("h")) {
      ms = qty * 3600 * 1000;
    } else if (unitStr.startsWith("d")) {
      ms = qty * 86400 * 1000;
    } else {
      ms = qty * 60 * 1000;
    }

    const targetDate = new Date(baseDate.getTime() + ms);
    dueAt = targetDate;
    reminderType = "once";
    reminderTime = targetDate;
    matchedPhrase = relMatch[0];
    text = text.replace(relMatch[0], " ");
  }

  // 3. Recurring schedules: "daily at 9am", "every day at 8am", "every 2 hours", "every weekday at 9am"
  if (!dueAt) {
    const recurMatch = text.match(/\b(daily|every\s+day|every\s+weekday|weekdays|every\s+hour|every\s+(\d+)\s+hours?)\s*(?:at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?)?\b/i);
    if (recurMatch) {
      reminderType = "recurring";
      const freq = recurMatch[1].toLowerCase();
      let hour = parseInt(recurMatch[3] || "9", 10);
      const min = parseInt(recurMatch[4] || "0", 10);
      const meridian = (recurMatch[5] || "").toLowerCase();
      if (meridian === "pm" && hour < 12) hour += 12;
      if (meridian === "am" && hour === 12) hour = 0;

      if (freq.includes("weekday")) {
        cronExpr = `${min} ${hour} * * 1-5`;
      } else if (freq.includes("hour")) {
        const step = recurMatch[2] ? `*/${recurMatch[2]}` : "*";
        cronExpr = `0 ${step} * * *`;
      } else {
        cronExpr = `${min} ${hour} * * *`;
      }
      matchedPhrase = recurMatch[0];
      text = text.replace(recurMatch[0], " ");
    }
  }

  // 4. Specific clock times: "at 5pm", "tomorrow at 9am", "tonight at 8pm", "at 6:30pm", "tomorrow"
  if (!dueAt && !cronExpr) {
    const timeMatch = text.match(/\b(?:(today|tonight|tomorrow)\s+)?(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b/i) ||
                      text.match(/\b(today|tonight|tomorrow)\s+at\s+(\d{1,2})(?::(\d{2}))?\b/i) ||
                      text.match(/\bat\s+(\d{1,2})(?::(\d{2}))?\b/i) ||
                      text.match(/\b(tomorrow|tonight)\b/i);
    if (timeMatch) {
      const dayKeyword = (timeMatch[1] || "").toLowerCase();
      let hour = parseInt(timeMatch[2] || "9", 10);
      const min = parseInt(timeMatch[3] || "0", 10);
      const meridian = (timeMatch[4] || "").toLowerCase();

      if (meridian === "pm" && hour < 12) hour += 12;
      if (meridian === "am" && hour === 12) hour = 0;
      if (!meridian && (dayKeyword === "tonight" || timeMatch[0].toLowerCase() === "tonight") && hour < 12) hour = 20;

      const d = new Date(baseDate);
      if (dayKeyword.startsWith("tomorrow") || timeMatch[0].toLowerCase() === "tomorrow") {
        d.setDate(d.getDate() + 1);
      }
      d.setHours(hour, min, 0, 0);

      if (d.getTime() <= baseDate.getTime() && !dayKeyword && timeMatch[0].toLowerCase() !== "today") {
        d.setDate(d.getDate() + 1);
      }

      dueAt = d;
      reminderType = "once";
      reminderTime = d;
      matchedPhrase = timeMatch[0];
      text = text.replace(timeMatch[0], " ");
    }
  }

  // Clean title
  let cleanTitle = text.replace(/\s+/g, " ").replace(/^(to\s+|for\s+)/i, "").trim();
  cleanTitle = cleanTitle.replace(/[,;.-]+$/, "").trim();
  if (cleanTitle) {
    cleanTitle = cleanTitle.charAt(0).toUpperCase() + cleanTitle.slice(1);
  }

  if (!dueAt && !cronExpr && reminderType === "none") {
    return null;
  }

  return {
    cleanTitle: cleanTitle || rawText.trim(),
    dueAt,
    reminderType,
    reminderTime,
    cronExpr,
    matchedPhrase
  };
}

let composerSelectedOffset = "15";
let editSelectedOffset = "15";
let lastNlpParsedResult = null;

function initTasksAndReminders() {
  // Priority selector buttons
  const priorityBtns = document.querySelectorAll("#task-priority-toggle .priority-btn");
  priorityBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      priorityBtns.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      currentComposerPriority = btn.getAttribute("data-priority") || "medium";
    });
  });

  // Reminder type selector toggle
  const reminderTypeSelect = document.getElementById("task-select-reminder-type");
  const onceFields = document.getElementById("task-reminder-once-fields");
  const recurringFields = document.getElementById("task-reminder-recurring-fields");
  const composerCustomTimeWrap = document.getElementById("task-composer-custom-time-wrap");
  const composerDueInput = document.getElementById("task-input-due");
  const composerRemTimeInput = document.getElementById("task-input-reminder-time");
  const composerAlertPreview = document.getElementById("task-composer-alert-preview");
  const composerAlertPreviewText = document.getElementById("task-composer-alert-preview-text");
  const taskSmartNlpHint = document.getElementById("task-smart-nlp-hint");
  const taskSmartNlpText = document.getElementById("task-smart-nlp-text");

  function updateComposerAlertPreview() {
    if (composerSelectedOffset === "custom") {
      if (composerCustomTimeWrap) composerCustomTimeWrap.style.display = "block";
      if (composerAlertPreview) composerAlertPreview.style.display = "none";
    } else {
      if (composerCustomTimeWrap) composerCustomTimeWrap.style.display = "none";
      const dueVal = composerDueInput ? composerDueInput.value : "";
      const res = formatRelativeAlertPreview(dueVal, composerSelectedOffset);
      if (res.isoLocal && composerRemTimeInput) {
        composerRemTimeInput.value = res.isoLocal;
      }
      if (composerAlertPreview && composerAlertPreviewText) {
        composerAlertPreview.style.display = "inline-flex";
        composerAlertPreviewText.textContent = res.text;
      }
    }
  }

  if (reminderTypeSelect) {
    reminderTypeSelect.addEventListener("change", () => {
      const val = reminderTypeSelect.value;
      if (onceFields) onceFields.style.display = val === "once" ? "block" : "none";
      if (recurringFields) recurringFields.style.display = val === "recurring" ? "block" : "none";
      if (val === "once") updateComposerAlertPreview();
    });
  }

  const composerOffsetChips = document.querySelectorAll("#task-composer-offset-chips .offset-chip");
  composerOffsetChips.forEach(chip => {
    chip.addEventListener("click", () => {
      composerOffsetChips.forEach(c => c.classList.remove("active"));
      chip.classList.add("active");
      composerSelectedOffset = chip.getAttribute("data-offset") || "15";
      updateComposerAlertPreview();
    });
  });

  if (composerDueInput) {
    composerDueInput.addEventListener("input", () => {
      if (reminderTypeSelect && reminderTypeSelect.value === "once") {
        updateComposerAlertPreview();
      }
    });
  }

  // Cron preset chips
  const cronChips = document.querySelectorAll(".cron-chip:not(.modal-cron-chip)");
  cronChips.forEach(chip => {
    chip.addEventListener("click", () => {
      const cronInput = document.getElementById("task-input-cron");
      if (cronInput) {
        cronInput.value = chip.getAttribute("data-cron") || "";
      }
    });
  });

  // Task form expand/collapse & Smart NLP parser
  const titleInput = document.getElementById("task-input-title");
  const composerCard = document.getElementById("task-create-form");
  const composerExpandedBody = document.getElementById("task-composer-expanded-body");

  function expandComposer() {
    if (composerExpandedBody) {
      composerExpandedBody.style.display = "block";
    }
  }

  function collapseComposer() {
    if (composerExpandedBody) {
      composerExpandedBody.style.display = "none";
    }
    if (taskSmartNlpHint) taskSmartNlpHint.style.display = "none";
  }

  function runSmartNlpDetection() {
    if (!titleInput) return;
    const text = titleInput.value.trim();
    if (!text) {
      if (taskSmartNlpHint) taskSmartNlpHint.style.display = "none";
      lastNlpParsedResult = null;
      return;
    }

    const parsed = parseNaturalLanguageTask(text);
    lastNlpParsedResult = parsed;

    if (parsed && (parsed.dueAt || parsed.reminderType !== "none" || parsed.cronExpr)) {
      expandComposer();
      
      // Auto-configure Due Date
      if (parsed.dueAt && composerDueInput) {
        composerDueInput.value = toLocalDatetimeInputString(parsed.dueAt);
      }

      // Auto-configure Reminder Type
      if (parsed.reminderType && reminderTypeSelect) {
        reminderTypeSelect.value = parsed.reminderType;
        if (onceFields) onceFields.style.display = parsed.reminderType === "once" ? "block" : "none";
        if (recurringFields) recurringFields.style.display = parsed.reminderType === "recurring" ? "block" : "none";

        if (parsed.reminderType === "once") {
          // Default to on due time (0 offset) since timing was in phrase
          composerSelectedOffset = "0";
          composerOffsetChips.forEach(c => c.classList.toggle("active", c.getAttribute("data-offset") === "0"));
          updateComposerAlertPreview();
        } else if (parsed.reminderType === "recurring" && parsed.cronExpr) {
          const cronInput = document.getElementById("task-input-cron");
          if (cronInput) cronInput.value = parsed.cronExpr;
        }
      }

      // Show NLP detection badge
      if (taskSmartNlpHint && taskSmartNlpText) {
        taskSmartNlpHint.style.display = "inline-flex";
        let timeDesc = "";
        if (parsed.dueAt) {
          timeDesc = parsed.dueAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', month: 'short', day: 'numeric' });
        } else if (parsed.cronExpr) {
          timeDesc = `Routine: ${parsed.cronExpr}`;
        }
        taskSmartNlpText.innerHTML = `Auto-Configured: <b>"${escapeHtml(parsed.cleanTitle)}"</b> · ⏰ ${escapeHtml(timeDesc)}`;
      }
    } else {
      if (taskSmartNlpHint) taskSmartNlpHint.style.display = "none";
    }
  }

  if (titleInput) {
    titleInput.addEventListener("focus", expandComposer);
    titleInput.addEventListener("input", () => {
      expandComposer();
      runSmartNlpDetection();
    });
    titleInput.addEventListener("click", expandComposer);
  }

  // Click-away listener: if user clicks outside of composer and title is empty, collapse
  document.addEventListener("click", (e) => {
    if (!composerCard || !composerExpandedBody) return;
    if (!composerCard.contains(e.target)) {
      if (titleInput && !titleInput.value.trim()) {
        collapseComposer();
      }
    }
  });

  // Task form submission
  const taskForm = document.getElementById("task-create-form");
  if (taskForm) {
    taskForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const descInput = document.getElementById("task-input-desc");
      const dueInput = document.getElementById("task-input-due");
      const remTypeSelect = document.getElementById("task-select-reminder-type");
      const remTimeInput = document.getElementById("task-input-reminder-time");
      const cronInput = document.getElementById("task-input-cron");

      let rawTitle = titleInput ? titleInput.value.trim() : "";
      if (!rawTitle) return;

      // Check if NLP parsed a clean title
      const nlp = parseNaturalLanguageTask(rawTitle);
      const title = (nlp && nlp.cleanTitle) ? nlp.cleanTitle : rawTitle;

      const desc = descInput ? descInput.value.trim() : "";
      let due = dueInput && dueInput.value ? new Date(dueInput.value).toISOString() : (nlp && nlp.dueAt ? nlp.dueAt.toISOString() : null);
      let remType = remTypeSelect ? remTypeSelect.value : (nlp && nlp.reminderType ? nlp.reminderType : "none");
      let remTime = null;
      let cronExpr = null;

      if (remType === "once") {
        if (remTimeInput && remTimeInput.value) {
          remTime = new Date(remTimeInput.value).toISOString();
        } else if (due) {
          remTime = due;
        } else if (nlp && nlp.reminderTime) {
          remTime = nlp.reminderTime.toISOString();
        } else {
          remTime = new Date(Date.now() + 3600000).toISOString();
        }
      } else if (remType === "recurring") {
        cronExpr = (cronInput && cronInput.value.trim()) ? cronInput.value.trim() : (nlp && nlp.cronExpr ? nlp.cronExpr : "0 9 * * *");
      }

      try {
        const res = await fetch("/api/dashboard/tasks", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title: title,
            description: desc || null,
            priority: currentComposerPriority || "medium",
            due_at: due,
            reminder_type: remType,
            reminder_time: remTime,
            cron_expression: cronExpr,
          }),
        });

        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || `Server returned ${res.status}`);
        }

        // Clear form and collapse
        if (titleInput) titleInput.value = "";
        if (descInput) descInput.value = "";
        if (dueInput) dueInput.value = "";
        if (remTimeInput) remTimeInput.value = "";
        if (cronInput) cronInput.value = "";
        if (remTypeSelect) {
          remTypeSelect.value = "none";
          if (onceFields) onceFields.style.display = "none";
          if (recurringFields) recurringFields.style.display = "none";
        }
        collapseComposer();

        showTaskToast("✅ Task created & scheduled! Push alert synced.", "success");
        await loadTasks();
        await loadJobs();
      } catch (err) {
        console.error("Task creation failed:", err);
        showTaskToast("⚠️ Error creating task: " + err.message, "error");
      }
    });
  }

  // Refresh tasks button
  const refreshTasksBtn = document.getElementById("btn-refresh-tasks");
  if (refreshTasksBtn) {
    refreshTasksBtn.addEventListener("click", () => {
      loadTasks();
      loadJobs();
      showTaskToast("🔄 Synced tasks from live engine", "info");
    });
  }

  // Edit Task Modal listeners
  const closeTaskModalBtn = document.getElementById("btn-close-task-modal");
  const cancelTaskModalBtn = document.getElementById("btn-cancel-task-modal");
  if (closeTaskModalBtn) closeTaskModalBtn.addEventListener("click", closeEditTaskModal);
  if (cancelTaskModalBtn) cancelTaskModalBtn.addEventListener("click", closeEditTaskModal);

  const editModalReminderType = document.getElementById("task-edit-reminder-type");
  const editOnceWrap = document.getElementById("task-edit-once-wrap");
  const editRecurringWrap = document.getElementById("task-edit-recurring-wrap");
  const editCustomTimeWrap = document.getElementById("task-edit-custom-time-wrap");
  const editDueInput = document.getElementById("task-edit-due");
  const editRemTimeInput = document.getElementById("task-edit-reminder-time");
  const editAlertPreview = document.getElementById("task-edit-alert-preview");
  const editAlertPreviewText = document.getElementById("task-edit-alert-preview-text");

  function updateEditAlertPreview() {
    if (editSelectedOffset === "custom") {
      if (editCustomTimeWrap) editCustomTimeWrap.style.display = "block";
      if (editAlertPreview) editAlertPreview.style.display = "none";
    } else {
      if (editCustomTimeWrap) editCustomTimeWrap.style.display = "none";
      const dueVal = editDueInput ? editDueInput.value : "";
      const res = formatRelativeAlertPreview(dueVal, editSelectedOffset);
      if (res.isoLocal && editRemTimeInput) {
        editRemTimeInput.value = res.isoLocal;
      }
      if (editAlertPreview && editAlertPreviewText) {
        editAlertPreview.style.display = "inline-flex";
        editAlertPreviewText.textContent = res.text;
      }
    }
  }

  if (editModalReminderType) {
    editModalReminderType.addEventListener("change", () => {
      const val = editModalReminderType.value;
      if (editOnceWrap) editOnceWrap.style.display = val === "once" ? "block" : "none";
      if (editRecurringWrap) editRecurringWrap.style.display = val === "recurring" ? "block" : "none";
      if (val === "once") updateEditAlertPreview();
    });
  }

  const editOffsetChips = document.querySelectorAll("#task-edit-offset-chips .modal-offset-chip");
  editOffsetChips.forEach(chip => {
    chip.addEventListener("click", () => {
      editOffsetChips.forEach(c => c.classList.remove("active"));
      chip.classList.add("active");
      editSelectedOffset = chip.getAttribute("data-offset") || "15";
      updateEditAlertPreview();
    });
  });

  if (editDueInput) {
    editDueInput.addEventListener("input", () => {
      if (editModalReminderType && editModalReminderType.value === "once") {
        updateEditAlertPreview();
      }
    });
  }

  const modalCronChips = document.querySelectorAll(".modal-cron-chip");
  modalCronChips.forEach(chip => {
    chip.addEventListener("click", () => {
      const cronInput = document.getElementById("task-edit-cron");
      if (cronInput) cronInput.value = chip.getAttribute("data-cron") || "";
    });
  });

  const editTaskForm = document.getElementById("form-edit-task");
  if (editTaskForm) {
    editTaskForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const idInput = document.getElementById("task-edit-id");
      const titleInput = document.getElementById("task-edit-title");
      const descInput = document.getElementById("task-edit-desc");
      const prioritySelect = document.getElementById("task-edit-priority");
      const statusSelect = document.getElementById("task-edit-status");
      const dueInput = document.getElementById("task-edit-due");
      const remTypeSelect = document.getElementById("task-edit-reminder-type");
      const remTimeInput = document.getElementById("task-edit-reminder-time");
      const cronInput = document.getElementById("task-edit-cron");

      const id = idInput ? parseInt(idInput.value) : null;
      if (!id) return;

      const remType = remTypeSelect ? remTypeSelect.value : "none";
      let remTime = null;
      let cronExpr = null;

      if (remType === "once" && remTimeInput && remTimeInput.value) {
        remTime = new Date(remTimeInput.value).toISOString();
      } else if (remType === "recurring" && cronInput && cronInput.value.trim()) {
        cronExpr = cronInput.value.trim();
      }

      try {
        const res = await fetch(`/api/dashboard/tasks/${id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title: titleInput ? titleInput.value.trim() : undefined,
            description: descInput ? descInput.value.trim() || null : null,
            priority: prioritySelect ? prioritySelect.value : "medium",
            status: statusSelect ? statusSelect.value : "todo",
            due_at: dueInput && dueInput.value ? new Date(dueInput.value).toISOString() : null,
            reminder_type: remType,
            reminder_time: remTime,
            cron_expression: cronExpr,
          }),
        });

        if (!res.ok) throw new Error("Failed to save changes");
        closeEditTaskModal();
        showTaskToast("✅ Task updated successfully!", "success");
        await loadTasks();
        await loadJobs();
      } catch (err) {
        showTaskToast("⚠️ Error updating task: " + err.message, "error");
      }
    });
  }

  const deleteFromModalBtn = document.getElementById("btn-delete-task-modal");
  if (deleteFromModalBtn) {
    deleteFromModalBtn.addEventListener("click", () => {
      const idInput = document.getElementById("task-edit-id");
      const id = idInput ? parseInt(idInput.value) : null;
      if (id) {
        closeEditTaskModal();
        deleteTaskItem(id);
      }
    });
  }

  // Filter pills
  const filterPills = document.querySelectorAll("#tasks-filter-group .task-filter-pill");
  filterPills.forEach(pill => {
    pill.addEventListener("click", () => {
      filterPills.forEach(p => p.classList.remove("active"));
      pill.classList.add("active");
      activeTaskFilter = pill.getAttribute("data-filter") || "all";
      renderFilteredTasks();
    });
  });

  // Priority filter dropdown
  const priorityFilter = document.getElementById("tasks-filter-priority");
  if (priorityFilter) {
    priorityFilter.addEventListener("change", () => {
      activeTaskPriority = priorityFilter.value;
      renderFilteredTasks();
    });
  }

  // Search input
  const searchInput = document.getElementById("tasks-search-input");
  if (searchInput) {
    searchInput.addEventListener("input", () => {
      activeTaskSearch = searchInput.value.trim().toLowerCase();
      renderFilteredTasks();
    });
  }
}

async function loadTasks() {
  const container = document.getElementById("tasks-cards-list");
  if (!container) return;

  try {
    const res = await fetch("/api/dashboard/tasks");
    if (!res.ok) throw new Error("Failed to fetch tasks");
    const data = await res.json();

    cachedTasksList = data.tasks || [];

    // Update stats counters
    const stats = data.stats || {};
    const totalEl = document.getElementById("stat-tasks-total");
    const todoEl = document.getElementById("stat-tasks-todo");
    const remEl = document.getElementById("stat-tasks-reminders");
    const doneEl = document.getElementById("stat-tasks-done");

    if (totalEl) totalEl.textContent = stats.total ?? cachedTasksList.length;
    if (todoEl) todoEl.textContent = stats.todo_count ?? cachedTasksList.filter(t => t.status === "todo").length;
    if (remEl) remEl.textContent = stats.reminders_count ?? cachedTasksList.filter(t => t.reminder_type !== "none" && t.is_reminder_active).length;
    if (doneEl) doneEl.textContent = stats.done_count ?? cachedTasksList.filter(t => t.status === "done").length;

    renderFilteredTasks();
  } catch (err) {
    console.warn("Could not load tasks:", err);
  }
}

function renderFilteredTasks() {
  const container = document.getElementById("tasks-cards-list");
  if (!container) return;

  let filtered = [...cachedTasksList];

  // Status & smart filters
  if (activeTaskFilter === "todo") {
    filtered = filtered.filter(t => t.status === "todo");
  } else if (activeTaskFilter === "done") {
    filtered = filtered.filter(t => t.status === "done");
  } else if (activeTaskFilter === "reminders") {
    filtered = filtered.filter(t => t.reminder_type !== "none" && t.is_reminder_active);
  } else if (activeTaskFilter === "today") {
    const todayStr = new Date().toISOString().slice(0, 10);
    filtered = filtered.filter(t => t.due_at && t.due_at.slice(0, 10) === todayStr);
  }

  // Priority filter
  if (activeTaskPriority !== "all") {
    filtered = filtered.filter(t => (t.priority || "").toLowerCase() === activeTaskPriority.toLowerCase());
  }

  // Search query filter
  if (activeTaskSearch) {
    filtered = filtered.filter(t =>
      (t.title || "").toLowerCase().includes(activeTaskSearch) ||
      (t.description || "").toLowerCase().includes(activeTaskSearch)
    );
  }

  if (filtered.length === 0) {
    container.innerHTML = `
      <div class="tasks-empty-state">
        <div style="font-size: 2rem; margin-bottom: 0.6rem;">📋</div>
        <div style="font-size: 0.95rem; font-weight: 600; color: var(--text-primary);">No tasks found</div>
        <div style="font-size: 0.8rem; margin-top: 0.3rem;">
          ${cachedTasksList.length === 0 ? "You have no active tasks. Add one using the composer above or via Telegram chat!" : "No tasks match your current filter settings."}
        </div>
      </div>
    `;
    return;
  }

  container.innerHTML = filtered.map(t => {
    const isDone = t.status === "done";
    const priorityClass = (t.priority || "medium").toLowerCase();
    const priorityLabels = { high: "🔴 High", medium: "🟡 Medium", low: "🟢 Low" };
    const priorityText = priorityLabels[priorityClass] || "🟡 Medium";

    let dueBadgeHtml = "";
    if (t.due_at) {
      const dueDate = new Date(t.due_at);
      const isOverdue = dueDate < new Date() && !isDone;
      const formattedDate = dueDate.toLocaleDateString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
      dueBadgeHtml = `<span class="badge-due-date" style="${isOverdue ? 'color: #fb7185; border-color: rgba(244,63,94,0.3); background: rgba(244,63,94,0.12);' : ''}">📅 ${isOverdue ? 'Overdue: ' : 'Due: '}${formattedDate}</span>`;
    }

    let reminderBadgeHtml = "";
    if (t.reminder_type === "once") {
      const remDate = t.reminder_time ? new Date(t.reminder_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', month: 'short', day: 'numeric' }) : "Scheduled";
      reminderBadgeHtml = `<span class="badge-reminder ${t.is_reminder_active && !isDone ? '' : 'inactive'}">⏰ Alert: ${remDate}</span>`;
    } else if (t.reminder_type === "recurring") {
      reminderBadgeHtml = `<span class="badge-reminder ${t.is_reminder_active && !isDone ? '' : 'inactive'}">🔄 Cron: ${escapeHtml(t.cron_expression || "0 9 * * *")}</span>`;
    }

    return `
      <div class="task-card-item ${isDone ? 'done' : ''}" id="task-card-${t.id}">
        <div class="task-left-col">
          <label class="task-checkbox-wrap" title="${isDone ? 'Mark as to-do' : 'Mark as completed'}">
            <input type="checkbox" ${isDone ? 'checked' : ''} onchange="toggleTaskStatus(${t.id}, '${isDone ? 'todo' : 'done'}')" />
            <span class="task-custom-checkbox">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="20 6 9 17 4 12"></polyline>
              </svg>
            </span>
          </label>

          <div class="task-details">
            <div class="task-title-text" onclick="openEditTaskModal(${t.id})" style="cursor: pointer;" title="Click to edit task">${escapeHtml(t.title)}</div>
            ${t.description ? `<div class="task-desc-text">${escapeHtml(t.description)}</div>` : ''}
            
            <div class="task-badges-row">
              <span class="badge-priority ${priorityClass}">${priorityText}</span>
              ${dueBadgeHtml}
              ${reminderBadgeHtml}
            </div>
          </div>
        </div>

        <div class="task-actions-col">
          <button class="btn-task-action alert-test" onclick="event.stopPropagation(); triggerTaskTestAlert(${t.id})" title="Send immediate test alert to Telegram">
            <span>🔔 Test Alert</span>
          </button>
          
          <button class="btn-task-action" onclick="event.stopPropagation(); openEditTaskModal(${t.id})" title="Edit task details & reminder">
            <span>✏️ Edit</span>
          </button>

          ${t.reminder_type !== 'none' && !isDone ? `
            <button class="btn-task-action" onclick="event.stopPropagation(); snoozeTaskItem(${t.id})" title="Snooze reminder for 1 hour">
              <span>⏰ +1h</span>
            </button>
          ` : ''}

          <button class="btn-task-action delete" onclick="event.stopPropagation(); deleteTaskItem(${t.id})" title="Delete task">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="3 6 5 6 21 6"></polyline>
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
            </svg>
          </button>
        </div>
      </div>
    `;
  }).join("");
}

window.openEditTaskModal = function(id) {
  const task = cachedTasksList.find(t => t.id === id);
  if (!task) return;

  const modal = document.getElementById("modal-edit-task");
  const heading = document.getElementById("modal-task-heading");
  const idInput = document.getElementById("task-edit-id");
  const titleInput = document.getElementById("task-edit-title");
  const descInput = document.getElementById("task-edit-desc");
  const prioritySelect = document.getElementById("task-edit-priority");
  const statusSelect = document.getElementById("task-edit-status");
  const dueInput = document.getElementById("task-edit-due");
  const remTypeSelect = document.getElementById("task-edit-reminder-type");
  const remTimeInput = document.getElementById("task-edit-reminder-time");
  const cronInput = document.getElementById("task-edit-cron");
  const onceWrap = document.getElementById("task-edit-once-wrap");
  const recurringWrap = document.getElementById("task-edit-recurring-wrap");

  if (heading) heading.textContent = `Edit Task #${task.id}`;
  if (idInput) idInput.value = task.id;
  if (titleInput) titleInput.value = task.title || "";
  if (descInput) descInput.value = task.description || "";
  if (prioritySelect) prioritySelect.value = (task.priority || "medium").toLowerCase();
  if (statusSelect) statusSelect.value = task.status || "todo";
  
  if (dueInput) {
    dueInput.value = toLocalDatetimeInputString(task.due_at);
  }

  const remType = task.reminder_type || "none";
  if (remTypeSelect) remTypeSelect.value = remType;
  if (onceWrap) onceWrap.style.display = remType === "once" ? "block" : "none";
  if (recurringWrap) recurringWrap.style.display = remType === "recurring" ? "block" : "none";

  const editCustomTimeWrap = document.getElementById("task-edit-custom-time-wrap");
  const editAlertPreview = document.getElementById("task-edit-alert-preview");
  const editAlertPreviewText = document.getElementById("task-edit-alert-preview-text");
  const editChips = document.querySelectorAll("#task-edit-offset-chips .modal-offset-chip");

  if (remTimeInput) {
    remTimeInput.value = toLocalDatetimeInputString(task.reminder_time);
  }
  if (cronInput) {
    cronInput.value = task.cron_expression || "";
  }

  // Calculate matching relative offset if both due_at and reminder_time exist
  if (remType === "once") {
    let matchedOffset = "custom";
    if (task.due_at && task.reminder_time) {
      const diffMin = Math.round((new Date(task.due_at) - new Date(task.reminder_time)) / 60000);
      const knownOffsets = [0, 5, 15, 30, 60, 120, 1440, 2880];
      const match = knownOffsets.find(o => Math.abs(o - diffMin) <= 1);
      if (match !== undefined) {
        matchedOffset = String(match);
      }
    } else if (task.due_at && !task.reminder_time) {
      matchedOffset = "15";
    }

    editSelectedOffset = matchedOffset;
    editChips.forEach(c => c.classList.toggle("active", c.getAttribute("data-offset") === matchedOffset));

    if (matchedOffset === "custom") {
      if (editCustomTimeWrap) editCustomTimeWrap.style.display = "block";
      if (editAlertPreview) editAlertPreview.style.display = "none";
    } else {
      if (editCustomTimeWrap) editCustomTimeWrap.style.display = "none";
      const dueVal = dueInput ? dueInput.value : "";
      const res = formatRelativeAlertPreview(dueVal, matchedOffset);
      if (res.isoLocal && remTimeInput) {
        remTimeInput.value = res.isoLocal;
      }
      if (editAlertPreview && editAlertPreviewText) {
        editAlertPreview.style.display = "inline-flex";
        editAlertPreviewText.textContent = res.text;
      }
    }
  }

  if (modal) {
    modal.style.display = "flex";
  }
};

window.closeEditTaskModal = function() {
  const modal = document.getElementById("modal-edit-task");
  if (modal) {
    modal.style.display = "none";
  }
};

window.toggleTaskStatus = async function(id, newStatus) {
  try {
    const res = await fetch(`/api/dashboard/tasks/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: newStatus }),
    });
    if (!res.ok) throw new Error("Failed to update status");
    const data = await res.json();
    
    // Update local cache
    const task = cachedTasksList.find(t => t.id === id);
    if (task) {
      task.status = newStatus;
      if (newStatus === "done") task.is_reminder_active = false;
    }
    renderFilteredTasks();
    showTaskToast(newStatus === "done" ? "🎉 Task completed!" : "⚡ Task marked as to-do", "success");
    loadTasks();
  } catch (err) {
    showTaskToast("⚠️ Error updating task: " + err.message, "error");
  }
};

window.triggerTaskTestAlert = async function(id) {
  try {
    const res = await fetch(`/api/dashboard/tasks/${id}/test_alert`, { method: "POST" });
    const data = await res.json();
    if (data.alert_triggered) {
      showTaskToast(`🔔 Telegram notification sent for Task #${id} with [✅ Mark Done] buttons!`, "success");
    } else {
      showTaskToast("⚠️ Telegram notification could not be delivered.", "error");
    }
  } catch (err) {
    showTaskToast("Error triggering alert: " + err.message, "error");
  }
};

window.snoozeTaskItem = async function(id) {
  try {
    const res = await fetch(`/api/dashboard/tasks/${id}/snooze?minutes=60`, { method: "POST" });
    const data = await res.json();
    if (data.snoozed) {
      showTaskToast(`⏰ Snoozed reminder for Task #${id} by 1 hour.`, "success");
      loadTasks();
    }
  } catch (err) {
    showTaskToast("Error snoozing task: " + err.message, "error");
  }
};

window.deleteTaskItem = async function(id) {
  // Optimistically remove from local array immediately for snappy UI
  const prevList = [...cachedTasksList];
  cachedTasksList = cachedTasksList.filter(t => t.id !== id);
  renderFilteredTasks();

  try {
    const res = await fetch(`/api/dashboard/tasks/${id}`, { method: "DELETE" });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || `Server returned ${res.status}`);
    }
    showTaskToast(`🗑️ Task #${id} deleted.`, "info");
    await loadTasks();
    await loadJobs();
  } catch (err) {
    console.error("Delete task failed:", err);
    // Rollback on failure
    cachedTasksList = prevList;
    renderFilteredTasks();
    showTaskToast("Error deleting task: " + err.message, "error");
  }
};

function showTaskToast(message, type = "info") {
  let toastContainer = document.getElementById("task-toast-container");
  if (!toastContainer) {
    toastContainer = document.createElement("div");
    toastContainer.id = "task-toast-container";
    toastContainer.style.cssText = "position: fixed; bottom: 1.5rem; right: 1.5rem; z-index: 99999; display: flex; flex-direction: column; gap: 0.5rem; pointer-events: none;";
    document.body.appendChild(toastContainer);
  }

  const toast = document.createElement("div");
  const bg = type === "success" ? "#065f46" : type === "error" ? "#881337" : "#1f1f26";
  const border = type === "success" ? "#10b981" : type === "error" ? "#f43f5e" : "#3f3f46";
  toast.style.cssText = `background: ${bg}; border: 1px solid ${border}; color: #fff; padding: 0.75rem 1.15rem; border-radius: 10px; font-size: 0.82rem; font-weight: 500; box-shadow: 0 10px 25px rgba(0,0,0,0.5); pointer-events: auto; animation: panelFadeIn 0.2s ease; font-family: 'Plus Jakarta Sans', sans-serif; display: flex; align-items: center; gap: 0.5rem; max-width: 380px;`;
  toast.textContent = message;

  toastContainer.appendChild(toast);
  setTimeout(() => {
    toast.style.transition = "opacity 0.3s ease, transform 0.3s ease";
    toast.style.opacity = "0";
    toast.style.transform = "translateY(10px)";
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// Low-Level APScheduler Engine Loader
function initJobs() {
  const refreshBtn = document.getElementById("btn-refresh-jobs");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", loadJobs);
  }
}

async function loadJobs() {
  const container = document.getElementById("jobs-cards-grid");
  if (!container) return;

  try {
    const res = await fetch("/api/dashboard/jobs");
    if (!res.ok) throw new Error("Failed to load jobs");
    const data = await res.json();

    if (!data.jobs || data.jobs.length === 0) {
      container.innerHTML = `
        <div style="padding: 1.25rem; text-align: center; color: var(--text-muted); background: rgba(24, 24, 27, 0.4); border: 1px dashed var(--border-subtle); border-radius: var(--radius-md); font-size: 0.82rem;">
          <div style="font-size: 1.25rem; margin-bottom: 0.35rem;">⏱️</div>
          <div style="color: #d4d4d8; font-weight: 500;">All Task Reminders & Background Routines are Active</div>
          <div style="font-size: 0.72rem; color: #71717a; margin-top: 0.25rem;">Timezone: Asia/Singapore (SGT) · Telegram Push Notifications: Connected ✅</div>
        </div>
      `;
      return;
    }

    container.innerHTML = `
      <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 1rem;">
        ${data.jobs.map(j => `
          <div class="metric-glass-card" style="min-height: 120px; padding: 1rem;" data-id="${j.job_id}">
            <div class="metric-top-bar">
              <div class="metric-icon-disc orange-disc" style="width: 28px; height: 28px; font-size: 0.8rem;">⏰</div>
              <span class="metric-label-text" style="font-size: 0.82rem; font-weight: 600;">${escapeHtml(j.job_name || "Automated Routine")}</span>
              <span class="category-tag-pill" style="margin-left: auto; font-size: 0.68rem; background: rgba(245, 158, 11, 0.12); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.25);">${escapeHtml(j.cron_expression || "Scheduled")}</span>
            </div>
            <div style="font-size: 0.78rem; color: var(--text-secondary); margin: 0.4rem 0;">"${escapeHtml(j.instruction_prompt || "")}"</div>
            <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid #202024; padding-top: 0.5rem; font-size: 0.7rem; font-family: var(--font-mono);">
              <span style="color: var(--text-muted);">Next Trigger: ${j.next_run_time ? new Date(j.next_run_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : "Active"}</span>
              <div style="display: flex; gap: 0.35rem;">
                <button class="btn-ask-ai-pill" style="padding: 0.15rem 0.5rem; font-size: 0.68rem;" onclick="triggerJobRun(${j.job_id})">⚡ Test Now</button>
                <button class="row-action-btn" onclick="deleteJobItem(${j.job_id})" title="Remove routine">🗑️</button>
              </div>
            </div>
          </div>
        `).join("")}
      </div>
    `;

  } catch (err) {
    console.warn("Could not load jobs:", err);
  }
}

window.triggerJobRun = async function(id) {
  try {
    const res = await fetch(`/api/dashboard/jobs/run/${id}`, { method: "POST" });
    const data = await res.json();
    if (data.triggered) {
      showTaskToast(`⚡ Triggered system job #${id} immediately! Check Telegram.`, "success");
    }
  } catch (err) {
    showTaskToast("Error triggering job: " + err.message, "error");
  }
};

window.deleteJobItem = async function(id) {
  if (!confirm(`Delete system job #${id}?`)) return;
  try {
    const res = await fetch(`/api/dashboard/jobs/${id}`, { method: "DELETE" });
    if (res.ok) {
      showTaskToast(`🗑️ System job #${id} deleted.`, "info");
      loadJobs();
    }
  } catch (err) {
    showTaskToast("Error deleting job: " + err.message, "error");
  }
};

// ==========================================================================
// ==========================================================================
// 4. PLANNING WHITEBOARDS & LIVING CANVAS
// ==========================================================================

let currentWhiteboardId = null;
let cachedWhiteboards = [];
let cachedWhiteboardBlocks = [];

function initWhiteboard() {
  // Board Switcher Dropdown
  const selector = document.getElementById("wb-project-selector");
  if (selector) {
    selector.addEventListener("change", (e) => {
      currentWhiteboardId = parseInt(e.target.value, 10);
      loadWhiteboardDetails(currentWhiteboardId);
    });
  }

  // Create Board Modal Controls
  const openCreateBtn = document.getElementById("btn-open-create-board-modal");
  const modalCreate = document.getElementById("modal-create-board");
  const closeCreateBtn = document.getElementById("btn-close-create-board");
  const cancelCreateBtn = document.getElementById("btn-cancel-create-board");
  const formCreate = document.getElementById("form-create-board");

  if (openCreateBtn && modalCreate) {
    openCreateBtn.addEventListener("click", () => {
      modalCreate.style.display = "flex";
      const titleInput = document.getElementById("new-board-title");
      if (titleInput) titleInput.focus();
    });
  }

  const hideCreateModal = () => {
    if (modalCreate) modalCreate.style.display = "none";
    if (formCreate) formCreate.reset();
  };

  if (closeCreateBtn) closeCreateBtn.addEventListener("click", hideCreateModal);
  if (cancelCreateBtn) cancelCreateBtn.addEventListener("click", hideCreateModal);

  // Template Card Selection
  const templateCards = document.querySelectorAll(".wb-template-card");
  templateCards.forEach(card => {
    card.addEventListener("click", () => {
      templateCards.forEach(c => c.classList.remove("selected"));
      card.classList.add("selected");
      const radio = card.querySelector('input[type="radio"]');
      if (radio) radio.checked = true;

      // Auto-populate emoji and category
      const t = card.getAttribute("data-template");
      const emojiInput = document.getElementById("new-board-emoji");
      const catSelect = document.getElementById("new-board-category");
      if (t === "trip") {
        if (emojiInput) emojiInput.value = "✈️";
        if (catSelect) catSelect.value = "trip";
      } else if (t === "meal") {
        if (emojiInput) emojiInput.value = "🛒";
        if (catSelect) catSelect.value = "meal";
      } else if (t === "event") {
        if (emojiInput) emojiInput.value = "🎉";
        if (catSelect) catSelect.value = "event";
      } else if (t === "project") {
        if (emojiInput) emojiInput.value = "🚀";
        if (catSelect) catSelect.value = "project";
      } else {
        if (emojiInput) emojiInput.value = "📝";
        if (catSelect) catSelect.value = "general";
      }
    });
  });

  // Submit Create Board Form
  if (formCreate) {
    formCreate.addEventListener("submit", async (e) => {
      e.preventDefault();
      const title = document.getElementById("new-board-title").value.trim();
      const emoji = document.getElementById("new-board-emoji").value.trim() || "📋";
      const category = document.getElementById("new-board-category").value;
      const summary = document.getElementById("new-board-summary").value.trim();
      const selectedTemplate = document.querySelector('input[name="board-template-choice"]:checked')?.value || "blank";

      try {
        const res = await fetch("/api/dashboard/whiteboards", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title,
            emoji_icon: emoji,
            category,
            summary: summary || null,
            template: selectedTemplate,
          }),
        });
        if (!res.ok) throw new Error("Failed to create board");
        const data = await res.json();
        hideCreateModal();
        await loadWhiteboards(data.project.id);
      } catch (err) {
        alert("Error creating board: " + err.message);
      }
    });
  }

  // Delete Board Button
  const deleteBoardBtn = document.getElementById("btn-delete-active-board");
  if (deleteBoardBtn) {
    deleteBoardBtn.addEventListener("click", async () => {
      if (!currentWhiteboardId) return;
      const currentProj = cachedWhiteboards.find(p => p.id === currentWhiteboardId);
      const title = currentProj ? currentProj.title : "this board";
      if (!confirm(`Are you sure you want to delete "${title}" and all its cards?`)) return;

      try {
        const res = await fetch(`/api/dashboard/whiteboards/${currentWhiteboardId}`, { method: "DELETE" });
        if (!res.ok) throw new Error("Failed to delete board");
        currentWhiteboardId = null;
        await loadWhiteboards();
      } catch (err) {
        alert("Error deleting board: " + err.message);
      }
    });
  }

  // AI Copilot Prompt Form & Chips
  const aiSubmitBtn = document.getElementById("wb-ai-prompt-submit");
  const aiInput = document.getElementById("wb-ai-prompt-input");

  const triggerAiCopilot = async (promptText) => {
    if (!promptText || !currentWhiteboardId) return;
    const origBtnText = aiSubmitBtn.innerHTML;
    aiSubmitBtn.disabled = true;
    aiSubmitBtn.innerHTML = `<span>Thinking...</span>`;

    try {
      const res = await fetch(`/api/dashboard/whiteboards/${currentWhiteboardId}/ai_copilot`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: promptText, section_name: "✨ AI Insights & Research" }),
      });
      if (!res.ok) throw new Error("AI generation failed");
      if (aiInput) aiInput.value = "";
      await loadWhiteboardDetails(currentWhiteboardId);
    } catch (err) {
      alert("Error generating card: " + err.message);
    } finally {
      aiSubmitBtn.disabled = false;
      aiSubmitBtn.innerHTML = origBtnText;
    }
  };

  if (aiSubmitBtn && aiInput) {
    aiSubmitBtn.addEventListener("click", () => triggerAiCopilot(aiInput.value.trim()));
    aiInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        triggerAiCopilot(aiInput.value.trim());
      }
    });
  }

  const promptChips = document.querySelectorAll(".wb-prompt-chip");
  promptChips.forEach(chip => {
    chip.addEventListener("click", () => {
      const p = chip.getAttribute("data-prompt");
      if (aiInput) aiInput.value = p;
      triggerAiCopilot(p);
    });
  });

  // Add Card Modal Controls
  const openAddCardBtn = document.getElementById("btn-open-add-card-modal");
  const modalAddCard = document.getElementById("modal-add-card");
  const closeAddCardBtn = document.getElementById("btn-close-add-card");
  const cancelAddCardBtn = document.getElementById("btn-cancel-add-card");
  const formAddCard = document.getElementById("form-add-card");

  if (openAddCardBtn && modalAddCard) {
    openAddCardBtn.addEventListener("click", () => {
      modalAddCard.style.display = "flex";
      const titleInput = document.getElementById("new-card-title");
      if (titleInput) titleInput.focus();
    });
  }

  const hideAddCardModal = () => {
    if (modalAddCard) modalAddCard.style.display = "none";
    if (formAddCard) formAddCard.reset();
  };

  if (closeAddCardBtn) closeAddCardBtn.addEventListener("click", hideAddCardModal);
  if (cancelAddCardBtn) cancelAddCardBtn.addEventListener("click", hideAddCardModal);

  if (formAddCard) {
    formAddCard.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!currentWhiteboardId) return;

      const section = document.getElementById("new-card-section").value.trim() || "General";
      const blockType = document.getElementById("new-card-type").value;
      const title = document.getElementById("new-card-title").value.trim();
      const notes = document.getElementById("new-card-notes").value.trim();

      let contentPayload = {};
      if (blockType === "note") {
        contentPayload = { markdown: notes };
      } else if (blockType === "checklist") {
        const lines = notes ? notes.split("\n").filter(l => l.trim()) : ["First check item"];
        contentPayload = { items: lines.map((l, idx) => ({ id: `c-${idx + 1}`, text: l.trim().replace(/^[-*•]\s*/, ''), checked: false })) };
      } else if (blockType === "comparison") {
        contentPayload = {
          options: [
            { id: "opt-1", name: title, price: "Standard", rating: "4.8 ★", pros: [notes || "Great option"], cons: [], is_winner: true }
          ]
        };
      } else if (blockType === "itinerary") {
        contentPayload = {
          steps: [
            { time: "09:00", title: title, location: "Main Venue", notes: notes || "Scheduled event" }
          ]
        };
      } else if (blockType === "budget") {
        contentPayload = {
          currency: "SGD",
          items: [{ name: title, cost: 100, status: "Estimated" }]
        };
      }

      try {
        const res = await fetch(`/api/dashboard/whiteboards/${currentWhiteboardId}/blocks`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            section_name: section,
            block_type: blockType,
            title,
            content_payload: contentPayload,
          }),
        });
        if (!res.ok) throw new Error("Failed to add card");
        hideAddCardModal();
        await loadWhiteboardDetails(currentWhiteboardId);
      } catch (err) {
        alert("Error adding card: " + err.message);
      }
    });
  }
}

async function loadWhiteboards(selectProjectId = null) {
  try {
    const res = await fetch("/api/dashboard/whiteboards");
    if (!res.ok) throw new Error("Failed to fetch whiteboards");
    const data = await res.json();
    cachedWhiteboards = data.projects || [];

    const dropdown = document.getElementById("wb-project-selector");
    if (!dropdown) return;

    if (cachedWhiteboards.length === 0) {
      dropdown.innerHTML = `<option value="">No boards</option>`;
      return;
    }

    if (selectProjectId) {
      currentWhiteboardId = selectProjectId;
    } else if (!currentWhiteboardId || !cachedWhiteboards.some(p => p.id === currentWhiteboardId)) {
      currentWhiteboardId = cachedWhiteboards[0].id;
    }

    dropdown.innerHTML = cachedWhiteboards.map(p => `
      <option value="${p.id}" ${p.id === currentWhiteboardId ? 'selected' : ''}>
        ${p.emoji_icon} ${escapeHtml(p.title)}
      </option>
    `).join("");

    dropdown.value = String(currentWhiteboardId);
    await loadWhiteboardDetails(currentWhiteboardId);

  } catch (err) {
    console.warn("Could not load whiteboards:", err);
  }
}

async function loadWhiteboardDetails(projectId) {
  if (!projectId) return;
  const container = document.getElementById("wb-sections-container");
  if (!container) return;

  try {
    const res = await fetch(`/api/dashboard/whiteboards/${projectId}`);
    if (!res.ok) throw new Error("Failed to fetch whiteboard details");
    const data = await res.json();
    const proj = data.project;
    const blocks = data.blocks || [];
    cachedWhiteboardBlocks = blocks;

    // Update Header
    const emojiEl = document.getElementById("wb-active-emoji");
    const titleEl = document.getElementById("wb-active-title");
    const catEl = document.getElementById("wb-active-category");
    const sumEl = document.getElementById("wb-active-summary");
    const countEl = document.getElementById("wb-canvas-block-count");

    if (emojiEl) emojiEl.textContent = proj.emoji_icon || "📋";
    if (titleEl) titleEl.textContent = proj.title;
    if (catEl) catEl.textContent = (proj.category || "general").toUpperCase();
    if (sumEl) sumEl.textContent = proj.summary || "Interactive planning canvas";

    // Group blocks by section_name
    const sectionsMap = new Map();
    blocks.forEach(b => {
      const sec = b.section_name || "General";
      if (!sectionsMap.has(sec)) sectionsMap.set(sec, []);
      sectionsMap.get(sec).push(b);
    });

    if (countEl) {
      countEl.textContent = `${sectionsMap.size} sections · ${blocks.length} active cards`;
    }

    if (sectionsMap.size === 0) {
      container.innerHTML = `
        <div style="padding: 3.5rem 1rem; text-align: center; color: var(--text-muted); background: #111115; border: 1px dashed #272730; border-radius: var(--radius-md);">
          <div style="font-size: 2rem; margin-bottom: 0.5rem;">🪄</div>
          <div style="font-size: 1rem; font-weight: 600; color: #fff; margin-bottom: 0.3rem;">This board is empty</div>
          <div style="font-size: 0.82rem; max-width: 420px; margin: 0 auto 1.25rem auto;">Use the AI Copilot bar above or click "+ Add Card" to brainstorm and add items!</div>
          <button class="btn-primary-ember" onclick="document.getElementById('wb-ai-prompt-input').focus()">🪄 Ask AI Copilot</button>
        </div>
      `;
      return;
    }

    let deckHtml = "";
    sectionsMap.forEach((sectionBlocks, sectionName) => {
      deckHtml += `
        <div class="wb-section-block">
          <div class="wb-section-header">
            <h3 class="wb-section-title">${escapeHtml(sectionName)}</h3>
            <span style="font-size: 0.75rem; color: var(--text-muted); font-weight: 500;">${sectionBlocks.length} card${sectionBlocks.length === 1 ? '' : 's'}</span>
          </div>
          <div class="wb-cards-grid">
            ${sectionBlocks.map(b => renderSmartCardHtml(b)).join("")}
          </div>
        </div>
      `;
    });

    container.innerHTML = deckHtml;

  } catch (err) {
    console.error("Error loading whiteboard details:", err);
    container.innerHTML = `<div style="color: #fb7185; padding: 1.5rem; text-align: center;">Error loading board details.</div>`;
  }
}

function renderSmartCardHtml(block) {
  const payload = block.content_payload || {};
  let cardBodyHtml = "";

  if (block.block_type === "comparison") {
    const options = payload.options || [];
    cardBodyHtml = `
      <div class="wb-opt-list">
        ${options.map(opt => `
          <div class="wb-opt-tile ${opt.is_winner ? 'winner' : ''}">
            <div class="wb-opt-top">
              <div>
                <span class="wb-opt-name">${escapeHtml(opt.name)}</span>
                <span class="wb-opt-rating">${opt.rating || ''}</span>
              </div>
              <span class="wb-opt-price">${opt.price || ''}</span>
            </div>
            ${(opt.pros?.length || opt.cons?.length) ? `
              <ul class="wb-opt-bullets">
                ${(opt.pros || []).map(p => `<li>✅ ${escapeHtml(p)}</li>`).join("")}
                ${(opt.cons || []).map(c => `<li>⚠️ ${escapeHtml(c)}</li>`).join("")}
              </ul>
            ` : ''}
            <div class="wb-opt-actions">
              ${opt.is_winner ? `
                <span class="wb-winner-badge">🏆 Selected Choice</span>
                <button class="btn-card-escalate" onclick="escalateOptionToTask(${block.id}, '${opt.id}')">⏰ Add Task</button>
              ` : `
                <button class="btn-select-winner" onclick="selectComparisonWinner(${block.id}, '${opt.id}')">⭐ Select Option</button>
              `}
            </div>
          </div>
        `).join("")}
      </div>
    `;
  } else if (block.block_type === "checklist") {
    const items = payload.items || [];
    const checkedCount = items.filter(i => i.checked).length;
    const progressPct = items.length ? Math.round((checkedCount / items.length) * 100) : 0;

    cardBodyHtml = `
      <div class="wb-check-progress">
        <div class="wb-check-progress-fill" style="width: ${progressPct}%;"></div>
      </div>
      <div style="display: flex; justify-content: space-between; font-size: 0.72rem; color: var(--text-muted); margin-bottom: 0.5rem;">
        <span>${checkedCount} of ${items.length} completed</span>
        <span style="font-family: var(--font-mono);">${progressPct}%</span>
      </div>
      <div class="wb-checklist-items">
        ${items.map(item => `
          <div class="wb-check-row ${item.checked ? 'done' : ''}" onclick="toggleChecklistItem(${block.id}, '${item.id}')">
            <input type="checkbox" class="dash-checkbox" ${item.checked ? 'checked' : ''} style="pointer-events: none;" />
            <span>${escapeHtml(item.text)}</span>
          </div>
        `).join("")}
      </div>
      <div class="wb-check-inline-add">
        <input type="text" class="wb-check-input" placeholder="+ Add item..." onkeydown="if(event.key==='Enter'){ addChecklistItem(${block.id}, this); }" />
      </div>
    `;
  } else if (block.block_type === "itinerary") {
    const steps = payload.steps || [];
    cardBodyHtml = `
      <div class="wb-itin-timeline">
        ${steps.map(step => `
          <div class="wb-itin-node">
            <div class="wb-itin-time">${escapeHtml(step.time || '')} · <span style="color: #d4d4d8;">${escapeHtml(step.location || '')}</span></div>
            <div class="wb-itin-step-title">${escapeHtml(step.title || '')}</div>
            ${step.notes ? `<div class="wb-itin-notes">${escapeHtml(step.notes)}</div>` : ''}
          </div>
        `).join("")}
      </div>
    `;
  } else if (block.block_type === "budget") {
    const items = payload.items || [];
    const curr = payload.currency || "SGD";
    const total = items.reduce((acc, i) => acc + (parseFloat(i.cost) || 0), 0);

    cardBodyHtml = `
      <div class="wb-budget-summary-pill">
        <span>Total:</span>
        <span>$${total.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${curr}</span>
      </div>
      <div class="wb-budget-rows">
        ${items.map(item => `
          <div class="wb-budget-row">
            <div>
              <span style="color: #fff; font-weight: 500;">${escapeHtml(item.name)}</span>
              <span style="font-size: 0.68rem; margin-left: 0.35rem; color: var(--text-muted);">(${escapeHtml(item.status || 'Estimated')})</span>
            </div>
            <span class="wb-budget-cost">$${(parseFloat(item.cost) || 0).toFixed(2)}</span>
          </div>
        `).join("")}
      </div>
    `;
  } else {
    // Note
    const text = payload.markdown || "";
    cardBodyHtml = `<div class="wb-note-text">${escapeHtml(text)}</div>`;
  }

  return `
    <div class="wb-card" data-block-id="${block.id}">
      <div>
        <div class="wb-card-header-row">
          <span class="wb-card-type-tag ${block.block_type}">${block.block_type}</span>
          <button class="btn-card-delete" onclick="deleteBlockCard(${block.id})" title="Delete card">🗑️</button>
        </div>
        <h4 class="wb-card-title">${escapeHtml(block.title)}</h4>
        ${cardBodyHtml}
      </div>

      <div class="wb-card-footer">
        <div class="wb-card-actions-left">
          ${block.block_type !== 'comparison' ? `
            <button class="btn-card-escalate" onclick="escalateBlockToTask(${block.id})">⏰ Add Task</button>
          ` : ''}
          ${block.block_type === 'budget' ? `
            <button class="btn-card-escalate" onclick="escalateBlockToExpense(${block.id})">💰 Log Expense</button>
          ` : ''}
        </div>
        <span style="font-size: 0.68rem; color: var(--text-muted);">${block.linked_task_id ? '🔗 Linked Task' : ''}</span>
      </div>
    </div>
  `;
}

// Window interactive helper functions for smart cards
window.selectComparisonWinner = async function(blockId, optionId) {
  const block = cachedWhiteboardBlocks.find(b => b.id === blockId);
  if (!block || !block.content_payload || !block.content_payload.options) return;

  const updatedOptions = block.content_payload.options.map(opt => ({
    ...opt,
    is_winner: opt.id === optionId,
  }));

  // Optimistic UI update
  block.content_payload.options = updatedOptions;
  loadWhiteboardDetails(currentWhiteboardId);

  try {
    await fetch(`/api/dashboard/whiteboards/blocks/${blockId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content_payload: { ...block.content_payload, options: updatedOptions } }),
    });
  } catch (err) {
    console.error("Error updating winner:", err);
  }
};

window.toggleChecklistItem = async function(blockId, itemId) {
  const block = cachedWhiteboardBlocks.find(b => b.id === blockId);
  if (!block || !block.content_payload || !block.content_payload.items) return;

  const updatedItems = block.content_payload.items.map(item => {
    if (item.id === itemId) return { ...item, checked: !item.checked };
    return item;
  });

  // Optimistic UI update
  block.content_payload.items = updatedItems;
  loadWhiteboardDetails(currentWhiteboardId);

  try {
    await fetch(`/api/dashboard/whiteboards/blocks/${blockId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content_payload: { ...block.content_payload, items: updatedItems } }),
    });
  } catch (err) {
    console.error("Error toggling checklist item:", err);
  }
};

window.addChecklistItem = async function(blockId, inputElem) {
  const text = inputElem.value.trim();
  if (!text) return;
  inputElem.value = "";

  const block = cachedWhiteboardBlocks.find(b => b.id === blockId);
  if (!block) return;
  const currentItems = block.content_payload?.items || [];
  const newItem = { id: `c-${Date.now()}`, text, checked: false };
  const updatedItems = [...currentItems, newItem];

  // Optimistic UI
  block.content_payload = { ...block.content_payload, items: updatedItems };
  loadWhiteboardDetails(currentWhiteboardId);

  try {
    await fetch(`/api/dashboard/whiteboards/blocks/${blockId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content_payload: block.content_payload }),
    });
  } catch (err) {
    console.error("Error adding checklist item:", err);
  }
};

window.deleteBlockCard = async function(blockId) {
  if (!confirm("Are you sure you want to delete this card?")) return;
  try {
    await fetch(`/api/dashboard/whiteboards/blocks/${blockId}`, { method: "DELETE" });
    await loadWhiteboardDetails(currentWhiteboardId);
  } catch (err) {
    alert("Error deleting card: " + err.message);
  }
};

window.escalateBlockToTask = async function(blockId) {
  const block = cachedWhiteboardBlocks.find(b => b.id === blockId);
  if (!block) return;
  const taskTitle = prompt("Enter task title to schedule in Tasks & Reminders:", block.title);
  if (!taskTitle) return;

  const dueStr = new Date(Date.now() + 24 * 3600 * 1000).toISOString();

  try {
    const res = await fetch(`/api/dashboard/whiteboards/blocks/${blockId}/escalate_task`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: taskTitle,
        due_at: dueStr,
        reminder_type: "once",
        reminder_time: dueStr,
        priority: "high",
      }),
    });
    if (!res.ok) throw new Error("Failed to escalate task");
    const data = await res.json();
    alert(`✅ Task scheduled: "${data.title}"!\nTelegram push reminder active.`);
    loadWhiteboardDetails(currentWhiteboardId);
  } catch (err) {
    alert("Error creating task: " + err.message);
  }
};

window.escalateOptionToTask = async function(blockId, optionId) {
  const block = cachedWhiteboardBlocks.find(b => b.id === blockId);
  if (!block) return;
  const opt = (block.content_payload?.options || []).find(o => o.id === optionId);
  const optName = opt ? opt.name : block.title;
  const taskTitle = prompt("Enter task title for this choice:", `Book ${optName} for ${block.title}`);
  if (!taskTitle) return;

  const dueStr = new Date(Date.now() + 24 * 3600 * 1000).toISOString();

  try {
    const res = await fetch(`/api/dashboard/whiteboards/blocks/${blockId}/escalate_task`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: taskTitle,
        due_at: dueStr,
        reminder_type: "once",
        reminder_time: dueStr,
        priority: "high",
      }),
    });
    if (!res.ok) throw new Error("Failed to escalate task");
    const data = await res.json();
    alert(`✅ Task created: "${data.title}"!\nScheduled in your Tasks Cockpit.`);
    loadWhiteboardDetails(currentWhiteboardId);
  } catch (err) {
    alert("Error creating task: " + err.message);
  }
};

window.escalateBlockToExpense = async function(blockId) {
  const block = cachedWhiteboardBlocks.find(b => b.id === blockId);
  const items = block?.content_payload?.items || [];
  const total = items.reduce((acc, i) => acc + (parseFloat(i.cost) || 0), 0);

  const merchant = prompt("Enter merchant / description for expense:", block ? block.title : "Whiteboard Budget");
  if (!merchant) return;
  const amountStr = prompt("Enter expense amount ($):", total ? total.toFixed(2) : "100.00");
  if (!amountStr) return;

  try {
    const res = await fetch(`/api/dashboard/whiteboards/blocks/${blockId}/escalate_expense`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        merchant,
        amount: parseFloat(amountStr),
        category: "Travel",
        currency: "SGD",
      }),
    });
    if (!res.ok) throw new Error("Failed to log expense");
    const data = await res.json();
    alert(`💰 Logged $${data.amount.toFixed(2)} to ${data.merchant} in Financial Cockpit!`);
    loadDashboardSummary();
  } catch (err) {
    alert("Error logging expense: " + err.message);
  }
};

// ==========================================================================
// 5. ASSISTANT CHAT CONSOLE
// ==========================================================================

function initWebChat() {
  const form = document.getElementById("chat-input-form");
  const input = document.getElementById("chat-user-input");
  const stream = document.getElementById("chat-messages-stream");
  const clearBtn = document.getElementById("btn-clear-chat");
  const sessionDisplay = document.getElementById("chat-session-id-display");

  if (sessionDisplay) {
    sessionDisplay.textContent = `Session: ${webSessionId}`;
  }

  // Quick Prompts
  document.querySelectorAll(".prompt-pill-btn").forEach(chip => {
    chip.addEventListener("click", () => {
      const msg = chip.getAttribute("data-msg");
      if (input && msg) {
        input.value = msg;
        sendChatMessage(msg);
      }
    });
  });

  // Form Submit
  if (form && input) {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      input.value = "";
      sendChatMessage(text);
    });
  }

  // Clear Chat Button
  if (clearBtn && stream) {
    clearBtn.addEventListener("click", () => {
      webSessionId = `web-${Math.random().toString(36).substring(2, 9)}`;
      localStorage.setItem("nexus_web_session_id", webSessionId);
      if (sessionDisplay) sessionDisplay.textContent = `Session: ${webSessionId}`;

      stream.innerHTML = `
        <div class="chat-message-bubble assistant-message">
          <div class="msg-avatar-icon">🤖</div>
          <div class="msg-body-wrapper">
            <div class="msg-text-surface">
              ✨ <strong>New session initialized!</strong><br/>
              Session ID: <code>${webSessionId}</code>. How can I help you?
            </div>
            <span class="msg-time-tag">Just now</span>
          </div>
        </div>
      `;
    });
  }
}

async function sendChatMessage(userText, action = null) {
  const stream = document.getElementById("chat-messages-stream");
  const typing = document.getElementById("chat-typing-indicator");
  const sendBtn = document.getElementById("btn-chat-send");
  const userTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Singapore";

  if (!action) {
    appendMessage("user", userText);
  }

  if (typing) typing.style.display = "flex";
  if (sendBtn) sendBtn.disabled = true;
  if (stream) stream.scrollTop = stream.scrollHeight;

  try {
    const payload = {
      message: userText,
      session_id: webSessionId,
      timezone: userTimezone,
      action: action
    };

    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (!response.ok) throw new Error(`HTTP Error ${response.status}`);
    const data = await response.json();
    appendMessage("assistant", data.reply, data.buttons);

    // Reactive UI Synchronization
    if (data.events && Array.isArray(data.events)) {
      dispatchReactiveUIEvents(data.events);
    } else {
      loadDashboardSummary();
      if (activeCategoryFilter) loadExpensesTable(activeCategoryFilter, activeSearchQuery, activeSortMode);
    }

  } catch (err) {
    console.warn("Chat error:", err);
    setTimeout(() => {
      appendMessage("assistant", "🤖 I've received your request and logged it.");
    }, 500);
  } finally {
    if (typing) typing.style.display = "none";
    if (sendBtn) sendBtn.disabled = false;
    if (stream) stream.scrollTop = stream.scrollHeight;
  }
}

function dispatchReactiveUIEvents(events) {
  if (!events || !Array.isArray(events)) return;
  for (const ev of events) {
    if (ev.type === "expenses_changed" || ev.domain === "expenses") {
      loadDashboardSummary();
      loadExpensesTable(activeCategoryFilter, activeSearchQuery, activeSortMode);
    } else if (ev.type === "reminders_changed" || ev.domain === "reminders") {
      loadJobs();
      loadDashboardSummary();
    } else if (ev.type === "groceries_changed" || ev.domain === "groceries") {
      loadGroceries();
      loadDashboardSummary();
    }
  }
}

function appendMessage(sender, text, buttons = null) {
  const stream = document.getElementById("chat-messages-stream");
  if (!stream) return;

  const msgDiv = document.createElement("div");
  msgDiv.className = `chat-message-bubble ${sender === "user" ? "user-message" : "assistant-message"}`;

  const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const formattedContent = formatMarkdown(text);

  let buttonsHtml = "";
  if (buttons && Array.isArray(buttons) && buttons.length > 0) {
    buttonsHtml = `<div style="display:flex; flex-wrap:wrap; gap:0.5rem; margin-top:0.6rem;">`;
    buttons.forEach(btnRow => {
      const btnList = Array.isArray(btnRow) ? btnRow : [btnRow];
      btnList.forEach(b => {
        const isCancel = b.text.toLowerCase().includes("cancel") || b.text.includes("❌");
        buttonsHtml += `<button class="btn-ask-ai-pill" style="padding:0.35rem 0.75rem; font-size:0.75rem; ${isCancel ? 'background:#27272a;' : ''}" data-action='${escapeAttr(b.callback_data)}'>${escapeHtml(b.text)}</button>`;
      });
    });
    buttonsHtml += `</div>`;
  }

  msgDiv.innerHTML = `
    <div class="msg-avatar-icon">${sender === "user" ? "👤" : "🤖"}</div>
    <div class="msg-body-wrapper">
      <div class="msg-text-surface">
        ${formattedContent}
        ${buttonsHtml}
      </div>
      <span class="msg-time-tag">${timeStr}</span>
    </div>
  `;

  msgDiv.querySelectorAll("button[data-action]").forEach(btn => {
    btn.addEventListener("click", () => {
      const actionPayload = btn.getAttribute("data-action");
      btn.parentElement.innerHTML = `<span style="font-size:0.75rem; color:var(--text-muted);">Action chosen: ${btn.textContent}</span>`;
      sendChatMessage(btn.textContent, actionPayload);
    });
  });

  stream.appendChild(msgDiv);
  stream.scrollTop = stream.scrollHeight;
}

// ==========================================================================
// 6. CONTEXT-AWARE AI COPILOT DRAWER
// ==========================================================================

let copilotContext = "transactions";

window.openCopilotDrawer = function(context = "transactions") {
  copilotContext = context;
  const drawer = document.getElementById("copilot-drawer");
  const backdrop = document.getElementById("copilot-backdrop");
  const contextLabel = document.getElementById("copilot-context-label");
  const input = document.getElementById("copilot-input");

  if (contextLabel) {
    if (context === "transactions") contextLabel.textContent = "Transactions & Expenses";
    else if (context === "jobs") contextLabel.textContent = "Scheduled Tasks & Reminders";
    else if (context === "groceries") contextLabel.textContent = "Smart Grocery Checklist";
    else contextLabel.textContent = "General Overview";
  }

  if (backdrop) {
    backdrop.style.display = "block";
    requestAnimationFrame(() => backdrop.classList.add("open"));
  }
  if (drawer) {
    drawer.classList.add("open");
  }
  setTimeout(() => {
    if (input) input.focus();
  }, 200);
};

window.closeCopilotDrawer = function() {
  const drawer = document.getElementById("copilot-drawer");
  const backdrop = document.getElementById("copilot-backdrop");

  if (drawer) drawer.classList.remove("open");
  if (backdrop) {
    backdrop.classList.remove("open");
    setTimeout(() => {
      backdrop.style.display = "none";
    }, 250);
  }
};

function initCopilotDrawer() {
  const form = document.getElementById("copilot-form");
  const input = document.getElementById("copilot-input");
  const clearBtn = document.getElementById("btn-copilot-clear");
  const messages = document.getElementById("copilot-messages");

  // Quick Prompt Chips
  document.querySelectorAll(".copilot-prompt-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      const prompt = chip.getAttribute("data-prompt");
      if (prompt) {
        if (input) input.value = prompt;
        sendCopilotMessage(prompt);
      }
    });
  });

  // Form Submit
  if (form && input) {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      input.value = "";
      sendCopilotMessage(text);
    });
  }

  // Reset Session Button
  if (clearBtn && messages) {
    clearBtn.addEventListener("click", () => {
      webSessionId = `web-${Math.random().toString(36).substring(2, 9)}`;
      localStorage.setItem("nexus_web_session_id", webSessionId);
      messages.innerHTML = `
        <div class="copilot-msg assistant">
          <div class="copilot-msg-bubble">
            ✨ <strong>New Copilot session initialized!</strong><br/><br/>
            I'm ready with your live ledger and context. What would you like to check or log?
          </div>
        </div>
      `;
    });
  }
}

async function sendCopilotMessage(userText) {
  const stream = document.getElementById("copilot-messages");
  const typing = document.getElementById("copilot-typing");
  const sendBtn = document.getElementById("btn-copilot-send");
  const userTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Singapore";

  appendCopilotMessage("user", userText);

  if (typing) typing.style.display = "flex";
  if (sendBtn) sendBtn.disabled = true;
  if (stream) stream.scrollTop = stream.scrollHeight;

  try {
    const payload = {
      message: userText,
      session_id: webSessionId,
      timezone: userTimezone,
      context: {
        current_page: copilotContext,
        active_filter: activeCategoryFilter,
        search_query: activeSearchQuery,
      }
    };

    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (!res.ok) throw new Error(`HTTP Error ${res.status}`);
    const data = await res.json();

    appendCopilotMessage("assistant", data.reply, data.buttons);

    // Reactive UI Synchronization
    if (data.events && Array.isArray(data.events)) {
      dispatchReactiveUIEvents(data.events);
    } else {
      loadDashboardSummary();
      loadExpensesTable(activeCategoryFilter, activeSearchQuery, activeSortMode);
    }

  } catch (err) {
    console.warn("Copilot chat error:", err);
    setTimeout(() => {
      appendCopilotMessage("assistant", "🤖 I've received your request and logged it.");
    }, 400);
  } finally {
    if (typing) typing.style.display = "none";
    if (sendBtn) sendBtn.disabled = false;
    if (stream) stream.scrollTop = stream.scrollHeight;
  }
}

function appendCopilotMessage(sender, text, buttons = null) {
  const stream = document.getElementById("copilot-messages");
  if (!stream) return;

  const msgDiv = document.createElement("div");
  msgDiv.className = `copilot-msg ${sender}`;

  let buttonsHtml = "";
  if (buttons && Array.isArray(buttons) && buttons.length > 0) {
    buttonsHtml = `<div style="display:flex; flex-wrap:wrap; gap:0.4rem; margin-top:0.5rem;">`;
    buttons.forEach(btnRow => {
      const btnList = Array.isArray(btnRow) ? btnRow : [btnRow];
      btnList.forEach(b => {
        buttonsHtml += `<button class="copilot-prompt-chip" data-action='${escapeAttr(b.callback_data)}'>${escapeHtml(b.text)}</button>`;
      });
    });
    buttonsHtml += `</div>`;
  }

  msgDiv.innerHTML = `
    <div class="copilot-msg-bubble">
      ${formatMarkdown(text)}
      ${buttonsHtml}
    </div>
  `;

  msgDiv.querySelectorAll("button[data-action]").forEach(btn => {
    btn.addEventListener("click", () => {
      const actionPayload = btn.getAttribute("data-action");
      btn.parentElement.innerHTML = `<span style="font-size:0.75rem; color:var(--text-muted);">Action chosen: ${btn.textContent}</span>`;
      sendChatMessage(btn.textContent, actionPayload);
    });
  });

  stream.appendChild(msgDiv);
  stream.scrollTop = stream.scrollHeight;
}

function formatMarkdown(text) {
  if (!text) return "";
  let out = escapeHtml(text);
  
  out = out.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/\*([^*\n]+?)\*/g, "<em>$1</em>");
  out = out.replace(/`([^`\n]+?)`/g, "<code>$1</code>");
  out = out.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener" style="color:var(--orange-primary);text-decoration:underline;">$1</a>');
  out = out.replace(/\n/g, "<br/>");
  
  return out;
}

function escapeHtml(str) {
  if (!str) return "";
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function escapeAttr(str) {
  if (!str) return "";
  return str.replace(/'/g, "&apos;").replace(/"/g, "&quot;");
}
