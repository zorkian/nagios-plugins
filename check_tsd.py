#!/usr/bin/python

'''%prog -- a script for generating alerts from TSD

This script connects to TSD and uses data points from there to determine
if a particular metric has gone outside of the expected range. This is
useful for creating a Nagios alert or sending email or taking actions
based on the results.

There are two main modes to use this script. The best way to describe it
is to use examples.

$ check_tsd.py -m proc.loadavg.15min -t host=web01 -w 5 -c 10

This loads the metric proc.loadavg.15min with the tag "host=web01". By
default, the script looks back 10 minutes and looks to see if *any* data
point exceeds the thresholds given. If so, alert.

But you might not want to alert if the load average just hits over the
line once or twice. Let's only alert if 20% of the data points are over
the line:

$ check_tsd.py -P 20 -m proc.loadavg.15min -t host=web01 -w 5 -c 10

There are many more options. I recommend you read through them to get an
idea of what they can do.

This script originally from Mark's Nagios Plugins:
    https://github.com/xb95/nagios-plugins

Copyright (c) 2010-2011 by StumbleUpon, Inc., Bump Technologies, Inc,
and authors and contributors. Please see the above linked repository for
licensing information.

'''


import datetime
import httplib
import operator
import socket
import sys
import time
from optparse import OptionParser


def main(argv):
    '''Main program runs here. Get the arguments, do something interesting.

    '''
    parser = OptionParser(usage=__doc__)
    parser.add_option('-H', '--host', dest='host', default='localhost', metavar='HOST',
            help='Hostname to use to connect to the TSD.')
    parser.add_option('-p', '--port', dest='port', type='int', default=4242,
            metavar='PORT', help='Port to connect to the TSD instance on.')
    parser.add_option('-m', '--metric', dest='metric', metavar='METRIC',
            help='Metric to query.')
    parser.add_option('-r', '--rate', dest='rate', default=False, action='store_true',
            help='Parse metric as a rate value.')
    parser.add_option('-L', '--delta', dest='delta', default=False, action='store_true',
            help='Use delta mode (see docs)')
    parser.add_option('-t', '--tag', dest='tags', action='append', default=[],
            metavar='TAG', help='Tags to filter the metric on.')
    parser.add_option('-d', '--duration', dest='duration', type='int', default=600,
            metavar='SECONDS', help='How far back to look for data.')
    parser.add_option('-D', '--downsample', dest='downsample', default='none',
            metavar='METHOD',
            help='Downsample the data over the duration via avg, min, sum, or max.')
    parser.add_option('-a', '--aggregator', dest='aggregator', default='sum',
            metavar='METHOD',
            help='Aggregation method: avg, min, sum (default), max.')
    parser.add_option('-x', '--method', dest='comparator', default='gt',
            metavar='METHOD', help='Comparison method for -w/-c: gt, ge, lt, le, eq, ne.')
    parser.add_option('-w', '--warning', dest='warning', type='float', metavar='THRESHOLD',
            help='Threshold for warning.  Uses the comparison method.')
    parser.add_option('-c', '--critical', dest='critical', type='float', metavar='THRESHOLD',
            help='Threshold for critical.  Uses the comparison method.')
    parser.add_option('-v', '--verbose', dest='verbose', default=False,
            action='store_true', help='Be more verbose.')
    parser.add_option('-T', '--timeout', dest='timeout', type='int', default=10,
            metavar='SECONDS', help='How long to wait for the response from TSD.')
    parser.add_option('-E', '--no-result-ok', dest='no_result_ok', default=False,
            action='store_true', help='Return OK when TSD query returns no result.')
    parser.add_option('-I', '--ignore-recent', dest='ignore_recent', default=0,
            metavar='SECONDS', type='int', help='Ignore data points that are more'
            ' recent than this.')
    parser.add_option('-P', '--percent-over', dest='percent_over', default=0,
            metavar='PERCENT', type='int', help='Only alarm if PERCENT of the data'
            ' points violate the threshold.')
    parser.add_option('-b', '--bucket-size', dest='bucket_size', default=0,
            metavar='SECONDS', type='int', help='How many seconds of data to consider'
            ' for doing bucket comparisons.')
    parser.add_option('-o', '--buckets-ago', dest='buckets_ago', default=0,
            metavar='BUCKETS', type='int', help='How many buckets back to compare'
            ' against the current bucket.')
    parser.add_option('-Z', '--bucket-no-abs', dest='bucket_abs', default=True,
            action='store_false', help='If present, do not only consider buckets'
            ' using absolute values.')
    (options, args) = parser.parse_args(args=argv[1:])

    # argument validation
    if options.comparator not in ('gt', 'ge', 'lt', 'le', 'eq', 'ne'):
        parser.error('Comparator "%s" not valid.' % options.comparator)
    elif options.downsample not in ('none', 'avg', 'min', 'sum', 'max'):
        parser.error('Downsample "%s" not valid.' % options.downsample)
    elif options.aggregator not in ('avg', 'min', 'sum', 'max'):
        parser.error('Aggregator "%s" not valid.' % options.aggregator)
    elif not options.metric:
        parser.error('You must specify a metric (option -m).')
    elif options.duration <= 0:
        parser.error('Duration must be strictly positive.')
    elif not options.critical and not options.warning:
        parser.error('You must specify at least a warning threshold (-w) or a'
                     ' critical threshold (-c).')
    elif options.ignore_recent < 0:
        parser.error('--ignore-recent must be positive.')
    elif options.percent_over < 0 or options.percent_over > 100:
        parser.error('--percent-over must be in the range 0..100.')
    elif options.bucket_size > 0 and options.bucket_size < 60:
        parser.error('--bucket-size must be at least 60 seconds')
    elif options.bucket_size > 0 and options.buckets_ago < 1:
        parser.error('--buckets-ago must be 1 or more')
    elif options.delta and options.rate:
        parser.error('--delta must not be combined with --rate')
    elif options.delta and options.percent_over > 0:
        parser.error('--delta must not be combined with --percent-over')
    elif options.delta and options.buckets_ago > 0:
        parser.error('--delta must not be combined with --buckets-ago')

    options.percent_over /= 100.0  # Convert to range 0-1
    if not options.critical:
        options.critical = options.warning
    elif not options.warning:
        options.warning = options.critical

    # Ensure that the warning/critical parameters are well ordered.
    comparator = operator.__dict__[options.comparator]
    if comparator(options.warning, options.critical):
        parser.error('Warning/Critical thresholds appear to be inverted.')

    # Branching logic begins here
    if options.bucket_size > 0:
        return bucket_check(options, comparator)
    else:
        return recent_check(options, comparator)


