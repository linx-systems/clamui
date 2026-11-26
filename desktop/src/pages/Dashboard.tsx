import { useCallback, useEffect, useState } from "react";
import { navigate, notify, onEvent, request } from "../api";
import { _ } from "../i18n";
import { ScanOverview } from "./ScanOverview";
import { useActivityRefresh } from "./useActivityRefresh";

type ScannerStatus = { available?: boolean; database_available?: boolean };

function readableError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export default function Dashboard({ active, scanning }: { active: boolean; scanning: boolean }) {
  const [scanner, setScanner] = useState<ScannerStatus | null>(null);
  const refreshStatus = useCallback(async () => {
    try {
      setScanner(await request<ScannerStatus>("scanner.status"));
    } catch {
      // Status becomes available again once the scanner responds.
    }
  }, []);
  const requestStatusRefresh = useActivityRefresh(active, refreshStatus);
  useEffect(() => {
    let dispose: (() => void) | undefined;
    let listening = true;
    void onEvent((event) => {
      if (event.event === "scan-complete" || event.event === "update-complete") void requestStatusRefresh(false);
    }).then((unlisten) => {
      if (listening) dispose = unlisten;
      else unlisten();
    }).catch((listenError: unknown) => notify(_("Dashboard updates are unavailable: {error}", { error: readableError(listenError) }), "warning"));
    return () => {
      listening = false;
      dispose?.();
    };
  }, [requestStatusRefresh]);

  return <section className="page dashboard-page" aria-label={_("Dashboard")}>
    <ScanOverview
      available={scanner?.available}
      databaseAvailable={scanner?.database_available}
      scanning={scanning}
      result={null}
      active={active}
      onQuickScan={() => navigate("scan", { quickScan: true })}
    />
  </section>;
}
