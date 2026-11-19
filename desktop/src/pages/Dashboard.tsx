import { useCallback, useState } from "react";
import { navigate, request } from "../api";
import { _ } from "../i18n";
import { ScanOverview } from "./ScanOverview";
import { useActivityRefresh } from "./useActivityRefresh";

type ScannerStatus = { available?: boolean; database_available?: boolean };

export default function Dashboard({ active, scanning }: { active: boolean; scanning: boolean }) {
  const [scanner, setScanner] = useState<ScannerStatus | null>(null);
  const refreshStatus = useCallback(async () => {
    try {
      setScanner(await request<ScannerStatus>("scanner.status"));
    } catch {
      // Status becomes available again once the scanner responds.
    }
  }, []);
  useActivityRefresh(active, refreshStatus);

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
