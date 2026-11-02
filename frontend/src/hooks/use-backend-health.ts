import { useEffect, useState } from "react";
import { fetchHealth, type HealthStatus } from "@/api/knowledge";

export type BackendHealth =
  | { state: "checking"; data: null }
  | { state: "online"; data: HealthStatus }
  | { state: "offline"; data: null };

export function useBackendHealth(): BackendHealth {
  const [health, setHealth] = useState<BackendHealth>({ state: "checking", data: null });

  useEffect(() => {
    let disposed = false;
    const check = () => {
      void fetchHealth()
        .then((data) => { if (!disposed) setHealth(data.ok ? { state: "online", data } : { state: "offline", data: null }); })
        .catch(() => { if (!disposed) setHealth({ state: "offline", data: null }); });
    };
    check();
    const timer = window.setInterval(check, 15_000);
    return () => { disposed = true; window.clearInterval(timer); };
  }, []);

  return health;
}
