# EDHREC snapshots

Transcribed EDHREC commander pages, one file per commander + variant + date:

`<commander-slug>__<variant>__<YYYY-MM-DD>.txt`

e.g. `jodah-archmage-eternal__upgraded__2026-09-27.txt`

Format, workflow, and the mandatory `edhrec_diff.py check` step are in
docs/USE_INSTRUCTIONS.md §9. `audit.py` finds the newest matching file
automatically. Anything over 30 days old should be refetched.
