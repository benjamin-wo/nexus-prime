import { api } from "./core";

export type Money = { amount: string; currency: string };
/** What a person logs by hand: money in or money out. */
export type Direction = "in" | "out";
/** What a ledger row can be: a move is money between two of the user's own wallets,
 * never spending and never income. */
export type TxDirection = Direction | "move";

export type WalletKind = "spending" | "investment" | "savings" | "card" | "other" | "cash";
export type CardNetwork = "visa" | "mastercard" | "amex" | "other";
/** A named place money sits (a label; no balance is kept). A card also has its bank, product,
 * network and last four digits (all optional), and one wallet at a time can be the usual card. */
export type Wallet = {
  id: string;
  name: string;
  kind: WalletKind;
  match_words: string[];
  issuer?: string | null;
  product?: string | null;
  network?: CardNetwork | null;
  /** Four digits, never more. */
  last4?: string | null;
  /** The wallet an expense is paid with when none is said. */
  usual?: boolean;
  /** Said by the server when more than four digits were sent and only the last four were kept. */
  note?: string;
};
/** A wallet as a transaction names it. */
export type WalletRef = { id: string; name: string; kind: WalletKind };
/** What paid for an expense. */
export type PaidWith = { id: string; name: string; kind: WalletKind; last4: string | null };
/** What a wallet paid for in a month. */
export type WalletSpend = { month: string; total: Money; count: number };

/** A foreign amount in the home currency; amount is null when no rate was available. */
export type HomeAmount = { amount: Money | null; rate: string | null; rate_date: string | null };

export type Transaction = {
  id: string;
  direction: TxDirection;
  amount: Money;
  /** A move only: where the money left and where it went (null for money in and out). */
  from_wallet?: WalletRef | null;
  to_wallet?: WalletRef | null;
  /** Money out only: the card, Spending, Cash or other wallet that paid. */
  paid_with?: PaidWith | null;
  /** A move only: what arrived, when that isn't `amount`. */
  received?: Money | null;
  /** Set on listings for rows not in the home currency. */
  home?: HomeAmount | null;
  occurred_at: string;
  counterparty: string | null;
  category_id: string | null;
  /** The rule that chose the category, if one did. */
  category_rule_id?: string | null;
  notes: string | null;
  status: "confirmed" | "pending";
  source: string;
  deleted: boolean;
  /** A receipt is kept for it; open it at receiptUrl(id). */
  has_receipt?: boolean;
  /** A bill shared with others: the user's share and each person's. */
  split?: { own_share: Money; people: { name: string; share: Money; repaid: Money }[] } | null;
  /** Repayments linking it to other transactions: for a bill, the money in that
   * paid part of it back; for money in, the bill it paid back. */
  links?: { transaction_id: string; counterparty: string | null; occurred_at: string; name: string; amount: Money }[];
  /** The user's own money in it, when friends paid part of it back. */
  own?: Money | null;
  /** Set on listings: another transaction that looks like the same payment. */
  duplicate?: { transaction_id: string; counterparty: string | null; occurred_at: string; amount: Money } | null;
};

/** The receipt's short-lived link; the server checks it's the owner asking. */
export const receiptUrl = (id: string) => `/api/transactions/${id}/receipt`;

/** Offered after a category correction; nothing changes unless the user accepts. */
export type RuleSuggestion = {
  question: string;
  pattern: string;
  category_id: string;
  replaces_category_id: string | null;
};
export type EditedTransaction = Transaction & { rule_suggestion?: RuleSuggestion | null };
export type CategoryRule = {
  id: string;
  pattern: string;
  category_id: string;
  category_name: string;
  explanation: string;
};

export type Memory = {
  id: string;
  kind: "fact" | "preference" | "episode";
  text: string;
  happened_on: string | null;
  updated_at: string;
};

export type ImportLayout = {
  date: number;
  description: number[];
  amount: number | null;
  debit: number | null;
  credit: number | null;
  currency: number | null;
  date_order: "dmy" | "mdy" | "ymd";
  sign: "negative_is_out" | "positive_is_out";
};
export type ImportRow = {
  index: number;
  verdict: "new" | "duplicate" | "imported" | "unclear";
  cells: string[];
  date: string | null;
  description: string;
  amount: string | null;
  currency: string | null;
  direction: "in" | "out" | null;
  category: string | null;
  problem: string | null;
  matches: { date: string; description: string | null; amount: string } | null;
  /** Proposed as a move because the description names a wallet: money out goes from Spending
   * to `move_to`; money in comes from `move_from`. Both null for an ordinary entry. */
  move_to?: Wallet | null;
  move_from?: Wallet | null;
};
export type ImportPreview = {
  headers: string[];
  layout: ImportLayout | null;
  saved_as: string | null;
  rows: ImportRow[];
};
export type ImportRecord = {
  id: string;
  file_name: string;
  added: number;
  created_at: string;
  undone_at: string | null;
  skipped?: number;
};

