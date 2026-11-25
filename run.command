#!/bin/sh
# Domingo on macOS, for people who set their browser to open .command files.
# Double-clicking this in Finder opens a Terminal window and starts the server.
# The same script works from a shell:  sh run.command
exec sh "$(dirname "$0")/run.sh" "$@"
