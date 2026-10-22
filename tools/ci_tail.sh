#!/bin/bash
# Prints the end of a log file as one GitHub annotation (readable via the API without downloading logs).
#   tools/ci_tail.sh LOGFILE [LINES]
f="$1"; n="${2:-80}"
[ -f "$f" ] || { echo "::error title=log missing::$f"; exit 0; }
msg=$(tail -n "$n" "$f" | sed -e 's/\x1b\[[0-9;]*m//g' | cut -c1-300 | sed -e 's/%/%25/g' | sed ':a;N;$!ba;s/\r/%0D/g;s/\n/%0A/g')
echo "::error title=$(basename "$f") (last $n lines)::$msg"
