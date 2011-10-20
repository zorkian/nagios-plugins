#!/usr/bin/python

'''check_riak.py -- a nagios plugin for Riak

This script originally from Mark's Nagios Plugins:
    https://github.com/xb95/nagios-plugins

Usage of this script is complicated by how many things you could
possibly be checking. In short, Riak gives you latencies on get and put
requests, sliced over the last 60 seconds in various ways.

For example, if you want to monitor the 95th percentile of your
requests, you can do:

    check_riak.py -H localhost -p 8098 --95th 10,20,15,25

The latency checks (--95th, --99th, --100th, --mean, --median) all use
the same format for data: "PW,PC,GW,GC". These values are:

    PW - WARNING if PUT latency exceeds this value in ms
    PC - CRITICAL if PUT latency exceeds this value in ms
    GW - WARNING if GET latency exceeds this value in ms
    GC - CRITICAL if GET latency exceeds this value in ms

All values are in milliseconds. Therefore, in the above example we are
going to fire a WARNING if the PUT latency exceeds 10ms as measured at
the 95th percentile.

A second example, let's say that you want to warn if the 95th exceeds
the above threshold, but you also want to monitor the 99th and make sure
it doesn't exceed some looser numbers.

    check_riak.py -H localhost -p 8098 --95th 15,25,5,10 \
        --99th 50,100,25,50

Finally, you can have this script also monitor the size of the ring
membership. This can be a simple way to alert if you lose more nodes
than you are comfortable with:

    check_riak.py -H localhost -p 8098 --ring 4,3

The values here are "W,C" which are the thresholds to warn/go critical
at. These values must be exceeded (the current ring member count must
fall below them) before they fire. Therefore, if you have 5 nodes in
your cluster and you want to warn if you lose any, set W to 5. "Warn if
this goes below 5."

Copyright (c) 2011 by Bump Technologies, Inc, and authors and
contributors. Please see the above linked repository for licensing
information.

'''

import re
import sys
from urllib2 import urlopen, URLError
from json import loads
from optparse import OptionParser


def _nagios(hdr, msg, code):
    print '%s: %s' % (hdr, msg)
    return code

def critical(msg): return _nagios('CRITICAL', msg, 2)
def warning(msg): return _nagios('WARNING', msg, 1)
def okay(msg): return _nagios('OKAY', msg, 0)


def main(args):
    '''This is the body of the plugin. Verifies arguments and then
    connects to Riak and gathers the requested statistics. Returns a
    value that is appropriate to a Nagios plugin.

    '''
    parser = OptionParser()
    parser.add_option('-H', '--host', dest='host', default='localhost',
                      help='Host to connect to.', metavar='HOST')
    parser.add_option('-p', '--port', dest='port', type='int', default=8098,
                      help='Port to connect to.', metavar='PORT')
    parser.add_option('--95th', dest='t95', metavar='THRESHOLDS',
                      help='"PW,PC,GW,GC" values for 95th percentile data')
    parser.add_option('--99th', dest='t99', metavar='THRESHOLDS',
                      help='"PW,PC,GW,GC" values for 99th percentile data')
    parser.add_option('--100th', dest='t100', metavar='THRESHOLDS',
                      help='"PW,PC,GW,GC" values for 100th percentile data')
    parser.add_option('--mean', dest='tmean', metavar='THRESHOLDS',
                      help='"PW,PC,GW,GC" values for mean percentile data')
    parser.add_option('--median', dest='tmedian', metavar='THRESHOLDS',
                      help='"PW,PC,GW,GC" values for median percentile data')
    parser.add_option('--ring', dest='tring', metavar='RING_THRESHOLDS',
                      help='"W,C" format for ring member thresholds')
    (options, args) = parser.parse_args()

    types = (('t95', '95'), ('t99', '99'), ('t100', '100'),
             ('tmedian', 'median'), ('tmean', 'mean'))
    for optname in [v[0] for v in types]:
        val = getattr(options, optname, None)
        if val is not None and not re.match(r'^\d+,\d+,\d+,\d+$', val):
            parser.error('Thresholds must be of the format "PW,PC,GW,GC".')
    if options.tring and not re.match(r'^\d+,\d+$', options.tring):
        parser.error('Ring threshold must be of the format "W,C".')

    try:
        req = urlopen("http://%s:%d/stats" % (options.host, options.port))
        obj = loads(req.read())
    except (URLError, ValueError) as e:
        return critical(str(e))

    crit, warn, ok = [], [], []
    def check(metric, warning, critical):
        if metric not in obj:
            crit.append('%s not found in Riak stats output' % metric)
            return
        val_ms = int(obj[metric] / 1000)
        if val_ms > critical:
            crit.append('%s: %dms (>%dms)' % (metric, val_ms, critical))
        elif val_ms > warning:
            warn.append('%s: %dms (>%dms)' % (metric, val_ms, warning))
        else:
            ok.append('%s: %dms' % (metric, val_ms))

    for ttype in types:
        optname, metricname = ttype
        val = getattr(options, optname, None)
        if val is None:
            continue
        pw, pc, gw, gc = [int(x) for x in val.split(',', 4)]
        check('node_get_fsm_time_%s' % metricname, gw, gc)
        check('node_put_fsm_time_%s' % metricname, pw, pc)

    val = getattr(options, 'tring', None)
    if val is not None:
        rw, rc = [int(x) for x in val.split(',', 2)]
        if 'ring_members' in obj:
            ring_size = len(obj['ring_members'])
            if ring_size < rc:
                crit.append('ring size: %d members (<%d)' % (ring_size, rc))
            elif ring_size < rw:
                warn.append('ring size: %d members (<%d)' % (ring_size, rw))
            else:
                ok.append('ring size: %d members' % ring_size)
        else:
            crit.append('ring size: unable to determine member count')

    if len(crit) > 0:
        return critical(', '.join(crit))
    elif len(warn) > 0:
        return warning(', '.join(warn))
    return okay(', '.join(ok))


if __name__ == '__main__':
    sys.exit(main(sys.argv[0:]))
