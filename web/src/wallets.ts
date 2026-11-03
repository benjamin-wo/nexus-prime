import type { CardNetwork, Wallet, WalletKind } from "./api";

/** The kinds of wallet that can pay for an expense. Investment and savings wallets only
 * ever receive money, so they are never offered as "Paid with". */
const PAYING_KINDS: WalletKind[] = ["card", "spending", "cash", "other"];

export const canPay = (wallet: Pick<Wallet, "kind">): boolean => PAYING_KINDS.includes(wallet.kind);

/** The wallets to offer as "Paid with": cards first, then Spending, Cash and the others, each in
 * the order given. */
export function payingWallets<W extends Pick<Wallet, "kind">>(wallets: W[]): W[] {
  return PAYING_KINDS.flatMap((kind) => wallets.filter((w) => w.kind === kind));
}

/** A wallet as the person reads it: "Citi PremierMiles ·· 4321", or just the name without a card number. */
export function walletLabel(wallet: { name: string; last4?: string | null }): string {
  return wallet.last4 ? `${wallet.name} ·· ${wallet.last4}` : wallet.name;
}

/** Only the last four digits of a card number are kept. Anything typed or pasted into the
 * Last 4 digits box is cut down to its digits, then to the last four; `trimmed` says that
 * digits were dropped. */
export function keepLast4(text: string): { value: string; trimmed: boolean } {
  const digits = text.replace(/\D/g, "");
  return { value: digits.slice(-4), trimmed: digits.length > 4 };
}

export const LAST4_NOTE = "Only the last 4 digits are kept.";

export const NETWORKS: { key: CardNetwork; label: string }[] = [
  { key: "visa", label: "Visa" },
  { key: "mastercard", label: "Mastercard" },
  { key: "amex", label: "American Express" },
  { key: "other", label: "Other" },
];

/** A card's details as the form holds them. */
export type CardDetails = { issuer: string; product: string; network: CardNetwork | ""; last4: string };
export const NO_DETAILS: CardDetails = { issuer: "", product: "", network: "", last4: "" };

/** What the API is sent for a card; a blank box clears the field. */
export const detailsBody = (d: CardDetails) => ({
  issuer: d.issuer.trim() || null,
  product: d.product.trim() || null,
  network: d.network || null,
  last4: d.last4 || null,
});
