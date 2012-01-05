#!/bin/bash
#
# A super simple check for TLS negotiation for stud.
#
# Usage:
#   check_stud_server.sh lbhost 443 "Jul 16 22:19:36 2010 GMT"
#
# This check verifies that the notAfter date on the certificate matches
# the provided date.
#
# This script originally from Mark's Nagios Plugins:
#    https://github.com/xb95/nagios-plugins
#
# Copyright (c) 2011 by Bump Technologies, Inc, and authors and
# contributors. Please see the above linked repository for licensing
# information.
#

HOST=$1
PORT=$2
DATE=$3

echo "Q" | \
    openssl s_client -connect $HOST:$PORT -tls1 2>&1 | \
    grep -q "notAfter=$DATE"

if [ $? -eq 0 ]; then
    echo "OK: found expected stud certificated."
    exit 0
else
    echo "CRITICAL: unexpected result from stud test."
    exit 2
fi
