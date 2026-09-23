/**
 * Nexus Prime — Financial Cockpit & Expenses Engine
 * Implements Mowany-style 2-column dashboard, SVG donut category visualizer, ledger table, and live assistant chat.
 */

// Application State & Global Registries
let webSessionId = localStorage.getItem("nexus_web_session_id") || `web-${Math.random().toString(36).substring(2, 9)}`;
localStorage.setItem("nexus_web_session_id", webSessionId);

let activeCategoryFilter = "all";
let activeSearchQuery = "";
let currentExpensesList = [];
let activeSortMode = "latest";
let selectedExpenseIds = new Set();
let undoStack = [];
let currentPage = 1;
let pageSize = 10;

// Category Visual Styling
const CATEGORY_MAP = {
  "Dining": { icon: "🍔", color: "#f43f5e", bg: "rgba(244, 63, 94, 0.15)" },
  "Groceries": { icon: "🛒", color: "#10b981", bg: "rgba(16, 185, 129, 0.15)" },
  "Transport": { icon: "🚌", color: "#06b6d4", bg: "rgba(6, 182, 212, 0.15)" },
  "Shopping": { icon: "🛍️", color: "#a855f7", bg: "rgba(168, 85, 247, 0.15)" },
  "Bills": { icon: "💡", color: "#f97316", bg: "rgba(249, 115, 22, 0.15)" },
  "General": { icon: "💳", color: "#71717a", bg: "rgba(113, 113, 122, 0.15)" }
};

