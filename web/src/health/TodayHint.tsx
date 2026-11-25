import { Row, RowList } from "../components/ui";

/** The first thing on Today: most logging happens in chat, so this opens it. */
export function TodayHint({ onOpenChat }: { onOpenChat?: () => void }) {
  return (
    <RowList aria-label="Log by chat">
      <Row title="Snap your food or tell Nexus what you ate." label="Open chat" onClick={onOpenChat} />
    </RowList>
  );
}
