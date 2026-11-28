#!/usr/bin/env bash
set -euo pipefail

. /etc/os-release
if [[ "${ID:-}" != ubuntu || "${VERSION_ID:-}" != 22.04 ]]; then
  echo "Native packages must be built on Ubuntu 22.04." >&2
  exit 1
fi

arch="$(dpkg --print-architecture)"
case "$arch" in
  amd64) archive=ubuntu ;;
  arm64) archive=ubuntu-ports ;;
  *) echo "Unsupported Ubuntu architecture." >&2; exit 1 ;;
esac

# Keep both operations on fresh indexes from the same authenticated archive.
apt_dir="$(mktemp -d)"
trap 'rm -rf "$apt_dir"' EXIT
chmod 755 "$apt_dir"
mkdir -p "$apt_dir/lists/partial" "$apt_dir/cache/archives/partial"
for pocket in jammy jammy-updates jammy-security jammy-backports; do
  echo "deb [arch=$arch signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg] https://ftp.tu-chemnitz.de/pub/linux/$archive/ $pocket main restricted universe multiverse" >> "$apt_dir/sources.list"
done

apt_options=(
  -o "Dir::Etc::sourcelist=$apt_dir/sources.list"
  -o "Dir::Etc::sourceparts=-"
  -o "Dir::State::lists=$apt_dir/lists"
  -o "Dir::Cache=$apt_dir/cache"
  -o "Acquire::Languages=none"
  -o "Acquire::Retries=0"
  -o "Acquire::http::Timeout=30"
  -o "Acquire::https::Timeout=30"
  -o "APT::Update::Error-Mode=any"
)
apt-get "${apt_options[@]}" update
DEBIAN_FRONTEND=noninteractive apt-get "${apt_options[@]}" install -y "$@"
