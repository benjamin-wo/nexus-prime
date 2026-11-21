#!/usr/bin/env bash
# Create or update the issue labels the software factory uses.
# Safe to run more than once: --force updates a label that already exists.
# `wontfix` is a GitHub default and is left alone.
set -euo pipefail

label() {
  gh label create "$1" --color "$2" --description "$3" --force
}

label needs-triage    FBCA04 "Maintainer needs to evaluate this issue"
label needs-info      D4C5F9 "Waiting on reporter for more information"
label ready-for-agent 0E8A16 "Fully specified, ready for the build bot"
label ready-for-human 1D76DB "Requires human implementation"
label spec-proposed   C2E0C6 "Triage bot posted a spec; waiting for the owner to apply ready-for-agent"
label sensitive       B60205 "Risk class: needs owner review at both spec and PR"