def linear_fit(dps, dpe, ts):
    '''Given two data points around a time, return a value for the exact
    time requested. This is a linear approximation algorithm. Nothing
    fancy.

    '''
    # If the end value is less than the beginning value, then we assume we had
    # a counter reset in the middle of the series. Since we don't know where
    # it reset, let's just assume 0. Not a great solution, but it should keep
    # the data away from crazytown.
    if dpe[1] < dps[1]:
        return 0
    delta = (float(dpe[1] - dps[1]) / float(dpe[0] - dps[0]))
    return dps[1] + delta * (ts - dps[0])


def get_bucket(options, metric, which):
    '''Get the value for a single bucket. This returns a single value
    which is calculated based on the options. The which argument is
    basically how many buckets ago you want, we use 0 to mean the
    current bucket (the most recently finished one) and every number
    goes back by bucket_size seconds.

    '''
    bs = options.bucket_size
    now = int(time.time())
    end = now - (now % bs)
    start = (end - bs) - (which * bs)
    end = start + bs - 1
    if options.verbose:
        print 'get_bucket size=%d which=%d now=%d start=%d end=%d' % (
              bs, which, now, start, end)

    url = ('/q?start=%d&end=%d&m=%s&ascii&nagios' %
           (start - bs, end + bs, metric))
    datapoints = get_datapoints(options, url)

    dp = [None, None, None, None]
    highest_val = None
    for datapoint in datapoints:
        ts, val = datapoint

        if highest_val is None or val > highest_val:
            highest_val = val

        if ts < start:
            if dp[0] is None or ts > dp[0][0]:
                dp[0] = datapoint
        elif ts > end:
            if dp[3] is None or ts < dp[3][0]:
                dp[3] = datapoint
        else:
            if dp[1] is None or ts < dp[1][0]:
                dp[1] = datapoint
            if dp[2] is None or ts > dp[2][0]:
                dp[2] = datapoint

    if dp[0] is None or dp[1] is None or dp[2] is None or dp[3] is None:
        print 'not enough data to frame the requested bucket'
        sys.exit(1)
    start_val = linear_fit(dp[0], dp[1], start)
    end_val = linear_fit(dp[2], dp[3], end)

    if options.rate:
        # If the counter restarted in the middle of this bucket, we have to do
        # some work to make sure our value is mostly correct. This is a best
        # effort approximation.
        if end_val < start_val:
            return (highest_val - start_val) + end_val
        else:
            return end_val - start_val
    else:
        print 'sorry, buckets only work with rates right now'
        sys.exit(1)