function escapeHtml(str) {
  if (!str) return "";
  return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function escapeAttr(str) {
  if (!str) return "";
  return String(str).replace(/'/g, "&apos;").replace(/"/g, "&quot;");
}

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

function mergeDashboardCategories(categories, totalSpend) {
  const merged = new Map();
  for (const item of Array.isArray(categories) ? categories : []) {
    const category = normalizeCategory(item.category);
    const current = merged.get(category) || { category, amount: 0, count: 0 };
    current.amount += Number(item.amount) || 0;
    current.count += Number(item.count) || 0;
    merged.set(category, current);
  }
  return [...merged.values()]
    .sort((a, b) => b.amount - a.amount)
    .map((item) => ({
      ...item,
      amount: Math.round(item.amount * 100) / 100,
      percentage: totalSpend > 0
        ? Math.round((item.amount / totalSpend) * 1000) / 10
        : 0,
    }));
}

function getUserId() {
  const urlParams = new URLSearchParams(window.location.search);
  const qUid = urlParams.get("user_id");
  if (qUid) {
    localStorage.setItem("nexus_user_id", qUid);
    return qUid;
  }
  return localStorage.getItem("nexus_user_id") || "";
}

function getApiUrl(path) {
  const uid = getUserId();
  if (!uid) return path;
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}user_id=${encodeURIComponent(uid)}`;
}

// Initialization
document.addEventListener("DOMContentLoaded", () => {
  initRailNavigation();
  initDashboard();
  initExpenseModal();
  initTransactionDetailsModal();

  // Auto-sync dashboard from live database every 8s
  setInterval(() => {
    const activeTab = document.querySelector(".rail-nav-btn.active")?.getAttribute("data-tab");
    if (activeTab === "tab-expenses") {
      loadDashboardSummary();
      loadExpensesTable(activeCategoryFilter, activeSearchQuery, activeSortMode);
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
  }
}

// ==========================================================================
// 1. TRANSACTIONS DASHBOARD & FINANCIAL BREAKDOWN
// ==========================================================================

function initDashboard() {
  if (document.getElementById("tx-direction-filter") && typeof window.initUnifiedTransactions === "function") {
    window.initUnifiedTransactions();
    loadDashboardSummary();
    return;
  }

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

function localDateTimeValue(date = new Date()) {
  const local = new Date(date);
  local.setMinutes(local.getMinutes() - local.getTimezoneOffset());
  return local.toISOString().slice(0, 16);
}

async function loadDashboardSummary() {
  try {
    const res = await fetch(getApiUrl("/api/dashboard/summary"));
    if (!res.ok) throw new Error("Failed to load summary");
    const data = await res.json();
    data.categories = mergeDashboardCategories(data.categories, data.total_spent_month);

    // Top 3 Metric Cards Figures
    const monthTxCount = document.getElementById("kpi-month-tx-count");
    if (monthTxCount) monthTxCount.textContent = `${data.month_transactions_count ?? 0}`;

    const totalTx = document.getElementById("kpi-total-tx");
    if (totalTx) totalTx.textContent = `${data.total_transactions_count}`;

    const monthSpend = document.getElementById("kpi-month-spend");
    if (monthSpend) monthSpend.textContent = `$${data.total_spent_month.toFixed(2)}`;

    const incomeMonth = document.getElementById("kpi-income-month");
    if (incomeMonth) incomeMonth.textContent = `$${(data.total_income_month || 0).toFixed(2)}`;
    const incomeAll = document.getElementById("kpi-income-all");
    if (incomeAll) incomeAll.textContent = `$${(data.total_income_all || 0).toFixed(2)}`;
    const incomeCount = document.getElementById("kpi-income-count");
    if (incomeCount) incomeCount.textContent = `${data.income_transactions_count || 0} record${data.income_transactions_count === 1 ? "" : "s"}`;
    const netCashflow = document.getElementById("kpi-net-cashflow");
    if (netCashflow) {
      const net = data.net_cash_flow_month || 0;
      netCashflow.textContent = `${net < 0 ? "-" : ""}$${Math.abs(net).toFixed(2)}`;
      netCashflow.style.color = net >= 0 ? "var(--emerald-accent)" : "#f87171";
    }

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

    if (data.categories && data.categories.length > 0) {
      const topCat = data.categories[0];
      if (insightText) {
        insightText.textContent = `Your ${topCat.category.toLowerCase()} spending represents ${topCat.percentage}% of this month's budget.`;
      }
    } else {
      if (insightText) {
        insightText.textContent = "Log expenses or forward receipts to see your category insights.";
      }
    }

    if (aiDynamicBody) {
      const count = data.month_transactions_count || data.total_transactions_count || 0;
      if (count === 0) {
        aiDynamicBody.innerHTML = `No transactions recorded for this period yet. Send a money-in or money-out message in Telegram or click <strong>+ Log Transaction</strong> to get started.`;
      } else {
        const topM = data.top_merchants && data.top_merchants.length > 0 ? data.top_merchants[0] : null;
        const topMText = topM ? `your top merchant is <strong>${escapeHtml(topM.merchant)}</strong> ($${topM.amount.toFixed(2)})` : "your spend is evenly distributed";
        aiDynamicBody.innerHTML = `You have logged <strong>${count} transactions</strong> totaling <strong>$${(data.total_spent_month || 0).toFixed(2)}</strong> this month. Based on your spending velocity, ${topMText}.`;
      }
    }

    // Render Top Merchants Mini List in Sidebar
    const miniList = document.getElementById("merchants-mini-list");
    if (miniList) {
      if (!data.top_merchants || data.top_merchants.length === 0) {
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

async function loadExpensesTable(category = "all", search = "", sort = "latest") {
  if (document.getElementById("tx-direction-filter") && typeof window.loadUnifiedTransactions === "function") {
    return window.loadUnifiedTransactions();
  }

  try {
    let url = getApiUrl(`/api/dashboard/expenses?limit=100`);
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

function formatExpenseDateTime(dateVal) {
  if (!dateVal) return "—";
  const monthNames = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

  if (typeof dateVal === "string" && /^\d{4}-\d{2}-\d{2}$/.test(dateVal.trim())) {
    const [y, m, day] = dateVal.trim().split("-").map(Number);
    return `${monthNames[m - 1]} ${day}, ${y}`;
  }

  const d = new Date(dateVal);
  if (isNaN(d.getTime())) return String(dateVal);

  const dateStr = `${monthNames[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`;
  const isMidnight = d.getHours() === 0 && d.getMinutes() === 0 && d.getSeconds() === 0;
  const isDateOnlyIso = typeof dateVal === "string" && (
    dateVal.endsWith("T00:00:00") ||
    dateVal.endsWith("T00:00:00Z") ||
    dateVal.endsWith("T00:00:00+00:00") ||
    !dateVal.includes("T")
  );

  if (isMidnight && isDateOnlyIso) {
    return dateStr;
  }

  const timeStr = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  return `${dateStr} · ${timeStr}`;
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
    const isFiltered = Boolean(activeSearchQuery || (activeCategoryFilter && activeCategoryFilter !== "all"));
    tbody.innerHTML = `
      <tr>
        <td colspan="7" style="padding: 3.5rem 1rem; text-align: center; color: var(--text-muted);">
          <div style="font-size: 1.75rem; margin-bottom: 0.5rem;">💳</div>
          <div style="font-size: 0.95rem; font-weight: 500; color: #d4d4d8;">
            ${isFiltered ? `No transactions found matching "${escapeHtml(activeSearchQuery || activeCategoryFilter)}"` : "No transactions recorded yet"}
          </div>
          <div style="font-size: 0.78rem; color: #71717a; margin-top: 0.35rem;">
            ${isFiltered ? "Try clearing your search keyword or selecting 'All money movement'." : "Forward receipts or send money-in and money-out messages via Telegram to start tracking."}
          </div>
        </td>
      </tr>
    `;
    selectedExpenseIds.clear();
    updateBatchActionBar();
    if (navContainer) {
      navContainer.innerHTML = `<button class="page-num-btn active" disabled>1</button>`;
    }
    return;
  }

  tbody.innerHTML = pageRows.map((tx) => {
    const txnId = `TXN-24080${String(tx.id).padStart(3, '0')}`;
    const normCat = normalizeCategory(tx.category);
    const catCfg = CATEGORY_MAP[normCat] || CATEGORY_MAP["General"];
    const formattedDate = formatExpenseDateTime(tx.date);
    const isChecked = selectedExpenseIds.has(tx.id);
    const hasSplit = tx.split_data && Array.isArray(tx.split_data.friends) && tx.split_data.friends.length > 1;

    return `
      <tr data-id="${tx.id}" style="cursor: pointer;" onclick="openTransactionDetailsModal(${tx.id})" title="Click to view details, receipt items or split bill">
        <td style="text-align: center;" onclick="event.stopPropagation()">
          <input type="checkbox" class="dash-checkbox row-checkbox" data-id="${tx.id}" ${isChecked ? 'checked' : ''} onchange="toggleRowCheckbox(${tx.id}, this.checked)" />
        </td>
        <td class="td-txn-id">${txnId}</td>
        <td>
          <div class="td-payment-name-cell">
            <div class="merchant-mini-icon" style="background: ${catCfg.bg}; color: ${catCfg.color};">
              ${catCfg.icon}
            </div>
            <div style="display: flex; flex-direction: column; min-width: 0;">
              <span class="merchant-title-text">${escapeHtml(tx.merchant)}</span>
              ${hasSplit ? `<span style="font-size: 0.65rem; color: var(--orange-primary); font-weight: 700;">🔀 Split (${tx.split_data.friends.length} people)</span>` : ''}
            </div>
          </div>
        </td>
        <td class="td-amount-figure debit">-$${tx.amount.toFixed(2)}</td>
        <td class="td-date-cell">${formattedDate}</td>
        <td style="text-align: center;">
          <span class="status-badge-pill completed">Completed</span>
        </td>
        <td style="text-align: center;" onclick="event.stopPropagation()">
          <div style="display: flex; justify-content: center; gap: 0.35rem;">
            <button class="row-action-btn" onclick="event.stopPropagation(); openTransactionDetailsModal(${tx.id})" title="Details & Split Bill">🔀</button>
            <button class="row-action-btn" onclick="event.stopPropagation(); openEditExpenseModal(${tx.id})" title="Quick edit">✏️</button>
            <button class="row-action-btn" onclick="event.stopPropagation(); deleteExpenseItem(${tx.id})" title="Delete expense">🗑️</button>
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
    if (!e.target.closest(".modal-card-dialog")) modal.style.display = "none";
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

// 8. TRANSACTION DETAILS, RECEIPT OCR & BILL SPLITTING WORKBENCH
// ==========================================================================

let activeDetailExpense = null;
let detailLineItems = [];
let splitFriends = ["Me"];
let splitPaidStatus = {};
let isSplitEvenly = false;
let isTotalInclusive = true;
let splitChargeBackup = { svc: 0.0, tax: 0.0 };
let isCustomSplit = false;
let customSplitAmounts = {};
let customSplitMode = "amount";
let customSplitInputs = {};
let customSplitTouched = new Set();

const CUSTOM_SPLIT_MODES = {
  amount: {
    title: "Custom amounts due",
    hint: "Enter a fixed share; the remainder is distributed across untouched people.",
    placeholder: "0.00",
    inputType: "number",
    inputMode: "decimal",
    prefix: "$",
    suffix: "",
  },
  ratio: {
    title: "Custom ratio shares",
    hint: "Enter one weight per person, or type a shorthand such as 2:1 for two people.",
    placeholder: "1",
    inputType: "text",
    inputMode: "text",
    prefix: "x",
    suffix: "",
  },
  percentage: {
    title: "Custom percentage shares",
    hint: "Enter each person's percentage. The total must equal 100%.",
    placeholder: "50",
    inputType: "number",
    inputMode: "decimal",
    prefix: "",
    suffix: "%",
  },
  fraction: {
    title: "Custom fraction shares",
    hint: "Enter fractions such as 1/2. The fractions must add up to 1.",
    placeholder: "1/2",
    inputType: "text",
    inputMode: "text",
    prefix: "",
    suffix: "of total",
  },
};

function initTransactionDetailsModal() {
  const modal = document.getElementById("modal-transaction-details");
  const btnClose = document.getElementById("btn-close-tx-detail-modal");
  const btnCancel = document.getElementById("btn-cancel-tx-detail");
  const btnSave = document.getElementById("btn-save-tx-detail");
  const btnDelete = document.getElementById("btn-delete-tx-detail");
  const btnAddFriend = document.getElementById("btn-add-split-friend");
  const friendInput = document.getElementById("split-add-friend-input");
  const btnAddItem = document.getElementById("btn-add-line-item");
  const btnCopyMsg = document.getElementById("btn-copy-split-msg");
  const evenCheckbox = document.getElementById("split-even-checkbox");
  const totalInclusiveCheckbox = document.getElementById("tx-input-total-inclusive");
  const customSplitCheckbox = document.getElementById("split-custom-checkbox");
  const customSplitModeSelect = document.getElementById("split-custom-mode");

  // Tabs inside modal
  const tabReceiptBtn = document.getElementById("btn-tx-tab-receipt");
  const tabSplitBtn = document.getElementById("btn-tx-tab-split");
  const paneReceipt = document.getElementById("tx-tab-pane-receipt");
  const paneSplit = document.getElementById("tx-tab-pane-split");

  if (tabReceiptBtn && tabSplitBtn) {
    tabReceiptBtn.addEventListener("click", () => {
      tabReceiptBtn.classList.add("active");
      tabSplitBtn.classList.remove("active");
      if (paneReceipt) paneReceipt.style.display = "";
      if (paneSplit) paneSplit.style.display = "none";
    });

    tabSplitBtn.addEventListener("click", () => {
      tabSplitBtn.classList.add("active");
      tabReceiptBtn.classList.remove("active");
      if (paneReceipt) paneReceipt.style.display = "none";
      if (paneSplit) paneSplit.style.display = "";
      renderSplitWorkbench();
    });
  }

  // Close handlers
  if (btnClose) btnClose.addEventListener("click", closeTransactionDetailsModal);
  if (btnCancel) btnCancel.addEventListener("click", closeTransactionDetailsModal);
  if (modal) {
    modal.addEventListener("click", (e) => {
      if (!e.target.closest(".modal-dialog-split")) closeTransactionDetailsModal();
    });
  }

  // Delete handler
  if (btnDelete) {
    btnDelete.addEventListener("click", async () => {
      if (!activeDetailExpense) return;
      if (!confirm(`Are you sure you want to delete this expense record (#${activeDetailExpense.id})?`)) return;
      await deleteExpenseItem(activeDetailExpense.id);
      closeTransactionDetailsModal();
    });
  }

  // Fetch email context handler
  const fetchCtxBtn = document.getElementById("btn-fetch-email-context");
  if (fetchCtxBtn) {
    fetchCtxBtn.addEventListener("click", () => {
      const expenseId = fetchCtxBtn.dataset.expenseId;
      if (expenseId) window.fetchEmailContext(expenseId);
    });
  }

  // Save details handler
  if (btnSave) {
    btnSave.addEventListener("click", saveTransactionDetails);
  }

  // Add line item
  if (btnAddItem) {
    btnAddItem.addEventListener("click", () => {
      detailLineItems.push({
        name: "New Item",
        quantity: 1,
        price: 0.0,
        assigned_to: [...splitFriends],
      });
      renderDetailLineItems();
      calculateChargesAndTotal();
    });
  }

  // Charges input change listeners
  ["tx-input-svc-pct", "tx-input-tax-pct", "tx-input-discount", "tx-input-grand-total"].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener("input", () => {
        calculateChargesAndTotal();
      });
    }
  });

  if (totalInclusiveCheckbox) {
    totalInclusiveCheckbox.addEventListener("change", () => {
      isTotalInclusive = totalInclusiveCheckbox.checked;
      applyTotalInclusiveMode();
      calculateChargesAndTotal();
    });
  }

  // Friend manager
  if (btnAddFriend && friendInput) {
    const addFriend = () => {
      const name = friendInput.value.trim();
      if (!name) return;
      if (!splitFriends.includes(name)) {
        splitFriends.push(name);
        if (!(name in splitPaidStatus)) {
          splitPaidStatus[name] = false;
        }
        // Assign new friend to existing items if unassigned
        detailLineItems.forEach(it => {
          if (!it.assigned_to || it.assigned_to.length === 0) {
            it.assigned_to = [...splitFriends];
          }
        });
      }
      friendInput.value = "";
      renderSplitWorkbench();
    };

    btnAddFriend.addEventListener("click", addFriend);
    friendInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        addFriend();
      }
    });
  }

  // Even split checkbox
  if (evenCheckbox) {
    evenCheckbox.addEventListener("change", () => {
      isSplitEvenly = evenCheckbox.checked;
      if (isSplitEvenly) {
        isCustomSplit = false;
        const customCheckbox = document.getElementById("split-custom-checkbox");
        if (customCheckbox) customCheckbox.checked = false;
      }
      const assignSec = document.getElementById("split-assignment-section");
      if (assignSec) {
        assignSec.style.display = isSplitEvenly ? "none" : "";
      }
      renderSplitWorkbench();
    });
  }

  if (customSplitCheckbox) {
    customSplitCheckbox.addEventListener("change", () => {
      isCustomSplit = customSplitCheckbox.checked;
      if (isCustomSplit) {
        isSplitEvenly = false;
        customSplitTouched = new Set();
        if (evenCheckbox) evenCheckbox.checked = false;
        ensureCustomSplitAmounts();
      }
      renderSplitWorkbench();
    });
  }

  if (customSplitModeSelect) {
    customSplitModeSelect.addEventListener("change", () => {
      setCustomSplitMode(customSplitModeSelect.value);
    });
  }

  // Copy Telegram/WhatsApp Message
  if (btnCopyMsg) {
    btnCopyMsg.addEventListener("click", () => {
      const textarea = document.getElementById("split-formatted-preview");
      if (!textarea) return;
      textarea.select();
      navigator.clipboard.writeText(textarea.value);
      showToast("📋 Copied WhatsApp / Telegram Breakdown to clipboard!");
    });
  }

  // Receipt OCR file upload & drag-drop
  initReceiptOcrUploader();
}

