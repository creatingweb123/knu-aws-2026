import { createContext, useContext } from 'react';

export type ShowToast = (message: string) => void;

export const ToastContext = createContext<ShowToast | null>(null);

/** 짧은 안내 메시지를 띄운다. ToastProvider 안에서 쓴다 */
export function useToast(): ShowToast {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast는 ToastProvider 안에서 써야 해요.');
  return ctx;
}
