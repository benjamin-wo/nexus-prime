import { createContext, useContext } from "react";

/** Where the docked chat is drawn: the Shell's chat column, once it is on the page. Null when the chat is
 * a drawer (it then goes to the page's body). */
export const ChatSlotContext = createContext<HTMLElement | null>(null);

export const useChatSlot = () => useContext(ChatSlotContext);
