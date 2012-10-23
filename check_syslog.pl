#!/usr/bin/perl
#
# check_syslog.pl
#
# This script originally from Mark's Nagios Plugins:
#    https://github.com/xb95/nagios-plugins
#
# This plugin checks the syslog file for things that are common problems and
# print reliable messages in syslog. This is not meant to be something that
# looks for every single possibility, but certain things are reliably noticed
# by messages being printed to the system log.
#
# The caveat is that if this script alerts, you will probably need to reset
# the alerting because it can't tell that time has passed. You can do this
# by invoking the plugin with the '--clear' flag.
#
# Copyright (c) 2012 by Bump Technologies, Inc, and authors and
# contributors. Please see the above linked repository for licensing
# information.
#

use v5.10;
use strict;
use Sys::Syslog;

if ($ARGV[0] eq '--clear') {
    openlog('check_syslog', 'ndelay', 'local0');
    syslog('info', 'Admin request: force-syslog-all-clear.');
    closelog();
    exit 0;
}

my $state = [ 0, 'OK: Syslog clear' ];
open LOG, "</var/log/syslog";
foreach my $line (<LOG>) {
    my $propose;
    if ($line =~ /.* rsyslogd: \[.+\] \(re\)start/i ||
            $line =~ /force-syslog-all-clear/i) {
        $propose = [ 0, 'OK: Syslog clear' ];
    } elsif ($line =~ /offlined - array failed/i) {
        $propose = [ 2, 'CRITICAL: Device failure, array offline' ];
    } elsif ($line =~ /nf_conntrack: table full/i) {
        $propose = [ 2, 'CRITICAL: nf_conntrack: table full' ];
    }

    next unless defined $propose;
    if ($propose->[0] == 0 || $propose->[0] > $state->[0]) {
        $state = $propose;
    }
}
close LOG;

say $state->[1];
exit $state->[0];
