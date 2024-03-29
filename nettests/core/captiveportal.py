# -*- coding: utf-8 -*-
"""
    captiveportal
    *************

    This test is a collection of tests to detect the presence of a
    captive portal. Code is taken, in part, from the old ooni-probe,
    which was written by Jacob Appelbaum and Arturo Filastò.

    This module performs multiple tests that match specific vendor captive
    portal tests. This is a basic internet captive portal filter tester written
    for RECon 2011.

    Read the following URLs to understand the captive portal detection process
    for various vendors:

    http://technet.microsoft.com/en-us/library/cc766017%28WS.10%29.aspx
    http://blog.superuser.com/2011/05/16/windows-7-network-awareness/
    http://isc.sans.org/diary.html?storyid=10312&
    http://src.chromium.org/viewvc/chrome?view=rev&revision=74608
    http://code.google.com/p/chromium-os/issues/detail?3281ttp,
    http://crbug.com/52489
    http://crbug.com/71736
    https://bugzilla.mozilla.org/show_bug.cgi?id=562917
    https://bugzilla.mozilla.org/show_bug.cgi?id=603505
    http://lists.w3.org/Archives/Public/ietf-http-wg/2011JanMar/0086.html
    http://tools.ietf.org/html/draft-nottingham-http-portal-02

    :copyright: (c) 2012 Isis Lovecruft
    :license: see LICENSE for more details
"""
import base64
import os
import random
import re
import string
import urllib2
from urlparse import urlparse

from ooni import nettest
from ooni.templates import httpt
from ooni.utils import log

try:
    from dns import resolver
except ImportError:
    print "The dnspython module was not found:"
    print "See https://crate.io/packages/dnspython/"
    resolver = None

__plugoo__ = "captiveportal"
__desc__ = "Captive portal detection test"

optParameters = [['asset', 'a', None, 'Asset file'],
                 ['experiment-url', 'e', 'http://google.com/', 'Experiment URL'],
                 ['user-agent', 'u', random.choice(httpt.useragents),
                  'User agent for HTTP requests']
                ]

