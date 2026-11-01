import { type ReactNode } from "react";

import { notify, openExternal } from "./api";
import { helperTrustFailure } from "./helperTrustError";
import { Icon } from "./Icon";
import { _ } from "./i18n";
import { Modal } from "./Modal";

const HELPER_PATH = "/usr/bin/clamui-apply-preferences";
const REPAIR_GUIDE_URL = "https://clamui.com/docs/troubleshooting/#privileged-helper-is-not-trusted";

type HelperTrustErrorDialogProps = {
  rawError: string;
  canInstall: boolean;
  installing: boolean;
  installError: string | null;
  onInstall: () => void;
  onSeeConfiguration?: () => void;
  onClose: () => void;
};

export function HelperTrustErrorDialog({
  rawError,
  canInstall,
  installing,
  installError,
  onInstall,
  onSeeConfiguration,
  onClose,
}: HelperTrustErrorDialogProps): ReactNode {
  const failure = helperTrustFailure(rawError);
  const missing = failure === "missing";
  const canOfferInstall = missing && canInstall;
  const openRepairGuide = (): void => {
    void openExternal(REPAIR_GUIDE_URL).catch((error: unknown) => {
      notify(_("Could not open documentation: {error}", { error: String(error) }), "error");
    });
  };

  return <Modal title={_("Protected settings are blocked")} busy={installing} onClose={onClose} className="helper-trust-error-dialog">
    <section className="helper-trust-error-content">
      <div className="helper-trust-error-intro">
        <Icon name="warning" className="helper-trust-error-icon" />
        <div>
          <p>{missing
            ? _("ClamUI could not save protected settings because its system helper is not installed.")
            : _("ClamUI blocked this operation because its system helper is missing or is not securely installed.")}</p>
          <p>{_("The helper provides administrator-authorized access to protected ClamAV settings.")}</p>
        </div>
      </div>
      {canOfferInstall ? <>
        <p>{_("Installing the helper requires administrator authorization.")}</p>
        <p>{_(
          // Translators: Keep Fedora, DNF, and ClamUI unchanged; DNF is Fedora's package manager.
          "On Fedora with DNF, installation also adds the ClamUI signing key to the system RPM keyring.",
        )}</p>
      </> : null}
      <div className="helper-trust-error-location">
        <strong>{_("Helper location")}</strong>
        <code>{HELPER_PATH}</code>
      </div>
      {!missing && <p className="helper-trust-error-requirement">{_("The helper must be an executable file owned by root, not a symbolic link, and other users must not be able to change it.")}</p>}
      <h3>{_("How to fix it")}</h3>
      <ol className="helper-trust-error-steps">
        <li>{missing
          ? _("Install the matching helper from the same trusted ClamUI release.")
          : _("Reinstall the matching helper from the same trusted ClamUI release.")}</li>
        <li>{_("Then return to Preferences and repeat the action.")}</li>
      </ol>
      {!missing && <p className="helper-trust-error-caution"><Icon name="shield" />{_("Do not change the permissions of an unknown executable to bypass this check.")}</p>}
      <details className="helper-trust-error-details">
        <summary tabIndex={0}><Icon name="chevron-down" />{_("Technical details")}</summary>
        <pre>{rawError}</pre>
      </details>
    </section>
    {installing ? <p className="notice" role="status">{_("Installing privileged helper…")}</p> : null}
    {installError ? <p className="error" role="alert">{installError}</p> : null}
    <div className="dialog-actions helper-trust-error-actions">
      <button className="button" type="button" disabled={installing} onClick={openRepairGuide}><Icon name="external-link" />{_("Open repair instructions")}</button>
      {onSeeConfiguration ? <button className="button" type="button" disabled={installing} onClick={onSeeConfiguration}>{_(
        // Translators: This button opens the failed native configuration snapshot.
        "See Configuration",
      )}</button> : null}
      {canOfferInstall ? <button className="button primary" type="button" disabled={installing} onClick={onInstall}>{installing ? _("Installing…") : installError ? _("Try Again") : _("Install Helper")}</button> : null}
      <button className="button primary" type="button" disabled={installing} onClick={onClose}>{_("Close")}</button>
    </div>
  </Modal>;
}
