import { Button } from "../components/ui";

/** On a phone, after a card's Open closed the chat: a slim bar on the page that opens it again where it was. */
export function BackToChat({ onBack }: { onBack: () => void }) {
  return (
    <div className="back-to-chat">
      <Button variant="text" onClick={onBack}>
        ← Back to chat
      </Button>
    </div>
  );
}
