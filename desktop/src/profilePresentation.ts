import { _ } from "./i18n";

type PresentedProfile = {
  is_default: boolean;
  name: string;
  description: string;
};

export function profileLabel(profile: Pick<PresentedProfile, "is_default" | "name">): string {
  if (!profile.is_default) return profile.name;

  switch (profile.name) {
    case "Quick Scan":
      return _("Quick Scan");
    case "Full Scan":
      return _("Full Scan");
    case "Home Folder":
      return _("Home Folder");
    default:
      return profile.name;
  }
}

export function profileDescription(profile: PresentedProfile): string {
  if (!profile.is_default) return profile.description;

  switch (profile.name) {
    case "Quick Scan":
      return profile.description === "Fast scan of the Downloads folder for quick threat detection"
        ? _("Fast scan of the Downloads folder for quick threat detection")
        : profile.description;
    case "Full Scan":
      return profile.description === "Comprehensive system-wide scan of all accessible directories"
        ? _("Comprehensive system-wide scan of all accessible directories")
        : profile.description;
    case "Home Folder":
      return profile.description === "Scan of the user's home directory and personal files"
        ? _("Scan of the user's home directory and personal files")
        : profile.description;
    default:
      return profile.description;
  }
}