def bucket_check(options, comparator):
    '''A bucket check is a comparison of buckets. A bucket is defined as
    a sum of data in a certain period of time. We check the most recent
    full bucket against a second bucket located N buckets ago.

    This lets us do checks like "alert if the number of X has fallen
    more than 10% since 15 minutes ago" or "alert if traffic is more
    than 5% lower compared to a week ago at this time".

    '''
    tags = ','.join(options.tags)
    if tags:
        tags = '{' + tags + '}'
    if options.downsample != 'none':
        print 'downsampling not supported with bucket checks'
        sys.exit(1)
    metric = '%s:%s%s' % (options.aggregator, options.metric, tags)

    b_now = get_bucket(options, metric, 0)
    b_old = get_bucket(options, metric, options.buckets_ago)
    change = ((float(b_now) / b_old) - 1) * 100
    if options.bucket_abs:
        cchange = abs(change)
    else:
        cchange = change
    if options.verbose:
        print 'bucket now=%r old=%r change=%r' % (b_now, b_old, change)

    tmetric = metric.replace('|',':')
    if comparator(cchange, options.critical):
        print ('CRITICAL: %s %s %s: bucket changed %.2f%%'
               % (tmetric, options.comparator, options.critical, change))
        return 2
    elif comparator(cchange, options.warning):
        print ('WARNING: %s %s %s: bucket changed %.2f%%'
               % (tmetric, options.comparator, options.warning, change))
        return 1
    else:
        print 'OK: %s: bucket changed %.2f%%' % (tmetric, change)
        return 0


