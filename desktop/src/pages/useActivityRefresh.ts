import { useCallback, useEffect, useRef } from "react";

type Refresh = () => Promise<void>;

type Waiter = {
  target: number;
  resolve: () => void;
};

/**
 * Serializes refreshes while a retained page is visible. Requests received
 * while hidden stay dirty until the next activation.
 */
export function useActivityRefresh(active: boolean, refresh: Refresh): (waitForCompletion?: boolean) => Promise<void> {
  const activeRef = useRef(active);
  const mountedRef = useRef(false);
  const refreshRef = useRef(refresh);
  const requestedRef = useRef(1);
  const completedRef = useRef(0);
  const refreshingRef = useRef(false);
  const waitersRef = useRef<Waiter[]>([]);
  const drainRef = useRef<() => void>(() => {});

  activeRef.current = active;
  refreshRef.current = refresh;

  const settleThrough = (target: number): void => {
    const remaining: Waiter[] = [];
    for (const waiter of waitersRef.current) {
      if (waiter.target <= target) waiter.resolve();
      else remaining.push(waiter);
    }
    waitersRef.current = remaining;
  };

  drainRef.current = () => {
    if (!mountedRef.current || !activeRef.current || refreshingRef.current || completedRef.current >= requestedRef.current) return;
    refreshingRef.current = true;
    void (async () => {
      while (mountedRef.current && activeRef.current && completedRef.current < requestedRef.current) {
        const target = requestedRef.current;
        try {
          await refreshRef.current();
        } finally {
          completedRef.current = target;
          settleThrough(target);
        }
      }
    })().finally(() => {
      refreshingRef.current = false;
      drainRef.current();
    });
  };

  const requestRefresh = useCallback((waitForCompletion = true) => {
    const target = ++requestedRef.current;
    if (!waitForCompletion || !mountedRef.current || !activeRef.current) {
      drainRef.current();
      return Promise.resolve();
    }
    const { promise, resolve } = Promise.withResolvers<void>();
    waitersRef.current.push({ target, resolve });
    drainRef.current();
    return promise;
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    if (activeRef.current) drainRef.current();
    return () => {
      mountedRef.current = false;
      settleThrough(Number.POSITIVE_INFINITY);
    };
  }, []);

  useEffect(() => {
    if (active) drainRef.current();
  }, [active]);

  return requestRefresh;
}