export type Page = { items: Transaction[]; total: number };
export type Category = { id: string; name: string };
export type TimezoneSource = "home" | "phone" | "chat" | "trip";
export type Me = {
  user: {
    telegram_user_id: number;
    role: "owner" | "member" | "guest";
    home_currency: string;
    /** The zone Nexus uses for "today" right now; it follows the person (see `timezone_source`). */
    timezone: string;
    /** Where they live; kept when `timezone` moves, and what "Use home time" goes back to. */
    home_timezone?: string;
    /** What set `timezone`: their home, their phone, something they said in chat or Settings, or a trip. */
    timezone_source?: TimezoneSource;
    /** When `timezone` was last set (ISO); null while it is still their home. */
    timezone_set_at?: string | null;
    /** Their Telegram first name and last initial ("Alex T."), as other people on a trip see them. */
    display_name?: string | null;
    /** Whether a Telegram chat is linked, so the bot can message them. A demo has none. */
    telegram_linked?: boolean;
  };
  csrf_token: string;
  /** Set by a sign-in that added the person to a trip with a trip invite. */
  joined_trip?: string | null;
  /** Set while this is the public demo account (made-up data, ends at `expires_at`); null for a real user. */
  demo?: Demo | null;
  /** `show_invest`, `show_travel` and `show_health`: whether Invest, Travel and Health are in the menu. Null is not decided
   * (hidden; chat turns it on the first time it is used), false is switched off. */
  preferences?: { track_cards: boolean; show_invest?: boolean | null; show_travel?: boolean | null; show_health?: boolean | null };
};
export type Demo = { expires_at: string; messages_left: number };
/** The answer to the two time zone writes: the same fields as `/me`, and whether the zone moved. */
export type TimezoneChange = Me & { changed: boolean };

/** Tells Nexus where the person is. "phone" is the browser's own zone, reported on start;
 * "manual" is a zone they picked in Settings. An unknown zone is a 422. */
export function setTimezone(timezone: string, source: "phone" | "manual"): Promise<TimezoneChange> {
  return api<TimezoneChange>("/me/timezone", { method: "POST", body: { timezone, source } });
}

