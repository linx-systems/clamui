#!/bin/bash
# ClamUI VirusTotal Scanner - Nautilus Script (Flatpak version)
# This script is installed to ~/.local/share/nautilus/scripts/
# and provides a "Scan with VirusTotal" context menu option.
#
# Usage: Called by Nautilus file manager when selecting "Scripts > Scan with VirusTotal"
# The selected files are passed via NAUTILUS_SCRIPT_SELECTED_FILE_PATHS environment variable.

# Enable logging for debugging
LOG_FILE="${XDG_CACHE_HOME:-$HOME/.cache}/clamui/virustotal-nautilus.log"
mkdir -p "$(dirname "$LOG_FILE")"

log() {
	echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >>"$LOG_FILE"
}

log "Script started (Flatpak version)"
log "NAUTILUS_SCRIPT_SELECTED_FILE_PATHS: $NAUTILUS_SCRIPT_SELECTED_FILE_PATHS"
log "Arguments: $*"

# Check if ClamUI Flatpak is available
if ! flatpak info io.github.linx_systems.ClamUI &>/dev/null; then
	log "ERROR: ClamUI Flatpak not installed"
	# Try to notify user
	if command -v notify-send &>/dev/null; then
		notify-send "ClamUI Not Found" "Please install ClamUI Flatpak to use VirusTotal scanning."
	fi
	exit 1
fi

log "ClamUI Flatpak found"

# Get selected files from Nautilus
# NAUTILUS_SCRIPT_SELECTED_FILE_PATHS contains newline-separated paths
if [[ -n "$NAUTILUS_SCRIPT_SELECTED_FILE_PATHS" ]]; then
	# Convert newline-separated paths to array
	IFS=$'\n' read -d '' -r -a files <<<"$NAUTILUS_SCRIPT_SELECTED_FILE_PATHS"

	log "Found ${#files[@]} files from NAUTILUS_SCRIPT_SELECTED_FILE_PATHS"

	# Launch clamui with --virustotal flag for the first file
	# (VirusTotal only supports single file scanning)
	if [[ ${#files[@]} -gt 0 ]]; then
		log "Launching: flatpak run io.github.linx_systems.ClamUI --virustotal \"${files[0]}\""
		flatpak run io.github.linx_systems.ClamUI --virustotal "${files[0]}" 2>&1 | tee -a "$LOG_FILE"
		log "clamui exited with code: $?"
	else
		log "ERROR: No files in array"
	fi
else
	# Fallback: try to use positional arguments
	if [[ $# -gt 0 ]]; then
		log "Using positional argument: $1"
		log "Launching: flatpak run io.github.linx_systems.ClamUI --virustotal \"$1\""
		flatpak run io.github.linx_systems.ClamUI --virustotal "$1" 2>&1 | tee -a "$LOG_FILE"
		log "clamui exited with code: $?"
	else
		log "ERROR: No files provided (neither env var nor arguments)"
		if command -v notify-send &>/dev/null; then
			notify-send "ClamUI VirusTotal" "No file selected for scanning."
		fi
	fi
fi

log "Script finished"
