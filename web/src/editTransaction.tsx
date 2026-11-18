import { createContext, type ReactNode, useContext } from "react";

import type { Transaction } from "./api";

/** How a list of transactions anywhere in the app opens the edit sheet. The app provides it once;
 * where there is none (a guest, a test) the lists just read, as before. */
const EditTransaction = createContext<((tx: Transaction) => void) | null>(null);

export function EditTransactionProvider({ onEdit, children }: { onEdit: (tx: Transaction) => void; children: ReactNode }) {
  return <EditTransaction.Provider value={onEdit}>{children}</EditTransaction.Provider>;
}

export const useEditTransaction = () => useContext(EditTransaction);
