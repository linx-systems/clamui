import { useEffect, useId, useLayoutEffect, useRef, type ReactNode } from "react";
import { Icon } from "./Icon";
import { _ } from "./i18n";

export type ModalProps = {
  title: string;
  children: ReactNode;
  onClose: () => void;
  className?: string;
  busy?: boolean;
};

function tabbableDescendants(dialog: HTMLDialogElement): HTMLElement[] {
  const selector = [
    "a[href]",
    "button:not([disabled])",
    'input:not([disabled]):not([type="hidden"])',
    "select:not([disabled])",
    "textarea:not([disabled])",
    '[contenteditable="true"]',
    '[tabindex]:not([tabindex="-1"])',
  ].join(",");
  return Array.from(dialog.querySelectorAll<HTMLElement>(selector)).filter((element) => (
    element.tabIndex >= 0 &&
    element.getClientRects().length > 0 &&
    getComputedStyle(element).visibility !== "hidden" &&
    !element.closest("[inert], [hidden]")
  ));
}

/** Native modal dialog with explicit tab containment, Escape handling, and focus return. */
export function Modal({ title, children, onClose, className, busy = false }: ModalProps): ReactNode {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const lastFocusedRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  const busyRef = useRef(busy);
  const titleId = useId();

  useEffect(() => {
    onCloseRef.current = onClose;
    busyRef.current = busy;
  }, [busy, onClose]);

  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) {
      return;
    }
    lastFocusedRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if (!dialog.open) {
      dialog.showModal();
    }
    const cancel = (event: Event): void => {
      event.preventDefault();
      if (!busyRef.current) {
        onCloseRef.current();
      }
    };
    dialog.addEventListener("cancel", cancel);
    const trapTab = (event: KeyboardEvent): void => {
      if (event.key !== "Tab" && event.code !== "Tab") {
        return;
      }
      const tabbables = tabbableDescendants(dialog);
      if (tabbables.length === 0) {
        event.preventDefault();
        dialog.focus({ preventScroll: true });
        return;
      }
      const first = tabbables[0];
      const last = tabbables[tabbables.length - 1];
      const activeElement = document.activeElement;
      if (
        event.shiftKey
          ? activeElement !== first
          : activeElement !== last
      ) {
        if (tabbables.includes(activeElement as HTMLElement)) {
          return;
        }
      }
      event.preventDefault();
      (event.shiftKey ? last : first).focus({ preventScroll: true });
    };
    dialog.addEventListener("keydown", trapTab);

    return () => {
      dialog.removeEventListener("cancel", cancel);
      dialog.removeEventListener("keydown", trapTab);
      if (dialog.open) {
        dialog.close();
      }
      if (lastFocusedRef.current?.isConnected) {
        lastFocusedRef.current.focus({ preventScroll: true });
      }
    };
  }, []);

  return (
    <dialog
      className={`modal-dialog${className ? ` ${className}` : ""}`}
      ref={dialogRef}
      tabIndex={-1}
      aria-labelledby={titleId}
      aria-modal="true"
      aria-busy={busy || undefined}
    >
      <div className="dialog-header">
        <h2 id={titleId}>{title}</h2>
        <button className="button icon-button" type="button" aria-label={_("Close")} disabled={busy} onClick={() => onCloseRef.current()}>
          <Icon name="close" />
        </button>
      </div>
      {children}
    </dialog>
  );
}
