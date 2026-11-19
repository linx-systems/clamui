import type { PageId } from "./pageId";

// Scan must be mounted from the start: App's selectPage() dispatches
// clamui-page-selected/clamui-quick-scan and open-targets synchronously,
// before a lazily mounted Scan page's useEffect has attached its window
// listeners, so those first events would otherwise be dropped.
export const INITIAL_MOUNTED_PAGES: readonly PageId[] = ["dashboard", "scan"];