function initReceiptOcrUploader() {
  const dropzone = document.getElementById("receipt-ocr-dropzone");
  const fileInput = document.getElementById("receipt-file-input");
  const triggerBtn = document.getElementById("btn-trigger-receipt-file");

  if (!dropzone || !fileInput) return;

  if (triggerBtn) {
    triggerBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      fileInput.click();
    });
  }

  dropzone.addEventListener("click", () => fileInput.click());

  fileInput.addEventListener("change", (e) => {
    const file = e.target.files?.[0];
    if (file) processReceiptImageFile(file);
  });

  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.style.borderColor = "var(--orange-primary)";
    dropzone.style.background = "rgba(255, 107, 53, 0.08)";
  });

  dropzone.addEventListener("dragleave", () => {
    dropzone.style.borderColor = "";
    dropzone.style.background = "";
  });

  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.style.borderColor = "";
    dropzone.style.background = "";
    const file = e.dataTransfer?.files?.[0];
    if (file && file.type.startsWith("image/")) {
      processReceiptImageFile(file);
    }
  });
}

async function processReceiptImageFile(file) {
  const idleBox = document.getElementById("ocr-dropzone-idle");
  const loadingBox = document.getElementById("ocr-dropzone-loading");

  if (idleBox) idleBox.style.display = "none";
  if (loadingBox) loadingBox.style.display = "flex";

  try {
    const base64Data = await readFileAsBase64(file);
    const mimeType = file.type || "image/jpeg";

    const res = await fetch(getApiUrl("/api/dashboard/expenses/ocr-receipt"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        image_b64: base64Data,
        mime_type: mimeType,
      }),
    });

    if (!res.ok) throw new Error("OCR request failed");
    const data = await res.json();
    const receipt = data.receipt || {};

    if (receipt.merchant && receipt.merchant !== "Unknown Merchant") {
      const merchantInput = document.getElementById("tx-detail-input-merchant");
      if (merchantInput) merchantInput.value = receipt.merchant;
      const titleEl = document.getElementById("tx-detail-merchant");
      if (titleEl) titleEl.textContent = receipt.merchant;
    }

    if (receipt.category) {
      const catSelect = document.getElementById("tx-detail-input-category");
      if (catSelect) catSelect.value = normalizeCategory(receipt.category);
    }

    // Set extracted items
    if (Array.isArray(receipt.items) && receipt.items.length > 0) {
      detailLineItems = receipt.items.map(it => ({
        name: it.name || "Item",
        quantity: parseInt(it.quantity) || 1,
        price: parseFloat(it.price) || 0.0,
        assigned_to: it.assigned_to || [...splitFriends],
      }));
    }

    // Set tax and service charges
    if (receipt.service_charge_pct !== undefined) {
      const svcel = document.getElementById("tx-input-svc-pct");
      if (svcel) svcel.value = receipt.service_charge_pct;
    }
    if (receipt.tax_pct !== undefined) {
      const taxel = document.getElementById("tx-input-tax-pct");
      if (taxel) taxel.value = receipt.tax_pct;
    }
    if (receipt.discount !== undefined) {
      const discel = document.getElementById("tx-input-discount");
      if (discel) discel.value = receipt.discount;
    }

    renderDetailLineItems();
    calculateChargesAndTotal();

    showToast(`⚡ Scanned ${detailLineItems.length} items with Gemini Vision!`);

  } catch (err) {
    console.error("Receipt OCR processing failed:", err);
    showToast("⚠️ Could not parse receipt photo. You can add items manually.");
  } finally {
    if (idleBox) idleBox.style.display = "flex";
    if (loadingBox) loadingBox.style.display = "none";
  }
}

function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = error => reject(error);
    reader.readAsDataURL(file);
  });
}

