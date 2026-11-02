/** How long a demo has left, as the banner says it: "23 h", "42 min", or "a moment" once it is up. */
export function timeLeft(expiresAt: string, now: number = Date.now()): string {
  const ms = Date.parse(expiresAt) - now;
  if (!Number.isFinite(ms) || ms <= 0) return "a moment";
  const minutes = Math.ceil(ms / 60_000);
  if (minutes < 60) return `${minutes} min`;
  return `${Math.floor(minutes / 60)} h`;
}

/** "5 messages left", "1 message left". */
export function messagesLeft(count: number): string {
  const n = Math.max(0, count);
  return `${n} ${n === 1 ? "message" : "messages"} left`;
}
