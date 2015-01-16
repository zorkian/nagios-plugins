#!/usr/bin/python

'''check_riak_ring.py -- a nagios plugin for monitoring Riak rings

This script originally from Mark's Nagios Plugins:
    https://github.com/xb95/nagios-plugins

As arguments, give this script some number of names/IPs to connect to
and pull Riak statistics. We will then use the information from the Ring
membership to connect to all of the nodes in the cluster and make sure
that the ring is entirely consistent.

Usage:
    ./check_riak_ring.py [-p 8098] [--down-ok] hosta hostb hostc hostd...

Copyright (c) 2012 by Bump Technologies, Inc, and authors and
contributors. Please see the above linked repository for licensing
information.

'''

import random
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
    parser.add_option('-p', '--port', dest='port', type='int', default=8098,
                      help='Port to connect to.', metavar='PORT')
    parser.add_option('--down-ok', dest='down_ok', action='store_true',
                      help='Do not alert on down nodes.')
    parser.add_option('-v', dest='verbose', action='store_true',
                      help='Print extra data in the output.')
    parser.add_option('-t', '--timeout', dest='timeout', type='int', default=3,
                      help='Connection timeout.')
    (options, args) = parser.parse_args()

    # Ensure we have hosts
    if not args:
        print 'Usage: ./check_riak_ring.py [-v] [-p 8098] [-t 3] [--down-ok] <hosta> [hostb hostc...]'
        sys.exit(1)

    # Gather ring states by iterating over the list of nodes we were told to
    # connect to, but also accepting more to add to our list.
    ownership, ownstrings = {}, {}
    hosts = args
    while len(hosts) > 0:
        host = hosts.pop(0)
        try:
            req = urlopen("http://%s:%d/stats" % (host, options.port), timeout=options.timeout)
            obj = loads(req.read())
        except (URLError, ValueError) as e:
            if options.down_ok:
                continue
            return critical('%s failed (GET): %s' % (host, str(e)))
        if obj is None or 'ring_ownership' not in obj:
            if options.down_ok:
                continue
            return critical('%s failed: no stats found' % host)

        owned = parse_ownership(obj['ring_ownership'])
        if not len(owned):
            return critical('%s has no connected nodes' % host)

        ownstring = ''
        for thost in sorted(owned):
            ownstring += ',' if ownstring else ''
            ownstring += thost + '=' + owned[thost]
            if thost not in ownership and thost not in hosts and host != thost:
                hosts.append(thost)

        ownership[host] = ownstring
        if ownstring not in ownstrings:
            ownstrings[ownstring] = 1
        else:
            ownstrings[ownstring] += 1

    # If we get here, we have ownership strings from everybody. If the
    # ownstrings dict is only length one, we're good.
    if len(ownstrings) == 1:
        if options.verbose:
            return okay('%d nodes agree: %s' % (len(ownership), ' '.join(sorted(ownership))))
        else:
            return okay('%d nodes up: ring is in agreement' % len(ownership))

    # Something has gone badly wrong. Let's see if we can identify the most
    # common pattern, and then reverse that to figure out who disagrees with
    # the rest of the cluster. (This is somewhat fragile, but hopefully it
    # will help with the common case of one out-of-whack node.)
    prob_correct, prob_ct = None, 0
    for s in ownstrings:
        if ownstrings[s] > prob_ct:
            prob_correct, prob_ct = s, ownstrings[s]
    bad_hosts = []
    for host in ownership:
        if ownership[host] != prob_correct:
            bad_hosts.append(host)
    return critical('Ring ownership disagreement! Maybe check: %s' %
                    ', '.join(sorted(bad_hosts)))


def parse_ownership(val):
    ret = {}
    for k in val.split('}'):
        if '{' not in k:
            continue
        host, ct = k.split('{')[1].split(',')
        host = host.split('@')[1].strip("'")
        ret[host] = ct
    return ret


if __name__ == '__main__':
    sys.exit(main(sys.argv[0:]))