async function openTransactionDetailsModal(expenseId) {
  const modal = document.getElementById("modal-transaction-details");
  if (!modal) return;

  // Find in cached list or fetch
  let expense = (currentExpensesList || []).find(e => e.id === expenseId);
  try {
    const res = await fetch(getApiUrl(`/api/dashboard/expenses/${expenseId}/details`));
    if (res.ok) {
      const data = await res.json();
      if (data.expense) expense = data.expense;
    }
  } catch (err) {
    console.warn("Could not fetch remote expense details:", err);
  }

  if (!expense) return;
  activeDetailExpense = expense;

  // Header
  const titleEl = document.getElementById("tx-detail-merchant");
  const catPill = document.getElementById("tx-detail-cat-pill");
  const sourcePill = document.getElementById("tx-detail-source-pill");
  const dateSub = document.getElementById("tx-detail-date-sub");
  const totalVal = document.getElementById("tx-detail-header-total-val");

  if (titleEl) titleEl.textContent = expense.merchant || "Transaction Details";
  if (catPill) {
    const norm = normalizeCategory(expense.category);
    catPill.textContent = norm;
    const cfg = CATEGORY_MAP[norm] || CATEGORY_MAP["General"];
    catPill.style.background = cfg.bg;
    catPill.style.color = cfg.color;
  }
  if (sourcePill) sourcePill.textContent = expense.source || "ledger";
  if (dateSub) dateSub.textContent = `Recorded on ${formatExpenseDateTime(expense.date)}`;
  if (totalVal) totalVal.textContent = `$${expense.amount.toFixed(2)}`;

  // Payment context block
  const contextBlock = document.getElementById("tx-payment-context-block");
  const contextText = document.getElementById("tx-payment-context-text");
  const fetchBtn = document.getElementById("btn-fetch-email-context");
  if (contextBlock) {
    if (expense.notes) {
      if (contextText) contextText.textContent = expense.notes;
      if (fetchBtn) fetchBtn.style.display = "none";
      contextBlock.style.display = "flex";
    } else if (expense.source === "gmail" || expense.from_email) {
      if (contextText) contextText.textContent = "";
      if (fetchBtn) {
        fetchBtn.style.display = "";
        fetchBtn.dataset.expenseId = expense.id;
      }
      contextBlock.style.display = "flex";
    } else {
      contextBlock.style.display = "none";
    }
  }

  // Meta inputs
  const merchantInput = document.getElementById("tx-detail-input-merchant");
  const catSelect = document.getElementById("tx-detail-input-category");
  if (merchantInput) merchantInput.value = expense.merchant || "";
  if (catSelect) catSelect.value = normalizeCategory(expense.category);

  // Setup items
  if (Array.isArray(expense.receipt_items) && expense.receipt_items.length > 0) {
    detailLineItems = JSON.parse(JSON.stringify(expense.receipt_items));
  } else {
    // Default to 1 item matching transaction
    detailLineItems = [
      {
        name: expense.merchant || "General Item",
        quantity: 1,
        price: expense.amount || 0.0,
        assigned_to: ["Me"],
      }
    ];
  }

  // Setup split data
  const splitData = expense.split_data || {};
  if (Array.isArray(splitData.friends) && splitData.friends.length > 0) {
    splitFriends = [...splitData.friends];
  } else {
    splitFriends = ["Me"];
  }
  customSplitAmounts = {};
  customSplitInputs = {};
  customSplitTouched = new Set();
  customSplitMode = Object.prototype.hasOwnProperty.call(CUSTOM_SPLIT_MODES, splitData.custom_allocation_mode)
    ? splitData.custom_allocation_mode
    : "amount";
  const savedInputs = splitData.custom_allocations && typeof splitData.custom_allocations === "object"
    ? splitData.custom_allocations
    : splitData.custom_amounts;
  if (savedInputs && typeof savedInputs === "object") {
    splitFriends.forEach(friend => {
      if (Object.prototype.hasOwnProperty.call(savedInputs, friend)) {
        customSplitInputs[friend] = String(savedInputs[friend]);
      }
    });
  }

  splitPaidStatus = splitData.paid_status || {};
  splitFriends.forEach(f => {
    if (!(f in splitPaidStatus)) splitPaidStatus[f] = (f === "Me");
  });

  isSplitEvenly = Boolean(splitData.is_even);
  isCustomSplit = (
    splitData.split_mode === "custom"
    || Boolean(splitData.custom_amounts)
    || Boolean(splitData.custom_allocation_mode)
  );
  if (isCustomSplit) isSplitEvenly = false;
  const evenCheckbox = document.getElementById("split-even-checkbox");
  if (evenCheckbox) evenCheckbox.checked = isSplitEvenly;
  const customCheckbox = document.getElementById("split-custom-checkbox");
  if (customCheckbox) customCheckbox.checked = isCustomSplit;
  const customModeSelect = document.getElementById("split-custom-mode");
  if (customModeSelect) customModeSelect.value = customSplitMode;

  const svcel = document.getElementById("tx-input-svc-pct");
  const taxel = document.getElementById("tx-input-tax-pct");
  const discel = document.getElementById("tx-input-discount");
  const hasSavedChargeConfig = (
    Object.prototype.hasOwnProperty.call(splitData, "svc_pct")
    || Object.prototype.hasOwnProperty.call(splitData, "tax_pct")
    || Object.prototype.hasOwnProperty.call(splitData, "total_inclusive")
  );
  const defaultSvc = splitData.svc_pct ?? (expense.category === "Dining" ? 10 : 0);
  const defaultTax = splitData.tax_pct ?? (expense.category === "Dining" || expense.category === "Shopping" ? 9 : 0);
  splitChargeBackup = { svc: Number(defaultSvc) || 0, tax: Number(defaultTax) || 0 };
  // Existing ledger amounts are normally already settled totals. Preserve the
  // old extra-charge mode only for transactions that explicitly saved it.
  isTotalInclusive = splitData.total_inclusive ?? !hasSavedChargeConfig;
  if (svcel) svcel.value = defaultSvc;
  if (taxel) taxel.value = defaultTax;
  if (discel) discel.value = splitData.discount ?? 0.0;
  const totalInclusiveEl = document.getElementById("tx-input-total-inclusive");
  if (totalInclusiveEl) totalInclusiveEl.checked = isTotalInclusive;
  applyTotalInclusiveMode();

  // Default tab is Receipt
  const tabReceiptBtn = document.getElementById("btn-tx-tab-receipt");
  const tabSplitBtn = document.getElementById("btn-tx-tab-split");
  const paneReceipt = document.getElementById("tx-tab-pane-receipt");
  const paneSplit = document.getElementById("tx-tab-pane-split");
  if (tabReceiptBtn) tabReceiptBtn.classList.add("active");
  if (tabSplitBtn) tabSplitBtn.classList.remove("active");
  if (paneReceipt) paneReceipt.style.display = "";
  if (paneSplit) paneSplit.style.display = "none";

  renderDetailLineItems();
  calculateChargesAndTotal();

  modal.style.display = "flex";
}

window.fetchEmailContext = async function fetchEmailContext(expenseId) {
  try {
    const res = await fetch(getApiUrl(`/api/dashboard/expenses/${expenseId}/email-context`));
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `Server returned ${res.status}`);
    if (data.context) {
      const contextText = document.getElementById("tx-payment-context-text");
      const fetchBtn = document.getElementById("btn-fetch-email-context");
      if (contextText) contextText.textContent = data.context;
      if (fetchBtn) fetchBtn.style.display = "none";
      showToast("Email context loaded");
    } else {
      showToast("No email context found for this transaction");
    }
  } catch (error) {
    showToast(`Could not fetch email context: ${error.message}`, "danger");
  }
};

function closeTransactionDetailsModal() {
  const modal = document.getElementById("modal-transaction-details");
  if (modal) modal.style.display = "none";
  activeDetailExpense = null;
}

