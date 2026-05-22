import { useEffect, useState } from "react";

/**
 * Returns a Date that updates every `intervalMs`. Use for wall-clock
 * displays + "Xs ago" indicators. Cleans up on unmount.
 */
export function useNow(intervalMs: number = 1000): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}