def recent_check(options, comparator):
    '''A recent check looks only at the recent data (as specified in the
    options) and alerts based on that data.

    '''
    tags = ','.join(options.tags)
    if tags:
        tags = '{' + tags + '}'
    if options.rate:
        options.metric = 'rate:' + options.metric
    if options.downsample == 'none':
        downsampling = ''
    else:
        downsampling = ':%ds-%s' % (options.duration, options.downsample)
    metric = '%s%s:%s%s' % (options.aggregator, downsampling, options.metric,
                            tags)
    url = ('/q?start=%ss-ago&m=%s&ascii&nagios' % (options.duration, metric))
    datapoints = get_datapoints(options, url)

    def no_data_point():
        if options.no_result_ok:
            print 'OK: query did not return any data point (--no-result-ok)'
            return 0
        else:
            print 'CRITICAL: query did not return any data point'
            return 2

    if not len(datapoints):
        return no_data_point()

    now = int(time.time())
    rv = 0         # Return value for this script
    bad = None     # Bad data point
    npoints = 0    # How many values have we seen?
    nbad = 0       # How many bad values have we seen?
    oldest = [None, None] # Closest value to our duration (for delta)
    newest = [None, None] # Newest data point (past ignore_recent)
    points = {'critical': [], 'warning': [], 'okay': []}
    for datapoint in datapoints:
        ts, val = datapoint

        delta = now - ts
        if delta > options.duration or delta <= options.ignore_recent:
            continue  # Ignore data points outside of our range.
        if oldest[0] is None or delta > oldest[0]:
            oldest = [delta, val]
        if newest[0] is None or delta < newest[0]:
            newest = [delta, val]
        npoints += 1

        if options.delta:
            continue

        state = 'okay'
        if comparator(val, options.critical):
            state = 'critical'
        elif comparator(val, options.warning):
            state = 'warning'
        points[state].append(val)

        # Store the worst value.
        if (state != 'okay' and
            (bad is None  # First bad value we find.
               or comparator(val, bad[1]))):  # Worst value.
            bad = datapoint

    if options.verbose:
        if len(datapoints) != npoints:
            print ('ignored %d/%d data points for being more than %ds old or too new'
                   % (len(datapoints) - npoints, len(datapoints), options.duration))
        if bad is not None:
            print 'worst data point value=%s at ts=%s' % (bad[1], bad[0])
        if options.delta:
            print 'delta: oldest = [%d, %d], newest = [%d, %d]' % (
                oldest[0], oldest[1], newest[0], newest[1])

    if not npoints:
        return no_data_point()
    tmetric = metric.replace('|',':')

    # Delta comparisons happen first. We do not explicitly ignore negative
    # values because the user might want to compare against those to, f.ex.,
    # look for restarts.
    if options.delta:
        if newest[0] is None or oldest[0] is None:
            if options.no_result_ok:
                print 'OK: not enough data to compute the delta'
                return 0
            else:
                print 'CRITICAL: not enough data to compute the delta'
                return 2
        delta = newest[1] - oldest[1]
        if comparator(delta, options.critical):
            print 'CRITICAL: %s delta is %s %s: currently %d over %d seconds' % (
                tmetric, options.comparator, options.critical, delta, options.duration)
            return 2
        elif comparator(delta, options.warning):
            print 'WARNING: %s delta is %s %s: currently %d over %d seconds' % (
                tmetric, options.comparator, options.warning, delta, options.duration)
            return 1
        else:
            print 'OK: %s delta is currently %d over %d seconds' % (tmetric,
                delta, options.duration)
            return 0

    # Determine return value.  We have to add the number of critical points
    # to the warning points because the criticals may not cross the
    # percent_over threshold on their own, downgrading this to a WARNING.
    ncrit = len(points['critical'])
    nwarn = len(points['warning']) + ncrit
    if ncrit > 0 and (float(ncrit) / npoints > options.percent_over):
        rv = 2
        nbad = ncrit
    elif nwarn > 0 and (float(nwarn) / npoints > options.percent_over):
        rv = 1
        nbad = nwarn

    # In nrpe, pipe character is something special, but it's used in tag
    # searches.  Translate it to something else for the purposes of output.
    if not rv:
        print ('OK: %s: %d values OK, last=%r' % (tmetric, npoints, val))
    else:
        if rv == 1:
            level ='WARNING'
            threshold = options.warning
        elif rv == 2:
            level = 'CRITICAL'
            threshold = options.critical
        print ('%s: %s %s %s: %d/%d bad values (%.1f%%) worst: %r @ %s'
               % (level, tmetric, options.comparator, threshold,
                  nbad, npoints, nbad * 100.0 / npoints, bad[1],
                  time.asctime(time.localtime(bad[0]))))
    return rv


def get_datapoints(options, url):
    '''Connect to TSD and get data. If a fatal error is encountered,
    this will call sys.exit automatically with a proper Nagios code.

    '''
    tsd = '%s:%d' % (options.host, options.port)
    if sys.version_info[0] * 10 + sys.version_info[1] >= 26:  # Python >2.6
        conn = httplib.HTTPConnection(tsd, timeout=options.timeout)
    else:  # Python 2.5 or less, using the timeout kwarg will make it croak :(
        conn = httplib.HTTPConnection(tsd)
    try:
        conn.connect()
    except socket.error, e:
        print 'ERROR: couldn\'t connect to %s: %s' % (tsd, e)
        sys.exit(2)
    if options.verbose:
        print 'Connected to %s:%d' % conn.sock.getpeername()
        conn.set_debuglevel(1)
    try:
        conn.request('GET', url)
        res = conn.getresponse()
        datapoints = res.read()
        conn.close()
    except socket.error, e:
        print 'ERROR: couldn\'t GET %s from %s: %s' % (url, tsd, e)
        sys.exit(2)

    if res.status != 200:
        print 'CRITICAL: status = %d when talking to %s:%d' % (res.status, options.host, options.port)
        if options.verbose:
            print 'TSD said:'
            print datapoints
        sys.exit(2)

    if options.verbose:
        print datapoints
    datapoints = datapoints.splitlines()

    ret = []
    for datapoint in datapoints:
        datapoint = datapoint.split()
        ts = int(datapoint[1])
        val = datapoint[2]
        if '.' in val:
            val = float(val)
        else:
            val = int(val)
        ret.append((ts, val))
    return ret


if __name__ == '__main__':
    sys.exit(main(sys.argv))