/** Puts the current zone back to their home zone. */
export function goHomeTimezone(): Promise<TimezoneChange> {
  return api<TimezoneChange>("/me/timezone/home", { method: "POST" });
}
export type Summary = {
  start: string;
  end: string;
  /** Every total is in this (home) currency; foreign amounts are converted at their day's rate. */
  currency: string;
  totals: { direction: Direction; total: Money; count: number; converted: Money[]; unconverted: Money[] }[];
  by_category: { category_id: string | null; category_name: string | null; total: Money; count: number }[];
  /** Net moved into savings and investment wallets over the period (home currency). */
  put_away?: Money;
  /** put_away / money in (0.24 is 24%); null without money in. */
  saving_rate?: number | null;
  /** Spending, plus moved from Spending to anything but a card. */
  total_out?: Money;
};
/** Money out per month for the chart on the Accounting overview (and last month by this date, for Home), oldest first, ending with this month so far. */
export type Spending = {
  currency: string;
  months: { month: string; spent: Money; to_date: boolean }[];
  last_month_to_date: Money;
  budget: Money | null;
};
export type Iou = {
  split_id: string;
  transaction_id: string;
  participant_name: string;
  share: Money;
  outstanding: Money;
  expense_occurred_at: string;
};
export type Budget = {
  id: string;
  category_id: string | null;
  name: string;
  limit: Money;
  spent: Money;
  remaining: Money;
  percent: number;
  unconverted: Money[];
};
/** How this month stands against what's coming: the figures behind "left to spend". */
export type BudgetMonth = {
  currency: string;
  /** Spending so far, plus moves from Spending to your wallets. */
  total_out: Money;
  /** This month's income less total out and what's still due. */
  left_to_spend: Money;
  /** Bills, subscriptions, trip set-asides and scheduled moves still to come this month. */
  still_due_out: Money;
  income: Money;
  /** The overall budget less spending so far; null without one. */
  budget_left: Money | null;
  /** Still-due bills that are spending, and subscriptions: they'll count against the budget. */
  spending_due: Money;
  /** budget_left less spending_due, so negative when the budget will be overspent; null without one. */
  budget_left_after_due: Money | null;
  /** Whichever of budget_left_after_due and left_to_spend is lower; null without an overall budget. */
  tighter: "budget" | "left_to_spend" | null;
  plan_warning: string | null;
  /** Scheduled items left out for want of an amount or a rate. */
  skipped: string[];
};
export type Bill = {
  id: string;
  name: string;
  /** Marking it paid logs an expense; false for money moved, not spent (it's marked done). */
  spending: boolean;
  /** A scheduled move's destination; null on spending and on a payment not linked yet. */
  wallet: WalletRef | null;
  amount: Money | null;
  cadence: "once" | "weekly" | "monthly" | "yearly";
  due: string;
  days_until: number;
  snoozed: boolean;
};
export type Salary = {
  rule: "monthly_day" | "last_weekday" | "biweekly";
  day: number | null;
  anchor: string | null;
  description: string;
  usual: Money | null;
  /** Who pays the salary (the employer), put on the salary entries logged without a name. */
  payer: string | null;
  /** Earlier salaries with no name that `POST /salary/name-earlier` would put the payer on. */
  unnamed_salaries: number;
  next_payday: string;
  days_until: number;
};
export type EmailStatus = "pending" | "logged" | "skipped" | "not_receipt" | "no_amount" | "duplicate" | "failed";
export type InboundEmail = {
  id: string;
  received_at: string;
  sender: string;
  subject: string;
  status: EmailStatus;
  reason: string | null;
  amount: string | null;
  currency: string | null;
  merchant: string | null; // who was paid; for money received, who sent it
  received: boolean; // money in, not money spent
  transaction_id: string | null;
  actionable: boolean;
  /** The payment it looks like a second record of, while it waits. */
  duplicate_of?: string | null;
  /** The wallet it names, while it waits: it may have been a move there (or from there). */
  move_wallet_id?: string | null;
  move_wallet?: string | null;
};
/** An entry that may really have been a move; nothing changes until the user says so. */
export type LikelyMove = { transaction: Transaction; wallet: Wallet | null; reason: string };
export type EmailConnection = {
  id: string;
  provider: "gmail" | "forward";
  address: string;
  status: "active" | "broken";
  last_checked: string | null;
  last_received: string | null;
};
export type EmailOverview = {
  available: boolean;
  forwarding_available: boolean;
  connections: EmailConnection[];
  emails: InboundEmail[];
};
export type Expected = {
  kind: "bill" | "subscription" | "salary" | "trip";
  name: string;
  direction: "in" | "out";
  amount: Money | null;
  home: Money | null;
};
export type CashDay = {
  day: string;
  money_in: Money;
  money_out: Money;
  net: Money;
  expected: Expected[];
  expected_net: Money;
};
export type CashFlow = {
  start: string;
  end: string;
  today: string;
  currency: string;
  days: CashDay[];
  logged_in: Money;
  logged_out: Money;
  expected_in: Money;
  expected_out: Money;
  unknown_amounts: number;
  unconverted: Money[];
};
export type Subscription = {
  id: string;
  name: string;
  cadence: "weekly" | "monthly" | "yearly";
  amount: Money;
  monthly: Money;
  last_charged_on: string;
  next_charge: string;
  previous_amount: Money | null;
  price_changed_on: string | null;
};
export type Subscriptions = { tracked: Subscription[]; proposed: Subscription[]; monthly_totals: Money[] };
export type Frequency = "instant" | "hourly" | "thrice_daily" | "daily" | "off";
export type Updates = {
  frequency: Frequency;
  /** HH:MM, local time: when the daily summary goes. */
  daily_at: string;
  description: string;
  options: Record<Frequency, string>;
  /** HH:MM, local time. Nothing is sent between quiet_start and quiet_end (it may cross
   * midnight), except an urgent stop on a stock held; the same time twice means no quiet hours. */
  quiet_start: string;
  quiet_end: string;
  /** A stock moving this much (%) in a day is a big move worth a message: 1 to 20. */
  move_alert_percent: string;
  /** The 08:00 summary of how the US market did, on a morning after a trading day. */
  market_summary: boolean;
  /** Messages a day (3 to 20) before the rest wait for a digest. An urgent message, one with
   * buttons and the summaries the user timed don't count. */
  daily_cap: number;
};
/** How urgent a message to the user on Telegram is: urgent goes at once, now unless it is
 * quiet hours or the day's cap is used up, digest only in a digest. */
