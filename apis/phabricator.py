#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import re
import json
import platform

from components.utilities import retry
from components.logging import logEntryExit, LogLevel
from components.providerbase import BaseProvider, INeedsCommandProvider, INeedsLoggingProvider


def _arc():
    if platform.system() == "Windows":
        return "arc.bat"
    return "arcanist"


def quote_echo_string(s):
    if platform.system() != "Windows":
        return "'" + s + "'"
    return s


class PhabricatorProvider(BaseProvider, INeedsCommandProvider, INeedsLoggingProvider):
    def __init__(self, config):
        if 'url' not in config:
            if config['General']['env'] == "dev":
                self.url = "https://phabricator-dev.allizom.org/"
            elif config['General']['env'] == "prod":
                self.url = "https://phabricator.services.mozilla.com/"
            else:
                assert ('url' in config) or (config['General']['env'] in ["dev", "prod"]), "No phabricator url provided, and unknown operating environment"
        else:
            self.url = config['url']

    @logEntryExit
    def submit_patches(self, bug_id, has_patches):
        phab_revisions = []

        @retry
        def submit_to_phabricator(rev_id):
            cmd = [_arc(), "diff", "--verbatim", "--conduit-uri", self.url]
            if rev_id:
                cmd.append(rev_id)
            cmd.append("--")

            ret = self.run(cmd)
            output = ret.stdout.decode()

            phab_revision = False
            r = re.compile(self.url + "D([0-9]+)")
            for line in output.split("\n"):
                s = r.search(line)
                if s:
                    phab_revision = s.groups(0)[0]

            if not phab_revision:
                raise Exception("Could not find a phabricator revision in the output of arc diff using regex %s" % r.pattern)

            return phab_revision

        # arc diff will squash all commits into a single commit, so we need to jump through some hoops.
        # Conceptually, we are only commiting the top-most commit in the repo (and not any subsequent commits)
        # If we have two commits, we'll go backwards and grab only the first commit, then go back to tip
        if has_patches:
            # Checkout to the first patch
            self.run(["hg", "checkout", "tip^"])
            # Tell phabricator to submit from the base to the current working tree
            phab_revisions.append(submit_to_phabricator(""))
            # Ask hg to evolve the original second patch on top of the rewritten first patch
            self.run(["hg", "next"])

        # Submit only a single patch
        phab_revisions.append(submit_to_phabricator("tip^"))

        # Chain revisions together if needed
        @retry
        def chain_revisions(parent_rev, child_rev):
            # First get the PHID of the revision
            cmd = "echo " + quote_echo_string("""{"constraints": {"ids":[%s]}}""" % child_rev)
            cmd += " | %s call-conduit --conduit-uri=%s differential.revision.search --""" % (_arc(), self.url)

            ret = self.run(cmd, shell=True)
            try:
                result = json.loads(ret.stdout.decode())
            except Exception:
                raise Exception("Could not decode response as JSON: %s" % ret.stdout.decode())

            if result['error']:
                raise Exception("Got an error from phabricator when trying to search for %s" % (child_rev))

            assert 'response' in result
            assert 'data' in result['response']
            if len(result['response']['data']) != 1:
                raise Exception("When querying conduit for diff %s, we got back %i results"
                                % (child_rev, len(result['response']['data'])))

            child_phid = result['response']['data'][0]['phid']

            # Now connect them
            cmd = "echo " + quote_echo_string("""{"transactions": [{"type":"parents.add", "value":["%s"]}], "objectIdentifier": "%s"}""" % (child_phid, parent_rev))
            cmd += " | %s call-conduit --conduit-uri=%s differential.revision.edit --""" % (_arc(), self.url)
            ret = self.run(cmd, shell=True)
            try:
                result = json.loads(ret.stdout.decode())
            except Exception:
                raise Exception("Could not decode response as JSON: %s" % ret.stdout.decode())
            if result['error']:
                raise Exception("Got an error from phabricator when trying chain revisions, parent: %s, child %s %s" % (parent_rev, child_rev, child_phid))

        parent_rev = phab_revisions[0]
        for child_rev in phab_revisions[1:]:
            chain_revisions(parent_rev, child_rev)
            parent_rev = child_rev

        # Associate the patches with the bug
        @retry
        def associate_bug_id(phab_revision):
            cmd = "echo " + quote_echo_string("""{"transactions": [{"type":"bugzilla.bug-id", "value":"%s"}], "objectIdentifier": "%s"}""" % (bug_id, phab_revision))
            cmd += " | %s call-conduit --conduit-uri=%s differential.revision.edit --""" % (_arc(), self.url)
            ret = self.run(cmd, shell=True)
            try:
                result = json.loads(ret.stdout.decode())
            except Exception:
                raise Exception("Could not decode response as JSON: %s" % ret.stdout.decode())
            if result['error']:
                raise Exception("Got an error from phabricator when trying to set the bugzilla id for %s" % (phab_revision))

        for p in phab_revisions:
            associate_bug_id(p)

        # Done
        for p in phab_revisions:
            self.logger.log("Submitted phabricator patch at {0}".format(self.url + p), level=LogLevel.Info)
        return phab_revisions

    @logEntryExit
    @retry
    def set_reviewer(self, phab_revision, phab_username):
        # We have to call a different API endpoint if this is a review group
        if phab_username[0] == "#":
            # Get the group's phid (groups are implemented as 'projects'')
            cmd = "echo " + quote_echo_string("""{"constraints": {"slugs":["%s"]}}""" % phab_username)
            cmd += " | %s call-conduit --conduit-uri=%s project.search --""" % (_arc(), self.url)
        else:
            # Get the user's phid
            cmd = "echo " + quote_echo_string("""{"constraints": {"usernames":["%s"]}}""" % phab_username)
            cmd += " | %s call-conduit --conduit-uri=%s user.search --""" % (_arc(), self.url)

        ret = self.run(cmd, shell=True)
        try:
            result = json.loads(ret.stdout.decode())
        except Exception:
            raise Exception("Could not decode response as JSON: %s" % ret.stdout.decode())

        if result['error']:
            raise Exception("Got an error from phabricator when trying to search for %s" % (phab_username))

        assert 'response' in result
        assert 'data' in result['response']
        if len(result['response']['data']) != 1:
            raise Exception("When querying conduit for username %s, we got back %i results"
                            % (phab_username, len(result['response']['data'])))

        phid = result['response']['data'][0]['phid']

        cmd = "echo " + quote_echo_string("""{"transactions": [{"type":"reviewers.set", "value":["%s"]}], "objectIdentifier": "%s"}""" % (phid, phab_revision))
        cmd += " | %s call-conduit --conduit-uri=%s differential.revision.edit --""" % (_arc(), self.url)
        ret = self.run(cmd, shell=True)
        try:
            result = json.loads(ret.stdout.decode())
        except Exception:
            raise Exception("Could not decode response as JSON: %s" % ret.stdout.decode())
        if result['error']:
            raise Exception("Got an error from phabricator when trying to set reviewers to %s (%s) for %s: %s" % (phab_username, phid, phab_revision, result))

    @logEntryExit
    @retry
    def abandon(self, phab_revision):
        cmd = "echo " + quote_echo_string("""{"transactions": [{"type":"abandon", "value":true}],"objectIdentifier": "%s"}""" % phab_revision)
        cmd += " | %s call-conduit --conduit-uri=%s differential.revision.edit --""" % (_arc(), self.url)
        ret = self.run(cmd, shell=True)
        try:
            result = json.loads(ret.stdout.decode())
        except Exception:
            raise Exception("Could not decode response as JSON: %s" % ret.stdout.decode())
        if result['error']:
            if "You can not abandon this revision because it has already been closed." in result['errorMessage']:
                self.logger.log("Strangely, the phabricator revision %s was already closed when we tried to abandon it. Oh well." % phab_revision, level=LogLevel.Warning)
            else:
                raise Exception("Got an error from phabricator when trying to abandon %s: %s" % (phab_revision, result))