function renderDetailLineItems() {
  const tbody = document.getElementById("tx-line-items-tbody");
  if (!tbody) return;

  if (detailLineItems.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="4" style="text-align: center; color: #71717a; padding: 1rem;">
          No line items yet. Click "+ Add Item" or scan a receipt photo above.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = detailLineItems.map((it, idx) => `
    <tr>
      <td>
        <input type="text" class="tx-item-input-name" value="${escapeAttr(it.name)}" oninput="updateLineItemField(${idx}, 'name', this.value)" placeholder="Item or dish name..." />
      </td>
      <td style="text-align: center;">
        <input type="number" min="1" step="1" class="tx-item-input-qty" value="${it.quantity || 1}" oninput="updateLineItemField(${idx}, 'quantity', parseInt(this.value) || 1)" />
      </td>
      <td style="text-align: right;">
        <input type="number" min="0" step="0.01" class="tx-item-input-price" value="${(it.price || 0).toFixed(2)}" oninput="updateLineItemField(${idx}, 'price', parseFloat(this.value) || 0)" />
      </td>
      <td style="text-align: center;">
        <button type="button" class="tx-item-btn-del" onclick="deleteLineItem(${idx})" title="Delete row">✕</button>
      </td>
    </tr>
  `).join("");
}

function updateLineItemField(idx, field, val) {
  if (detailLineItems[idx]) {
    detailLineItems[idx][field] = val;
    calculateChargesAndTotal();
  }
}

function deleteLineItem(idx) {
  detailLineItems.splice(idx, 1);
  renderDetailLineItems();
  calculateChargesAndTotal();
}

function calculateChargesAndTotal() {
  const subtotal = detailLineItems.reduce((acc, it) => acc + (it.price * (it.quantity || 1)), 0.0);
  const svcPct = parseFloat(document.getElementById("tx-input-svc-pct")?.value) || 0.0;
  const taxPct = parseFloat(document.getElementById("tx-input-tax-pct")?.value) || 0.0;
  const discount = parseFloat(document.getElementById("tx-input-discount")?.value) || 0.0;
  const inclusive = document.getElementById("tx-input-total-inclusive")?.checked ?? isTotalInclusive;
  const svcAmt = inclusive ? 0.0 : subtotal * (svcPct / 100.0);
  const taxAmt = inclusive ? 0.0 : (subtotal + svcAmt) * (taxPct / 100.0);
  const grandTotal = Math.max(0, subtotal + svcAmt + taxAmt - discount);

  const subtotalEl = document.getElementById("tx-input-subtotal");
  const grandTotalEl = document.getElementById("tx-input-grand-total");
  const headerTotalEl = document.getElementById("tx-detail-header-total-val");

  if (subtotalEl) subtotalEl.value = subtotal.toFixed(2);
  if (grandTotalEl) grandTotalEl.value = grandTotal.toFixed(2);
  if (headerTotalEl) headerTotalEl.textContent = `$${grandTotal.toFixed(2)}`;

  const splitBadge = document.getElementById("tx-split-count-badge");
  if (splitBadge) splitBadge.textContent = splitFriends.length;

  renderSplitWorkbench();
}

function applyTotalInclusiveMode() {
  const checkbox = document.getElementById("tx-input-total-inclusive");
  const svcEl = document.getElementById("tx-input-svc-pct");
  const taxEl = document.getElementById("tx-input-tax-pct");
  const hintEl = document.querySelector(".tx-inclusive-toggle small");
  const inclusive = checkbox?.checked ?? isTotalInclusive;
  isTotalInclusive = inclusive;

  if (inclusive) {
    // Keep the user's extra-charge values available if they switch modes.
    if (svcEl && !svcEl.disabled) splitChargeBackup.svc = parseFloat(svcEl.value) || 0.0;
    if (taxEl && !taxEl.disabled) splitChargeBackup.tax = parseFloat(taxEl.value) || 0.0;
    if (svcEl) { svcEl.value = "0"; svcEl.disabled = true; }
    if (taxEl) { taxEl.value = "0"; taxEl.disabled = true; }
    if (hintEl) hintEl.textContent = "Charges are included in the original total and are not added again.";
  } else {
    if (svcEl) { svcEl.value = splitChargeBackup.svc; svcEl.disabled = false; }
    if (taxEl) { taxEl.value = splitChargeBackup.tax; taxEl.disabled = false; }
    if (hintEl) hintEl.textContent = "Uncheck only when adding charges to a pre-tax subtotal.";
  }
}

function renderSplitWorkbench() {
  renderFriendPills();
  renderCustomSplitAmounts();
  renderItemAssignmentCards();
  renderSplitCalculations();
}

function renderFriendPills() {
  const container = document.getElementById("split-friends-chips-row");
  if (!container) return;

  container.innerHTML = splitFriends.map(f => {
    const initial = f.charAt(0).toUpperCase();
    const isMe = f === "Me";
    return `
      <div class="friend-pill-chip">
        <div class="friend-avatar-dot">${initial}</div>
        <span>${escapeHtml(f)}</span>
        ${!isMe ? `<button type="button" class="friend-remove-x" onclick="removeSplitFriend('${escapeAttr(f)}')">✕</button>` : ''}
      </div>
    `;
  }).join("");
}

function removeSplitFriend(name) {
  if (name === "Me") return;
  splitFriends = splitFriends.filter(f => f !== name);
  delete splitPaidStatus[name];
  delete customSplitInputs[name];
  customSplitTouched.delete(name);
  delete customSplitAmounts[name];
  // Remove from assigned items
  detailLineItems.forEach(it => {
    if (Array.isArray(it.assigned_to)) {
      it.assigned_to = it.assigned_to.filter(f => f !== name);
      if (it.assigned_to.length === 0) it.assigned_to = ["Me"];
    }
  });
  renderSplitWorkbench();
}

function parseCustomSplitNumber(value) {
  const raw = String(value ?? "").trim();
  if (!raw || !/^(?:\d+(?:\.\d*)?|\.\d+)$/.test(raw)) return null;
  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

function parseCustomSplitFraction(value) {
  const raw = String(value ?? "").trim();
  if (!raw) return null;
  const fraction = raw.match(/^(\d+(?:\.\d*)?)\s*\/\s*(\d+(?:\.\d*)?)$/);
  if (fraction) {
    const numerator = Number(fraction[1]);
    const denominator = Number(fraction[2]);
    if (Number.isFinite(numerator) && Number.isFinite(denominator) && denominator > 0) {
      return numerator / denominator;
    }
    return null;
  }
  return parseCustomSplitNumber(raw);
}

function allocateCustomSplitCents(totalCents, weights) {
  const weightTotal = weights.reduce((sum, weight) => sum + (weight || 0), 0);
  if (!(weightTotal > 0)) return weights.map(() => 0);

  const exact = weights.map(weight => Math.max(0, totalCents * weight / weightTotal));
  const cents = exact.map(value => Math.floor(value));
  let remainder = totalCents - cents.reduce((sum, value) => sum + value, 0);
  const order = exact
    .map((value, index) => ({ index, fraction: value - Math.floor(value) }))
    .sort((a, b) => b.fraction - a.fraction || a.index - b.index);

  for (let index = 0; index < remainder && order.length > 0; index += 1) {
    cents[order[index % order.length].index] += 1;
  }
  return cents;
}

function getCustomAllocationResult() {
  const grandTotal = parseFloat(document.getElementById("tx-input-grand-total")?.value) || 0.0;
  const totalCents = Math.max(0, Math.round(grandTotal * 100));
  const rawValues = splitFriends.map(friend => customSplitInputs[friend] ?? "");
  let values = rawValues.map(value => (
    customSplitMode === "fraction" ? parseCustomSplitFraction(value) : parseCustomSplitNumber(value)
  ));
  if (customSplitMode === "ratio") {
    const shorthand = rawValues.find(value => String(value).includes(":"));
    if (shorthand) {
      const parts = String(shorthand).split(":").map(part => parseCustomSplitNumber(part));
      if (parts.length === splitFriends.length) values = parts;
    }
  }
  const hasInvalidInput = values.some(value => value === null);
  const inputTotal = values.reduce((sum, value) => sum + (value ?? 0), 0);
  let amountsCents = values.map(() => 0);
  let valid = !hasInvalidInput;
  let message = "";

  if (customSplitMode === "amount") {
    amountsCents = values.map(value => value === null ? 0 : Math.round(value * 100));
    const allocatedCents = amountsCents.reduce((sum, value) => sum + value, 0);
    if (hasInvalidInput) {
      valid = false;
      message = "Enter a valid amount for everyone.";
    } else if (Math.abs(allocatedCents - totalCents) > 1) {
      valid = false;
      message = `Amounts must add up to $${grandTotal.toFixed(2)}.`;
    }
  } else if (customSplitMode === "ratio") {
    if (inputTotal <= 0) {
      valid = false;
      message = "Enter a ratio for at least one person.";
    } else {
      amountsCents = allocateCustomSplitCents(totalCents, values.map(value => value || 0));
    }
    if (hasInvalidInput) {
      valid = false;
      message = "Enter a valid ratio for everyone.";
    }
  } else if (customSplitMode === "percentage") {
    if (Math.abs(Math.round(inputTotal * 100) - 10000) > 1) {
      valid = false;
      message = `Percentages must add up to 100% (currently ${inputTotal.toFixed(2)}%).`;
    } else {
      amountsCents = allocateCustomSplitCents(totalCents, values.map(value => value || 0));
    }
    if (hasInvalidInput) {
      valid = false;
      message = "Enter a valid percentage for everyone.";
    }
  } else {
    if (Math.abs(inputTotal - 1) > 0.0001) {
      valid = false;
      message = `Fractions must add up to 1 (currently ${inputTotal.toFixed(4)}).`;
    } else {
      amountsCents = allocateCustomSplitCents(totalCents, values.map(value => value || 0));
    }
    if (hasInvalidInput) {
      valid = false;
      message = "Enter a valid fraction for everyone, such as 1/2.";
    }
  }

  // Show a useful in-progress preview even while a percentage/fraction total is
  // being corrected, without allowing the invalid allocation to be saved.
  if (!valid && customSplitMode === "percentage") {
    amountsCents = values.map(value => value === null ? 0 : Math.round(totalCents * value / 100));
  } else if (!valid && customSplitMode === "fraction") {
    amountsCents = values.map(value => value === null ? 0 : Math.round(totalCents * value));
  }

  const amounts = {};
  splitFriends.forEach((friend, index) => {
    amounts[friend] = amountsCents[index] / 100;
  });
  return {
    valid,
    message,
    amounts,
    allocatedCents: amountsCents.reduce((sum, value) => sum + value, 0),
    inputTotal,
    rawValues,
    values,
  };
}

function formatCustomSplitInputNumber(value, digits = 4) {
  return String(Number(value.toFixed(digits)));
}

function seedCustomSplitInputs() {
  const grandTotal = parseFloat(document.getElementById("tx-input-grand-total")?.value) || 0.0;
  const totalCents = Math.max(0, Math.round(grandTotal * 100));
  const baseCents = splitFriends.length > 0 ? Math.floor(totalCents / splitFriends.length) : 0;
  const remainderCents = totalCents - (baseCents * splitFriends.length);
  const basePercentHundredths = splitFriends.length > 0 ? Math.floor(10000 / splitFriends.length) : 0;
  const percentRemainder = 10000 - (basePercentHundredths * splitFriends.length);

  splitFriends.forEach((friend, index) => {
    if (customSplitMode === "amount") {
      customSplitInputs[friend] = ((baseCents + (index < remainderCents ? 1 : 0)) / 100).toFixed(2);
    } else if (customSplitMode === "ratio") {
      customSplitInputs[friend] = "1";
    } else if (customSplitMode === "percentage") {
      customSplitInputs[friend] = ((basePercentHundredths + (index < percentRemainder ? 1 : 0)) / 100).toFixed(2);
    } else {
      customSplitInputs[friend] = `1/${splitFriends.length || 1}`;
    }
  });
}

function ensureCustomSplitAmounts() {
  const hasExistingInputs = splitFriends.some(friend => (
    Object.prototype.hasOwnProperty.call(customSplitInputs, friend)
  ));

  if (!hasExistingInputs && splitFriends.length > 0) {
    seedCustomSplitInputs();
  }
  splitFriends.forEach(friend => {
    if (!Object.prototype.hasOwnProperty.call(customSplitInputs, friend)) {
      customSplitInputs[friend] = customSplitMode === "amount" ? "0.00" : "0";
    }
  });
  Object.keys(customSplitInputs).forEach(friend => {
    if (!splitFriends.includes(friend)) delete customSplitInputs[friend];
  });

  const result = getCustomAllocationResult();
  customSplitAmounts = result.amounts;
  return result;
}

function autoAllocateCustomAmountRemainder() {
  if (customSplitMode !== "amount" || customSplitTouched.size === 0) return;

  const grandTotal = parseFloat(document.getElementById("tx-input-grand-total")?.value) || 0.0;
  const totalCents = Math.max(0, Math.round(grandTotal * 100));
  const fixedFriends = splitFriends.filter(friend => customSplitTouched.has(friend));
  const remainingFriends = splitFriends.filter(friend => !customSplitTouched.has(friend));
  if (remainingFriends.length === 0) return;

  const fixedValues = fixedFriends.map(friend => parseCustomSplitNumber(customSplitInputs[friend]));
  if (fixedValues.some(value => value === null)) return;

  const fixedCents = fixedValues.reduce((sum, value) => sum + Math.round(value * 100), 0);
  const remainingCents = Math.max(0, totalCents - fixedCents);
  const baseCents = Math.floor(remainingCents / remainingFriends.length);
  const remainderCents = remainingCents - (baseCents * remainingFriends.length);
  remainingFriends.forEach((friend, index) => {
    customSplitInputs[friend] = ((baseCents + (index < remainderCents ? 1 : 0)) / 100).toFixed(2);
  });
}

function syncCustomAmountInputValues() {
  splitFriends.forEach((friend, index) => {
    const input = document.getElementById(`split-custom-input-${index}`);
    if (input && input !== document.activeElement) {
      input.value = String(customSplitInputs[friend] ?? "");
    }
  });
}

function setCustomSplitMode(nextMode) {
  if (!Object.prototype.hasOwnProperty.call(CUSTOM_SPLIT_MODES, nextMode)) return;
  if (nextMode === customSplitMode) return;

  const previous = ensureCustomSplitAmounts();
  const previousAmounts = splitFriends.map(friend => Math.max(0, Number(previous.amounts[friend]) || 0));
  const totalCents = Math.max(0, Math.round((parseFloat(document.getElementById("tx-input-grand-total")?.value) || 0) * 100));
  customSplitMode = nextMode;
  customSplitInputs = {};
  customSplitTouched = new Set();

  if (totalCents === 0 || previousAmounts.every(amount => amount <= 0)) {
    seedCustomSplitInputs();
  } else if (nextMode === "amount") {
    splitFriends.forEach((friend, index) => {
      customSplitInputs[friend] = previousAmounts[index].toFixed(2);
    });
  } else if (nextMode === "ratio") {
    const positive = previousAmounts.filter(amount => amount > 0);
    const minimum = Math.min(...positive);
    const maximum = Math.max(...positive);
    splitFriends.forEach((friend, index) => {
      const amount = previousAmounts[index];
      const ratio = amount <= 0 ? 0 : (maximum / minimum < 1.005 ? 1 : amount / minimum);
      customSplitInputs[friend] = formatCustomSplitInputNumber(ratio);
    });
  } else if (nextMode === "percentage") {
    const values = previousAmounts.map(amount => amount * 100 / (totalCents / 100));
    values[values.length - 1] = Math.max(0, 100 - values.slice(0, -1).reduce((sum, value) => sum + Number(value.toFixed(2)), 0));
    splitFriends.forEach((friend, index) => {
      customSplitInputs[friend] = values[index].toFixed(2);
    });
  } else {
    splitFriends.forEach((friend, index) => {
      customSplitInputs[friend] = formatCustomSplitInputNumber(previousAmounts[index] / (totalCents / 100));
    });
  }

  const modeSelect = document.getElementById("split-custom-mode");
  if (modeSelect) modeSelect.value = customSplitMode;
  renderSplitWorkbench();
}

function updateCustomSplitInput(friendName, value) {
  customSplitInputs[friendName] = String(value ?? "");
  if (customSplitMode === "amount") {
    customSplitTouched.add(friendName);
    autoAllocateCustomAmountRemainder();
    syncCustomAmountInputValues();
  }
  const result = getCustomAllocationResult();
  customSplitAmounts = result.amounts;
  updateCustomSplitSummary(result);
  renderSplitCalculations();
}

function renderCustomSplitAmounts() {
  const section = document.getElementById("split-custom-amounts");
  const list = document.getElementById("split-custom-amount-list");
  if (!section || !list) return;

  section.style.display = isCustomSplit ? "" : "none";
  if (!isCustomSplit) return;
  ensureCustomSplitAmounts();
  const config = CUSTOM_SPLIT_MODES[customSplitMode] || CUSTOM_SPLIT_MODES.amount;
  const modeSelect = document.getElementById("split-custom-mode");
  const title = document.getElementById("split-custom-section-title");
  const hint = document.getElementById("split-custom-mode-hint");
  if (modeSelect) modeSelect.value = customSplitMode;
  if (title) title.textContent = config.title;
  if (hint) hint.textContent = config.hint;

  list.innerHTML = splitFriends.map((friend, index) => `
    <label class="split-custom-amount-row">
      <span class="split-custom-person">
        <span class="friend-avatar-dot">${escapeHtml(friend.charAt(0).toUpperCase())}</span>
        ${escapeHtml(friend)}
      </span>
      <span class="split-custom-input-wrap">
        ${config.prefix ? `<span>${config.prefix}</span>` : ""}
        <input id="split-custom-input-${index}" type="${config.inputType}" ${config.inputType === "number" ? 'min="0" step="0.01"' : ""}
          inputmode="${config.inputMode}" value="${escapeAttr(String(customSplitInputs[friend] ?? ""))}"
          placeholder="${config.placeholder}" oninput="updateCustomSplitInput('${escapeAttr(friend)}', this.value)"
          aria-label="${config.title} for ${escapeAttr(friend)}" />
        ${config.suffix ? `<span class="split-custom-suffix">${config.suffix}</span>` : ""}
      </span>
    </label>
  `).join("");
  updateCustomSplitSummary();
}

function updateCustomSplitSummary(result = null) {
  if (!isCustomSplit) return;
  const grandTotal = parseFloat(document.getElementById("tx-input-grand-total")?.value) || 0.0;
  const allocation = result || getCustomAllocationResult();
  customSplitAmounts = allocation.amounts;
  const allocated = allocation.allocatedCents / 100;
  const totalLabel = document.getElementById("split-custom-total-label");
  const remainingEl = document.getElementById("split-custom-remaining");

  let allocationLabel = `Allocated $${allocated.toFixed(2)} of $${grandTotal.toFixed(2)}`;
  if (customSplitMode === "ratio") {
    const ratioDisplay = allocation.values.map(value => value === null ? "?" : value).join(" : ");
    allocationLabel = `Ratio ${ratioDisplay} • ${allocationLabel}`;
  } else if (customSplitMode === "percentage") {
    allocationLabel = `Entered ${allocation.inputTotal.toFixed(2)}% • ${allocationLabel}`;
  } else if (customSplitMode === "fraction") {
    allocationLabel = `Entered ${allocation.inputTotal.toFixed(4)} of total • ${allocationLabel}`;
  }
  if (totalLabel) totalLabel.textContent = allocationLabel;
  if (remainingEl) {
    remainingEl.classList.toggle("balanced", allocation.valid);
    remainingEl.classList.toggle("over", !allocation.valid && allocation.allocatedCents > Math.round(grandTotal * 100) + 1);
    remainingEl.textContent = allocation.valid ? "✓ Fully allocated" : allocation.message;
  }
}

function renderItemAssignmentCards() {
  const container = document.getElementById("split-assignment-cards");
  const assignSec = document.getElementById("split-assignment-section");
  if (!container) return;

  if (isSplitEvenly || isCustomSplit) {
    if (assignSec) assignSec.style.display = "none";
    return;
  }
  if (assignSec) assignSec.style.display = "";

  if (detailLineItems.length === 0) {
    container.innerHTML = `<div style="font-size:0.75rem; color:#71717a;">Add items in Receipt tab first.</div>`;
    return;
  }

  container.innerHTML = detailLineItems.map((it, itIdx) => {
    const assigned = Array.isArray(it.assigned_to) && it.assigned_to.length > 0 ? it.assigned_to : splitFriends;
    const cost = it.price * (it.quantity || 1);

    return `
      <div class="split-item-card">
        <div class="split-item-meta">
          <span class="split-item-name">${it.quantity > 1 ? `${it.quantity}x ` : ''}${escapeHtml(it.name)}</span>
          <span class="split-item-cost">$${cost.toFixed(2)}</span>
        </div>
        <div class="split-assign-chips">
          ${splitFriends.map(f => {
            const isAssigned = assigned.includes(f);
            return `
              <button type="button" class="friend-toggle-chip ${isAssigned ? 'active' : ''}" onclick="toggleItemFriendAssignment(${itIdx}, '${escapeAttr(f)}')">
                ${escapeHtml(f)}
              </button>
            `;
          }).join("")}
        </div>
      </div>
    `;
  }).join("");
}

function toggleItemFriendAssignment(itemIdx, friendName) {
  const item = detailLineItems[itemIdx];
  if (!item) return;

  let assigned = Array.isArray(item.assigned_to) ? [...item.assigned_to] : [...splitFriends];
  if (assigned.includes(friendName)) {
    if (assigned.length > 1) {
      assigned = assigned.filter(f => f !== friendName);
    }
  } else {
    assigned.push(friendName);
  }
  item.assigned_to = assigned;
  renderSplitWorkbench();
}

function renderSplitCalculations() {
  const grid = document.getElementById("split-summary-grid");
  const previewTextarea = document.getElementById("split-formatted-preview");
  if (!grid) return;

  const svcPct = parseFloat(document.getElementById("tx-input-svc-pct")?.value) || 0.0;
  const taxPct = parseFloat(document.getElementById("tx-input-tax-pct")?.value) || 0.0;
  const discount = parseFloat(document.getElementById("tx-input-discount")?.value) || 0.0;
  const inclusive = document.getElementById("tx-input-total-inclusive")?.checked ?? isTotalInclusive;

  let breakdown = [];
  const grandTotal = parseFloat(document.getElementById("tx-input-grand-total")?.value) || 0.0;

  if (isCustomSplit && splitFriends.length > 0) {
    ensureCustomSplitAmounts();
    breakdown = splitFriends.map(friend => {
      const amount = Number(customSplitAmounts[friend]) || 0.0;
      return {
        name: friend,
        subtotal: amount,
        service_charge: 0,
        tax: 0,
        discount: 0,
        total: amount,
        items: [{ name: "Custom share", share_price: amount }],
      };
    });
  } else if (isSplitEvenly && splitFriends.length > 0) {
    const totalCents = Math.max(0, Math.round(grandTotal * 100));
    const baseCents = Math.floor(totalCents / splitFriends.length);
    const remainderCents = totalCents - (baseCents * splitFriends.length);
    breakdown = splitFriends.map((f, index) => {
      const share = (baseCents + (index < remainderCents ? 1 : 0)) / 100;
      return {
        name: f,
        subtotal: share,
        service_charge: 0,
        tax: 0,
        discount: 0,
        total: share,
        items: [{ name: "Equal Split", share_price: share }],
      };
    });
  } else {
    const friendSubtotals = {};
    const friendItems = {};
    splitFriends.forEach(f => {
      friendSubtotals[f] = 0.0;
      friendItems[f] = [];
    });

    detailLineItems.forEach(it => {
      const price = it.price * (it.quantity || 1);
      const assigned = (it.assigned_to && it.assigned_to.length > 0)
        ? it.assigned_to.filter(f => splitFriends.includes(f))
        : splitFriends;
      const validAssigned = assigned.length > 0 ? assigned : splitFriends;
      // Allocate item cents before calculating totals so the displayed shares
      // cannot lose a cent on values such as $37.05 / 2.
      const priceCents = Math.max(0, Math.round(price * 100));
      const baseCents = Math.floor(priceCents / validAssigned.length);
      const remainderCents = priceCents - (baseCents * validAssigned.length);

      validAssigned.forEach((f, index) => {
        const share = (baseCents + (index < remainderCents ? 1 : 0)) / 100;
        friendSubtotals[f] = (friendSubtotals[f] || 0) + share;
        friendItems[f].push({
          name: it.name,
          share_price: share,
          is_shared: validAssigned.length > 1,
        });
      });
    });

    const totalSub = Object.values(friendSubtotals).reduce((a, b) => a + b, 0.0) || 1.0;

    breakdown = splitFriends.map(f => {
      const sub = friendSubtotals[f] || 0.0;
      const ratio = sub / totalSub;
      const svc = inclusive ? 0.0 : sub * (svcPct / 100.0);
      const tax = inclusive ? 0.0 : (sub + svc) * (taxPct / 100.0);
      const disc = discount * ratio;
      const friendTot = Math.max(0, sub + svc + tax - disc);

      return {
        name: f,
        subtotal: sub,
        service_charge: svc,
        tax: tax,
        discount: disc,
        total: friendTot,
        items: friendItems[f] || [],
      };
    });
  }

  // Reconcile rounded person totals to the displayed grand total. This keeps
  // the sum of visible shares equal to the amount the user is splitting.
  if (breakdown.length > 0 && !isCustomSplit) {
    const targetCents = Math.max(0, Math.round(grandTotal * 100));
    const visibleCents = breakdown.reduce((sum, person) => sum + Math.round(person.total * 100), 0);
    const remainderCents = targetCents - visibleCents;
    if (remainderCents) {
      const last = breakdown[breakdown.length - 1];
      last.total = (Math.round(last.total * 100) + remainderCents) / 100;
    }
  }

  // Render individual summary cards
  grid.innerHTML = breakdown.map(b => {
    const isPaid = splitPaidStatus[b.name] === true;
    const initial = b.name.charAt(0).toUpperCase();

    return `
      <div class="split-person-card">
        <div class="split-person-header">
          <div class="split-person-name-wrap">
            <div class="friend-avatar-dot">${initial}</div>
            <span>${escapeHtml(b.name)}</span>
          </div>
          <button type="button" class="split-paid-toggle ${isPaid ? 'paid' : ''}" onclick="toggleFriendPaidStatus('${escapeAttr(b.name)}')">
            ${isPaid ? '🟢 Paid' : '🟡 Pending'}
          </button>
        </div>
        <div class="split-person-total">$${b.total.toFixed(2)}</div>
        <div class="split-person-subtext">
          Sub: $${b.subtotal.toFixed(2)} ${b.service_charge > 0 ? `+ Svc $${b.service_charge.toFixed(2)}` : ''} ${b.tax > 0 ? `+ Tax $${b.tax.toFixed(2)}` : ''}
        </div>
      </div>
    `;
  }).join("");

  // Generate copyable WhatsApp/Telegram summary
  if (previewTextarea) {
    const merchantName = document.getElementById("tx-detail-input-merchant")?.value || "Dining Bill";
    let msg = `🧾 *${merchantName} Bill Split*\n`;
    msg += `💰 Grand Total: $${grandTotal.toFixed(2)}\n`;
    msg += `─────────────────────────\n`;

    breakdown.forEach(b => {
      const statusIcon = splitPaidStatus[b.name] ? "✅" : "⏳";
      msg += `👤 *${b.name}*: $${b.total.toFixed(2)} ${statusIcon}\n`;
      if (b.items && b.items.length > 0) {
        b.items.forEach(it => {
          msg += `   • ${it.name} ($${it.share_price.toFixed(2)}${it.is_shared ? ' shared' : ''})\n`;
        });
      }
      if (b.service_charge > 0 || b.tax > 0) {
        msg += `   • Tax/Svc: +$${(b.service_charge + b.tax).toFixed(2)}\n`;
      }
      msg += `\n`;
    });

    msg += `💸 PayNow to: ${getUserId() || "Mobile / QR"}\n`;
    msg += `✨ Shared via Nexus Prime`;
    previewTextarea.value = msg;
  }
}

async function toggleFriendPaidStatus(friendName) {
  if (friendName === "Me" || splitPaidStatus[friendName]) return;
  if (activeDetailExpense?.id && typeof window.settleUnifiedIou === "function") {
    const settled = await window.settleUnifiedIou(
      `out-${String(activeDetailExpense.id).padStart(6, "0")}`,
      friendName,
    );
    if (settled) {
      splitPaidStatus[friendName] = true;
      activeDetailExpense.split_data = {
        ...(activeDetailExpense.split_data || {}),
        paid_status: splitPaidStatus,
      };
      renderSplitCalculations();
    }
    return;
  }
  splitPaidStatus[friendName] = true;
  renderSplitCalculations();
}

async function saveTransactionDetails() {
  if (!activeDetailExpense) return;

  const merchant = document.getElementById("tx-detail-input-merchant")?.value || activeDetailExpense.merchant;
  const category = document.getElementById("tx-detail-input-category")?.value || activeDetailExpense.category;
  const grandTotal = parseFloat(document.getElementById("tx-input-grand-total")?.value) || activeDetailExpense.amount;
  const svcPct = parseFloat(document.getElementById("tx-input-svc-pct")?.value) || 0.0;
  const taxPct = parseFloat(document.getElementById("tx-input-tax-pct")?.value) || 0.0;
  const discount = parseFloat(document.getElementById("tx-input-discount")?.value) || 0.0;

  if (isCustomSplit) {
    const allocation = ensureCustomSplitAmounts();
    if (!allocation.valid) {
      updateCustomSplitSummary();
      showToast(allocation.message, "danger");
      return;
    }
  }

  const splitData = {
    friends: splitFriends,
    paid_status: splitPaidStatus,
    is_even: isSplitEvenly,
    svc_pct: svcPct,
    tax_pct: taxPct,
    discount: discount,
    total_inclusive: isTotalInclusive,
    split_mode: isCustomSplit ? "custom" : (isSplitEvenly ? "even" : "items"),
    custom_amounts: isCustomSplit ? { ...customSplitAmounts } : null,
    share_amounts: isCustomSplit ? { ...customSplitAmounts } : null,
    custom_allocation_mode: isCustomSplit ? customSplitMode : null,
    custom_allocations: isCustomSplit ? { ...customSplitInputs } : null,
    // Keep the gross bill auditable even when the personal share is smaller.
    gross_total: grandTotal,
    my_share: isCustomSplit ? (Number(customSplitAmounts.Me) || 0) : null,
  };

  try {
    const res = await fetch(getApiUrl(`/api/dashboard/expenses/${activeDetailExpense.id}/details`), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        merchant: merchant,
        category: category,
        amount: grandTotal,
        receipt_items: detailLineItems,
        split_data: splitData,
      }),
    });

    if (!res.ok) throw new Error("Failed to save transaction details");
    showToast("💾 Saved transaction items and bill split!");
    closeTransactionDetailsModal();
    loadDashboardSummary();
    loadExpensesTable(activeCategoryFilter, activeSearchQuery, activeSortMode);

  } catch (err) {
    console.error("Save details error:", err);
    showToast("⚠️ Could not save changes. Please try again.");
  }
}