class CaptivePortal(nettest.NetTestCase):
    """
    Compares content and status codes of HTTP responses, and attempts
    to determine if content has been altered.
    """

    name = "captivep"
    description = "Captive Portal Test"
    requirements = None

    def http_fetch(self, url, headers={}):
        """
        Parses an HTTP url, fetches it, and returns a urllib2 response
        object.
        """
        url = urlparse(url).geturl()
        request = urllib2.Request(url, None, headers)
        response = urllib2.urlopen(request)
        response_headers = dict(response.headers)
        return response, response_headers

    def http_content_match_fuzzy_opt(self, experimental_url, control_result,
                                     headers=None, fuzzy=False):
        """
        Makes an HTTP request on port 80 for experimental_url, then
        compares the response_content of experimental_url with the
        control_result. Optionally, if the fuzzy parameter is set to
        True, the response_content is compared with a regex of the
        control_result. If the response_content from the
        experimental_url and the control_result match, returns True
        with the HTTP status code and headers; False, status code, and
        headers if otherwise.
        """

        if headers is None:
            default_ua = self.local_options['user-agent']
            headers = {'User-Agent': default_ua}

        response, response_headers = self.http_fetch(experimental_url, headers)
        response_content = response.read()
        response_code = response.code
        if response_content is None:
            log.warn("HTTP connection appears to have failed.")
            return False, False, False

        if fuzzy:
            pattern = re.compile(control_result)
            match = pattern.search(response_content)
            log.msg("Fuzzy HTTP content comparison for experiment URL")
            log.msg("'%s'" % experimental_url)
            if not match:
                log.msg("does not match!")
                return False, response_code, response_headers
            else:
                log.msg("and the expected control result yielded a match.")
                return True, response_code, response_headers
        else:
            if str(response_content) != str(control_result):
                log.msg("HTTP content comparison of experiment URL")
                log.msg("'%s'" % experimental_url)
                log.msg("and the expected control result do not match.")
                return False, response_code, response_headers
            else:
                return True, response_code, response_headers

    def http_status_code_match(self, experiment_code, control_code):
        """
        Compare two HTTP status codes, returns True if they match.
        """
        return int(experiment_code) == int(control_code)

    def http_status_code_no_match(self, experiment_code, control_code):
        """
        Compare two HTTP status codes, returns True if they do not match.
        """
        return int(experiment_code) != int(control_code)

    def dns_resolve(self, hostname, nameserver=None):
        """
        Resolves hostname(s) though nameserver to corresponding
        address(es). hostname may be either a single hostname string,
        or a list of strings. If nameserver is not given, use local
        DNS resolver, and if that fails try using 8.8.8.8.
        """
        if not resolver:
            log.msg("dnspython is not installed.\
                    Cannot perform DNS Resolve test")
            return []
        if isinstance(hostname, str):
            hostname = [hostname]

        if nameserver is not None:
            res = resolver.Resolver(configure=False)
            res.nameservers = [nameserver]
        else:
            res = resolver.Resolver()

        response = []
        answer = None

        for hn in hostname:
            try:
                answer = res.query(hn)
            except resolver.NoNameservers:
                res.nameservers = ['8.8.8.8']
                try:
                    answer = res.query(hn)
                except resolver.NXDOMAIN:
                    log.msg("DNS resolution for %s returned NXDOMAIN" % hn)
                    response.append('NXDOMAIN')
            except resolver.NXDOMAIN:
                log.msg("DNS resolution for %s returned NXDOMAIN" % hn)
                response.append('NXDOMAIN')
            finally:
                if not answer:
                    return response
                for addr in answer:
                    response.append(addr.address)
        return response

    def dns_resolve_match(self, experiment_hostname, control_address):
        """
        Resolve experiment_hostname, and check to see that it returns
        an experiment_address which matches the control_address.  If
        they match, returns True and experiment_address; otherwise
        returns False and experiment_address.
        """
        experiment_address = self.dns_resolve(experiment_hostname)
        if not experiment_address:
            log.debug("dns_resolve() for %s failed" % experiment_hostname)
            return None, experiment_address

        if len(set(experiment_address) & set([control_address])) > 0:
            return True, experiment_address
        else:
            log.msg("DNS comparison of control '%s' does not" % control_address)
            log.msg("match experiment response '%s'" % experiment_address)
            return False, experiment_address

    def get_auth_nameservers(self, hostname):
        """
        Many CPs set a nameserver to be used. Let's query that
        nameserver for the authoritative nameservers of hostname.

        The equivalent of:
        $ dig +short NS ooni.nu
        """
        if not resolver:
            log.msg("dnspython not installed.")
            log.msg("Cannot perform test.")
            return []

        res = resolver.Resolver()
        answer = res.query(hostname, 'NS')
        auth_nameservers = []
        for auth in answer:
            auth_nameservers.append(auth.to_text())
        return auth_nameservers

    def hostname_to_0x20(self, hostname):
        """
        MaKEs yOur HOsTnaME lOoK LiKE THis.

        For more information, see:
        D. Dagon, et. al. "Increased DNS Forgery Resistance
        Through 0x20-Bit Encoding". Proc. CSS, 2008.
        """
        hostname_0x20 = ''
        for char in hostname:
            l33t = random.choice(['caps', 'nocaps'])
            if l33t == 'caps':
                hostname_0x20 += char.capitalize()
            else:
                hostname_0x20 += char.lower()
        return hostname_0x20

    def check_0x20_to_auth_ns(self, hostname, sample_size=None):
        """
        Resolve a 0x20 DNS request for hostname over hostname's
        authoritative nameserver(s), and check to make sure that
        the capitalization in the 0x20 request matches that of the
        response. Also, check the serial numbers of the SOA (Start
        of Authority) records on the authoritative nameservers to
        make sure that they match.

        If sample_size is given, a random sample equal to that number
        of authoritative nameservers will be queried; default is 5.
        """
        log.msg("")
        log.msg("Testing random capitalization of DNS queries...")
        log.msg("Testing that Start of Authority serial numbers match...")

        auth_nameservers = self.get_auth_nameservers(hostname)

        if sample_size is None:
            sample_size = 5
            resolved_auth_ns = random.sample(self.dns_resolve(auth_nameservers),
                                             sample_size)

        querynames = []
        answernames = []
        serials = []

        # Even when gevent monkey patching is on, the requests here
        # are sent without being 0x20'd, so we need to 0x20 them.
        hostname = self.hostname_to_0x20(hostname)

        for auth_ns in resolved_auth_ns:
            res = resolver.Resolver(configure=False)
            res.nameservers = [auth_ns]
            try:
                answer = res.query(hostname, 'SOA')
            except resolver.Timeout:
                continue
            querynames.append(answer.qname.to_text())
            answernames.append(answer.rrset.name.to_text())
            for soa in answer:
                serials.append(str(soa.serial))

        if len(set(querynames).intersection(answernames)) == 1:
            log.msg("Capitalization in DNS queries and responses match.")
            name_match = True
        else:
            log.msg("The random capitalization '%s' used in" % hostname)
            log.msg("DNS queries to that hostname's authoritative")
            log.msg("nameservers does not match the capitalization in")
            log.msg("the response.")
            name_match = False

        if len(set(serials)) == 1:
            log.msg("Start of Authority serial numbers all match.")
            serial_match = True
        else:
            log.msg("Some SOA serial numbers did not match the rest!")
            serial_match = False

        ret = name_match, serial_match, querynames, answernames, serials

        if name_match and serial_match:
            log.msg("Your DNS queries do not appear to be tampered.")
            return ret
        elif name_match or serial_match:
            log.msg("Something is tampering with your DNS queries.")
            return ret
        elif not name_match and not serial_match:
            log.msg("Your DNS queries are definitely being tampered with.")
            return ret

    def get_random_url_safe_string(self, length):
        """
        Returns a random url-safe string of specified length, where
        0 < length <= 256. The returned string will always start with
        an alphabetic character.
        """
        if (length <= 0):
            length = 1
        elif (length > 256):
            length = 256

        random_ascii = base64.urlsafe_b64encode(os.urandom(int(length)))

        while not random_ascii[:1].isalpha():
            random_ascii = base64.urlsafe_b64encode(os.urandom(int(length)))

        three_quarters = int((len(random_ascii)) * (3.0/4.0))
        random_string = random_ascii[:three_quarters]
        return random_string

    def get_random_hostname(self, length=None):
        """
        Returns a random hostname with SLD of specified length. If
        length is unspecified, length=32 is used.

        These *should* all resolve to NXDOMAIN. If they actually
        resolve to a box that isn't part of a captive portal that
        would be rather interesting.
        """
        if length is None:
            length = 32

        random_sld = self.get_random_url_safe_string(length)

        # if it doesn't start with a letter, chuck it.
        while not random_sld[:1].isalpha():
            random_sld = self.get_random_url_safe_string(length)

        tld_list = ['.com', '.net', '.org', '.info', '.test', '.invalid']
        random_tld = urllib2.random.choice(tld_list)
        random_hostname = random_sld + random_tld
        return random_hostname

    def compare_random_hostnames(self, hostname_count=None, hostname_length=None):
        """
        Get hostname_count number of random hostnames with SLD length
        of hostname_length, and then attempt DNS resolution. If no
        arguments are given, default to three hostnames of 32 bytes
        each. These random hostnames *should* resolve to NXDOMAIN,
        except in the case where a user is presented with a captive
        portal and remains unauthenticated, in which case the captive
        portal may return the address of the authentication page.

        If the cardinality of the intersection of the set of resolved
        random hostnames and the single element control set
        (['NXDOMAIN']) are equal to one, then DNS properly resolved.

        Returns true if only NXDOMAINs were returned, otherwise returns
        False with the relative complement of the control set in the
        response set.
        """
        if hostname_count is None:
            hostname_count = 3

        log.msg("Generating random hostnames...")
        log.msg("Resolving DNS for %d random hostnames..." % hostname_count)

        control = ['NXDOMAIN']
        responses = []

        for x in range(hostname_count):
            random_hostname = self.get_random_hostname(hostname_length)
            response_match, response_address = self.dns_resolve_match(random_hostname,
                                                                      control[0])
            for address in response_address:
                if response_match is False:
                    log.msg("Strangely, DNS resolution of the random hostname")
                    log.msg("%s actually points to %s"
                             % (random_hostname, response_address))
                    responses = responses + [address]
                else:
                    responses = responses + [address]

        intersection = set(responses) & set(control)
        relative_complement = set(responses) - set(control)
        r = set(responses)

        if len(intersection) == 1:
            log.msg("All %d random hostnames properly resolved to NXDOMAIN."
                     % hostname_count)
            return True, relative_complement
        elif (len(intersection) == 1) and (len(r) > 1):
            log.msg("Something odd happened. Some random hostnames correctly")
            log.msg("resolved to NXDOMAIN, but several others resolved to")
            log.msg("to the following addresses: %s" % relative_complement)
            return False, relative_complement
        elif (len(intersection) == 0) and (len(r) == 1):
            log.msg("All random hostnames resolved to the IP address ")
            log.msg("'%s', which is indicative of a captive portal." % r)
            return False, relative_complement
        else:
            log.debug("Apparently, pigs are flying on your network, 'cause a")
            log.debug("bunch of hostnames made from 32-byte random strings")
            log.debug("just magically resolved to a bunch of random addresses.")
            log.debug("That is definitely highly improbable. In fact, my napkin")
            log.debug("tells me that the probability of just one of those")
            log.debug("hostnames resolving to an address is 1.68e-59, making")
            log.debug("it nearly twice as unlikely as an MD5 hash collision.")
            log.debug("Either someone is seriously messing with your network,")
            log.debug("or else you are witnessing the impossible. %s" % r)
            return False, relative_complement

    def google_dns_cp_test(self):
        """
        Google Chrome resolves three 10-byte random hostnames.
        """
        subtest = "Google Chrome DNS-based"

        log.msg("")
        log.msg("Running the Google Chrome DNS-based captive portal test...")

        gmatch, google_dns_result = self.compare_random_hostnames(3, 10)

        if gmatch:
            log.msg("Google Chrome DNS-based captive portal test did not")
            log.msg("detect a captive portal.")
            return google_dns_result
        else:
            log.msg("Google Chrome DNS-based captive portal test believes")
            log.msg("you are in a captive portal, or else something very")
            log.msg("odd is happening with your DNS.")
            return google_dns_result

    def ms_dns_cp_test(self):
        """
        Microsoft "phones home" to a server which will always resolve
        to the same address.
        """
        subtest = "Microsoft NCSI DNS-based"

        log.msg("")
        log.msg("Running the Microsoft NCSI DNS-based captive portal")
        log.msg("test...")

        msmatch, ms_dns_result = self.dns_resolve_match("dns.msftncsi.com",
                                                        "131.107.255.255")
        if msmatch:
            log.msg("Microsoft NCSI DNS-based captive portal test did not")
            log.msg("detect a captive portal.")
            return ms_dns_result
        else:
            log.msg("Microsoft NCSI DNS-based captive portal test ")
            log.msg("believes you are in a captive portal.")
            return ms_dns_result

    def run_vendor_dns_tests(self):
        """
        Run the vendor DNS tests.
        """
        report = {}
        report['google_dns_cp'] = self.google_dns_cp_test()
        report['ms_dns_cp'] = self.ms_dns_cp_test()

        return report

    def run_vendor_tests(self, *a, **kw):
        """
        These are several vendor tests used to detect the presence of
        a captive portal. Each test compares HTTP status code and
        content to the control results and has its own User-Agent
        string, in order to emulate the test as it would occur on the
        device it was intended for. Vendor tests are defined in the
        format:
        [exp_url, ctrl_result, ctrl_code, ua, test_name]
        """

        vendor_tests = [['http://www.apple.com/library/test/success.html',
                         'Success',
                         '200',
                         'Mozilla/5.0 (iPhone; U; CPU like Mac OS X; en) AppleWebKit/420+ (KHTML, like Gecko) Version/3.0 Mobile/1A543a Safari/419.3',
                         'Apple HTTP Captive Portal'],
                        ['http://tools.ietf.org/html/draft-nottingham-http-portal-02',
                         '428 Network Authentication Required',
                         '428',
                         'Mozilla/5.0 (Windows NT 6.1; rv:5.0) Gecko/20100101 Firefox/5.0',
                         'W3 Captive Portal'],
                        ['http://www.msftncsi.com/ncsi.txt',
                         'Microsoft NCSI',
                         '200',
                         'Microsoft NCSI',
                         'MS HTTP Captive Portal',]]

        cm = self.http_content_match_fuzzy_opt
        sm = self.http_status_code_match
        snm = self.http_status_code_no_match

        def compare_content(status_func, fuzzy, experiment_url, control_result,
                            control_code, headers, test_name):
            log.msg("")
            log.msg("Running the %s test..." % test_name)

            content_match, experiment_code, experiment_headers = cm(experiment_url,
                                                                    control_result,
                                                                    headers, fuzzy)
            status_match = status_func(experiment_code, control_code)

            if status_match and content_match:
                log.msg("The %s test was unable to detect" % test_name)
                log.msg("a captive portal.")
                return True
            else:
                log.msg("The %s test shows that your network" % test_name)
                log.msg("is filtered.")
                return False

        result = []
        for vt in vendor_tests:
            report = {}
            report['vt'] = vt

            experiment_url = vt[0]
            control_result = vt[1]
            control_code = vt[2]
            headers = {'User-Agent': vt[3]}
            test_name = vt[4]

            args = (experiment_url, control_result, control_code, headers, test_name)

            if test_name == "MS HTTP Captive Portal":
                report['result'] = compare_content(sm, False, *args)

            elif test_name == "Apple HTTP Captive Portal":
                report['result'] = compare_content(sm, True, *args)

            elif test_name == "W3 Captive Portal":
                report['result'] = compare_content(snm, True, *args)

            else:
                log.warn("Ooni is trying to run an undefined CP vendor test.")
            result.append(report)
        return result

    def control(self, experiment_result, args):
        """
        Compares the content and status code of the HTTP response for
        experiment_url with the control_result and control_code
        respectively. If the status codes match, but the experimental
        content and control_result do not match, fuzzy matching is enabled
        to determine if the control_result is at least included somewhere
        in the experimental content. Returns True if matches are found,
        and False if otherwise.
        """
        # XXX put this back to being parametrized
        #experiment_url = self.local_options['experiment-url']
        experiment_url = 'http://google.com/'
        control_result = 'XX'
        control_code = 200
        ua = self.local_options['user-agent']

        cm = self.http_content_match_fuzzy_opt
        sm = self.http_status_code_match
        snm = self.http_status_code_no_match

        log.msg("Running test for '%s'..." % experiment_url)
        content_match, experiment_code, experiment_headers = cm(experiment_url,
                                                                control_result)
        status_match = sm(experiment_code, control_code)
        if status_match and content_match:
            log.msg("The test for '%s'" % experiment_url)
            log.msg("was unable to detect a captive portal.")

            self.report['result'] = True

        elif status_match and not content_match:
            log.msg("Retrying '%s' with fuzzy match enabled."
                     % experiment_url)
            fuzzy_match, experiment_code, experiment_headers = cm(experiment_url,
                                                                  control_result,
                                                                  fuzzy=True)
            if fuzzy_match:
                self.report['result'] = True
            else:
                log.msg("Found modified content on '%s'," % experiment_url)
                log.msg("which could indicate a captive portal.")

                self.report['result'] = False
        else:
            log.msg("The content comparison test for ")
            log.msg("'%s'" % experiment_url)
            log.msg("shows that your HTTP traffic is filtered.")

            self.report['result'] = False

    def test_captive_portal(self):
        """
        Runs the CaptivePortal(Test).

        CONFIG OPTIONS
        --------------

        If "do_captive_portal_vendor_tests" is set to "true", then vendor
        specific captive portal HTTP-based tests will be run.

        If "do_captive_portal_dns_tests" is set to "true", then vendor
        specific captive portal DNS-based tests will be run.

        If "check_dns_requests" is set to "true", then Ooni-probe will
        attempt to check that your DNS requests are not being tampered with
        by a captive portal.

        If "captive_portal" = "yourfilename.txt", then user-specified tests
        will be run.

        Any combination of the above tests can be run.
        """

        log.msg("")
        log.msg("Running vendor tests...")
        self.report['vendor_tests'] = self.run_vendor_tests()

        log.msg("")
        log.msg("Running vendor DNS-based tests...")
        self.report['vendor_dns_tests'] = self.run_vendor_dns_tests()

        log.msg("")
        log.msg("Checking that DNS requests are not being tampered...")
        self.report['check0x20'] = self.check_0x20_to_auth_ns('ooni.nu')

        log.msg("")
        log.msg("Captive portal test finished!")

        self.control(self.report)

