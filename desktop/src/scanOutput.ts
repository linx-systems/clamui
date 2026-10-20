export type ScanOutputTarget = {
  path?: string;
  error_message?: string | null;
  stdout?: string;
  stderr?: string;
  warning_message?: string;
  nonfatal_warnings?: string[];
};

export type ScanOutputResult = ScanOutputTarget & {
  per_target_results?: ScanOutputTarget[];
};

export function formatScanOutput(result: ScanOutputResult, targetLabel: string): string {
  const targets = result.per_target_results ?? [];
  if (targets.length > 0) {
    return [
      result.error_message,
      ...targets.map((target) => [
        `=== ${target.path || targetLabel} ===`,
        target.error_message === result.error_message ? undefined : target.error_message,
        target.stdout,
        target.stderr,
        target.warning_message,
        ...(target.nonfatal_warnings ?? []),
      ].filter((part): part is string => typeof part === "string" && part.length > 0).join("\n")),
    ].filter((part): part is string => typeof part === "string" && part.length > 0).join("\n\n");
  }

  return [
    result.error_message,
    result.stdout,
    result.stderr,
    result.warning_message,
    ...(result.nonfatal_warnings ?? []),
  ].filter((part): part is string => typeof part === "string" && part.length > 0).join("\n\n");
}
