#!/bin/bash
#
# Simple Redis replication check.
#
# Usage:
#   check_redis_repl.sh redisserver 6379
#
# Technically, this check verifies that the slave is connected to a master
# and has loaded the database. There may be replication lag that needs to be
# checked for? I haven't experienced that in practice, but this needs more
# investigation.
#
# This script originally from Mark's Nagios Plugins:
#    https://github.com/xb95/nagios-plugins
#
# Copyright (c) 2011 by Bump Technologies, Inc, and authors and
# contributors. Please see the above linked repository for licensing
# information.
#

UP=$(redis-cli -h $1 -p $2 info | fgrep 'master_link_status:up')
if [ "$UP" == "" ]; then
    echo "Slave not in sync"
    exit 2
fi

echo "OK: Slave is synced"
