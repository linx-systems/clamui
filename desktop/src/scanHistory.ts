export type LatestScan = {
  timestamp?: string;
  status: string;
  summary?: string;
  scanned_files?: number;
  infected_count?: number;
  threat_details?: Array<{ file_path: string; threat_name: string }>;
};

export function parseLatestScan(value: unknown): LatestScan | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  if (typeof record.status !== "string") return null;
  const count = (value: unknown) => typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : undefined;
  return {
    status: record.status,
    timestamp: typeof record.timestamp === "string" ? record.timestamp : undefined,
    summary: typeof record.summary === "string" ? record.summary : undefined,
    scanned_files: count(record.scanned_files),
    infected_count: count(record.infected_count),
  };
}