export type NotificationLevel = "urgent" | "now" | "digest";
/** What became of it: sent, held for quiet hours or the next digest, told in a digest, or
 * dropped (no Telegram chat to tell). */
export type NotificationStatus = "sent" | "held" | "digested" | "dropped";
/** One message Nexus meant to send the user on Telegram, kept for 30 days (GET
 * /notifications/history, newest first). */
export type NotificationEntry = {
  id: string;
  /** Short and stable, such as budget_alert or bill_reminder. */
  kind: string;
  level: NotificationLevel;
  text: string;
  /** A web path that opens what it is about. */
  link: string | null;
  status: NotificationStatus;
  created_at: string;
  /** When it went, alone or in a digest. */
  sent_at: string | null;
  held_until: string | null;
};
/** Whether the user is told on Telegram when someone else changes a trip they share. */
export type TripAlerts = { enabled: boolean };
/** How Nexus words its replies (GET and PUT /settings/voice). Only wording: never what Nexus can do. */
export type VoicePresetId = "default" | "chill" | "direct" | "hype" | "cheeky";
export type VoiceEmoji = "none" | "some" | "lots";
export type VoiceLength = "short" | "normal" | "detailed";
export type VoiceHumour = "off" | "light" | "playful";
export type VoiceDials = { emoji: VoiceEmoji; length: VoiceLength; humour: VoiceHumour };
export type VoicePreset = { id: VoicePresetId; label: string; blurb: string } & VoiceDials;
export type VoiceSettings = VoiceDials & { preset: VoicePresetId; note: string | null; presets: VoicePreset[] };
/** Any of these may be sent; "" clears the note. Changing the preset alone resets the dials to its defaults. */
export type VoiceUpdate = Partial<VoiceDials & { preset: VoicePresetId; note: string }>;
/** A view Prime puts in the chat as a card (ADR 0005): the caption and headline figures are built on the server. */
export type ViewShow = {
  view_id: string;
  kind: string;
  params: Record<string, unknown>;
  focus: boolean;
  caption: string;
  summary: Record<string, unknown> | null;
};
export type Reply = { text: string; buttons: { label: string; data: string }[][]; views?: ViewShow[] };
/** A view kept with a reply in the history: kind, params and focus, never figures. */
export type StoredView = { kind: string; params: Record<string, unknown>; focus: boolean };
/** The running chat as the user saw it, oldest first; notifications aren't part of it. */
export type ChatHistory = {
  lines: {
    id: number;
    role: "user" | "nexus";
    text: string;
    channel: string | null;
    at: string;
    views?: StoredView[];
  }[];
  more: boolean;
  pending: Reply | null;
};

export type LedgerFilters = {
  direction?: TxDirection;
  status?: "pending" | "confirmed";
  search?: string;
  start?: string;
  end?: string;
  category_id?: string;
  uncategorized?: boolean;
  /** A wallet id, or "none" for entries with no card set. */
  paid_with?: string;
};

export function ledgerParams(filters: LedgerFilters, extra: Record<string, string | number> = {}): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries({ ...filters, ...extra })) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  return params.toString();
}

/** One thing a department is waiting on the user for, on Home. */
export type FeedItem = {
  department: string;
  kind: string;
  text: string;
  link: string;
  urgent: boolean;
  /** How soon it needs the user, and the order the list comes in: "now" (urgent), "today" (about something today), then "soon". */
  when: "now" | "today" | "soon";
  /** Buttons that settle the item; `path` is relative to /api. */
  actions: FeedAction[];
};
export type FeedAction = {
  key: string;
  label: string;
  method: string;
  path: string;
  /** The JSON to send with it; null when the endpoint takes none. */
  body?: unknown;
};

/** One step of Home's setup checklist. */
export type SetupItem = {
  key: "payday" | "receipts" | "investments" | "budget";
  label: string;
  done: boolean;
  /** The page where it is done. */
  link: string;
  /** A sentence the web can send to the chat to do it there. */
  ask: string;
};
/** `GET /api/setup`. Once `dismissed`, the checklist is put away (the items still come, for the same data). */
export type Setup = { dismissed: boolean; items: SetupItem[] };

/** A department's long piece of work, saved step by step. */
export type Run = {
  id: string;
  department: string;
  kind: string;
  title: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  progress: string;
  steps_done: number;
  steps_total: number;
  result: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
};
