import { create } from "zustand";

export type ToastVariant = "success" | "error" | "warning" | "info";

export interface Toast {
  id: number;
  variant: ToastVariant;
  message: string;
}

interface ToastState {
  toasts: Toast[];
  /** Push a toast; returns its id. ttlMs <= 0 makes it sticky. */
  add: (variant: ToastVariant, message: string, ttlMs?: number) => number;
  remove: (id: number) => void;
  clear: () => void;
}

// Newest toasts pushed to the end; cap the stack so a burst of errors can't
// paper over the screen.
const MAX_TOASTS = 4;
const DEFAULT_TTL = 5_000;

let _seq = 0;

export const useToastStore = create<ToastState>((set, get) => ({
  toasts: [],
  add: (variant, message, ttlMs = DEFAULT_TTL) => {
    const id = ++_seq;
    set((s) => ({ toasts: [...s.toasts, { id, variant, message }].slice(-MAX_TOASTS) }));
    if (ttlMs > 0) {
      // setTimeout id isn't tracked — remove() is a no-op if already gone.
      setTimeout(() => get().remove(id), ttlMs);
    }
    return id;
  },
  remove: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
  clear: () => set({ toasts: [] }),
}));

/**
 * Imperative API for non-component callers (react-query mutation
 * onSuccess/onError, plain functions). Mirrors react-hot-toast's `toast.*`
 * so call sites stay terse: `toast.error(message)`.
 */
export const toast = {
  success: (message: string, ttlMs?: number) =>
    useToastStore.getState().add("success", message, ttlMs),
  error: (message: string, ttlMs?: number) =>
    useToastStore.getState().add("error", message, ttlMs),
  warning: (message: string, ttlMs?: number) =>
    useToastStore.getState().add("warning", message, ttlMs),
  info: (message: string, ttlMs?: number) =>
    useToastStore.getState().add("info", message, ttlMs),
};
