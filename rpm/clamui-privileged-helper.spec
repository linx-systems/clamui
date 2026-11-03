Name:           clamui-privileged-helper
Epoch:          0
Version:        %{clamui_version}
Release:        1
Summary:        Root-owned ClamUI privileged helper and PolicyKit policy
License:        MIT
URL:            https://github.com/linx-systems/clamui
BuildArch:      %{_target_cpu}
Requires:       polkit

# The helper is already built on the supported native baseline. Do not generate
# debuginfo or build-id links for that binary.
%global debug_package %{nil}
%global _build_id_links none

Source0:        clamui-apply-preferences
Source1:        io.github.linx_systems.ClamUI.policy

%description
Root-owned Rust helper (/usr/bin/clamui-apply-preferences) and the matching
PolicyKit policy for applying authorized host ClamAV configuration from ClamUI.

%install
install -Dpm 0755 %{SOURCE0} %{buildroot}%{_bindir}/clamui-apply-preferences
install -Dpm 0644 %{SOURCE1} %{buildroot}%{_datadir}/polkit-1/actions/io.github.linx_systems.ClamUI.policy

%files
%attr(0755,root,root) %{_bindir}/clamui-apply-preferences
%attr(0644,root,root) %{_datadir}/polkit-1/actions/io.github.linx_systems.ClamUI.policy
