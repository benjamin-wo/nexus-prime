import type { Money } from "./money";

/** Someone paid (or paying) before, suggested on the entry form from the user's own ledger. */
export type MerchantSuggestion = {
  name: string;
  category_id: string | null;
  category: string | null;
  /** The amount usually paid. */
  amount: Money;
  times: number;
  last_on: string;
};

/** Signing in from the iOS app: POST /auth/device, then GET /auth/device/{poll_id} until approved. */
export type DeviceStart = { code: string; poll_id: string; expires_in: number; bot_username: string };
export type DevicePoll = { status: "pending" } | { status: "approved"; login_path: string };
