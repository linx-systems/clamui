import { useCallback, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode, type UIEvent } from "react";
import { createScanLogIndex } from "./scanLog";

const ROW_HEIGHT = 18;
const MAX_MOUNTED_ROWS = 50;
const OVERSCAN_ROWS = 4;

type ScanLogViewportProps = {
  readonly chunks: readonly string[];
  readonly label: string;
  readonly className?: string;
};


export function ScanLogViewport({ chunks, label, className }: ScanLogViewportProps) {
  const index = useMemo(() => createScanLogIndex(chunks), [chunks]);
  const viewportRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(0);
  const totalHeight = index.lineCount * ROW_HEIGHT;
  const mountedRowLimit = viewportHeight > 0
    ? Math.min(MAX_MOUNTED_ROWS, Math.max(1, Math.ceil(viewportHeight / ROW_HEIGHT) + OVERSCAN_ROWS * 2))
    : Math.min(MAX_MOUNTED_ROWS, index.lineCount);
  const firstLine = Math.min(
    Math.max(Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN_ROWS, 0),
    Math.max(0, index.lineCount - mountedRowLimit),
  );
  const mountedLineCount = Math.min(mountedRowLimit, index.lineCount - firstLine);

  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return undefined;

    const measure = () => setViewportHeight(viewport.clientHeight);
    measure();

    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", measure);
      return () => window.removeEventListener("resize", measure);
    }

    const observer = new ResizeObserver(measure);
    observer.observe(viewport);
    return () => observer.disconnect();
  }, [index]);

  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const maximumScrollTop = Math.max(0, totalHeight - viewport.clientHeight);
    if (viewport.scrollTop > maximumScrollTop) viewport.scrollTop = maximumScrollTop;
  }, [totalHeight]);

  const onScroll = useCallback((event: UIEvent<HTMLDivElement>) => {
    setScrollTop(event.currentTarget.scrollTop);
  }, []);

  const onKeyDown = useCallback((event: KeyboardEvent<HTMLDivElement>) => {
    const viewport = event.currentTarget;
    const maximumScrollTop = Math.max(0, totalHeight - viewport.clientHeight);
    const pageStep = Math.max(ROW_HEIGHT, viewport.clientHeight - ROW_HEIGHT);
    let nextScrollTop = viewport.scrollTop;

    switch (event.key) {
      case "ArrowDown":
        nextScrollTop = viewport.scrollTop + ROW_HEIGHT;
        break;
      case "ArrowUp":
        nextScrollTop = viewport.scrollTop - ROW_HEIGHT;
        break;
      case "PageDown":
        nextScrollTop = viewport.scrollTop + pageStep;
        break;
      case "PageUp":
        nextScrollTop = viewport.scrollTop - pageStep;
        break;
      case "Home":
        nextScrollTop = 0;
        break;
      case "End":
        nextScrollTop = maximumScrollTop;
        break;
      default:
        return;
    }

    event.preventDefault();
    viewport.scrollTop = Math.min(Math.max(nextScrollTop, 0), maximumScrollTop);
  }, [totalHeight]);

  const viewportClassName = className ? `scan-log-viewport ${className}` : "scan-log-viewport";
  const lines: ReactNode[] = [];
  for (let offset = 0; offset < mountedLineCount; offset += 1) {
    const lineNumber = firstLine + offset;
    lines.push(<div className="scan-log-line" key={lineNumber}>{index.lineAt(lineNumber)}</div>);
  }

  return <div
    aria-label={label}
    className={viewportClassName}
    onKeyDown={onKeyDown}
    onScroll={onScroll}
    ref={viewportRef}
    tabIndex={0}
  >
    <div className="scan-log-spacer" style={{ height: totalHeight }}>
      <div className="scan-log-lines" style={{ transform: `translateY(${firstLine * ROW_HEIGHT}px)` }}>
        {lines}
      </div>
    </div>
  </div>;
}
