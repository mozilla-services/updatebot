#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import re
import json

from components.utilities import retry
from components.logging import logEntryExit, LogLevel
from components.providerbase import BaseProvider, INeedsCommandProvider, INeedsLoggingProvider


def quote_echo_string(s):
    return "'" + s + "'"


# arc diff asks before submitting a file whose diff (with full-file context) is
# over 4 MiB, and aborts without a TTY. The message is wrapped across lines.
ARC_DIFF_TOO_LARGE = re.compile(r"Diff\s+for\s+'([^']+)'\s+with\s+context\s+is\s+([\d,]+)\s+bytes\s+in\s+length")


class DiffTooLargeError(Exception):
    pass


class ConduitError(Exception):
    def __init__(self, method, result):
        super().__init__("Got an error from phabricator calling %s: %s" % (method, result))
        self.error_message = result.get('errorMessage') or ""


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

    def _call_conduit(self, method, params):
        cmd = "echo " + quote_echo_string(json.dumps(params))
        cmd += " | arc call-conduit --conduit-uri=%s %s --" % (self.url, method)
        ret = self.run(cmd, shell=True)
        try:
            result = json.loads(ret.stdout)
        except Exception:
            raise Exception("Could not decode response as JSON: %s" % ret.stdout)
        if result['error']:
            raise ConduitError(method, result)
        return result['response']

    def _search_one(self, method, constraints, what):
        data = self._call_conduit(method, {"constraints": constraints})['data']
        if len(data) != 1:
            raise Exception("When querying conduit for %s, we got back %i results" % (what, len(data)))
        return data[0]

    def _edit_revision(self, phab_revision, transactions):
        return self._call_conduit("differential.revision.edit", {"transactions": transactions, "objectIdentifier": str(phab_revision)})

    # Only called from is_commandeered, which retries
    def _own_phid(self):
        if not getattr(self, '_phid', None):
            self._phid = self._call_conduit("user.whoami", {})['phid']
        return self._phid

    @logEntryExit
    @retry
    def is_commandeered(self, phab_revision):
        """Whether someone else has made themselves the author of one of our revisions."""
        revision = self._search_one("differential.revision.search", {"ids": [int(phab_revision)]}, "revision %s" % phab_revision)
        return revision['fields']['authorPHID'] != self._own_phid()

    @logEntryExit
    def submit_patches(self, bug_id, num_commits):
        phab_revisions = []

        @retry(giveup=(DiffTooLargeError,))
        def submit_to_phabricator(rev_id, retry_attempt=None):
            cmd = ["arc", "diff", "--verbatim", "--conduit-uri", self.url]
            if retry_attempt > 1:
                cmd.append("--trace")
            if rev_id:
                cmd.append(rev_id)
            cmd.append("--")

            ret = self.run(cmd, clean_return=False)
            too_large = ARC_DIFF_TOO_LARGE.search(ret.stdout)
            if too_large:
                raise DiffTooLargeError(
                    "arc diff will not submit %s because its diff is %s bytes, over arc's limit of 4 MiB for a single file."
                    % too_large.groups())
            if ret.returncode == 255 and retry_attempt > 1:
                pass  # --trace results in this return code
            else:
                ret.check_returncode()

            output = ret.stdout

            phab_revision = False
            r = re.compile(self.url + "D([0-9]+)")
            for line in output.split("\n"):
                s = r.search(line)
                if s:
                    phab_revision = s.groups(0)[0]

            if not phab_revision:
                raise Exception("Could not find a phabricator revision in the output of arc diff using regex %s" % r.pattern)

            return phab_revision

        # arc diff will squash everything from the base to the working parent into a
        # single revision, so to submit each commit as its own revision we walk the
        # stack from the bottom-most commit upward, submitting one commit at a time.
        # (num_commits is 1 for a plain vendor, 2 when there are local patches, and 3
        # when the AI added a commit resolving patch conflicts.)
        if num_commits > 1:
            # Checkout to the bottom-most commit we're submitting.
            self.run(["hg", "checkout", "tip~%d" % (num_commits - 1)])
            # Submit it as the diff from the base to the current working tree.
            phab_revisions.append(submit_to_phabricator(""))
            # Then evolve up one commit at a time, submitting each on its own.
            for _ in range(num_commits - 1):
                self.run(["hg", "next"])
                phab_revisions.append(submit_to_phabricator(".^"))
        else:
            # Submit only the single (vendoring) commit.
            phab_revisions.append(submit_to_phabricator("tip^"))

        # Chain revisions together if needed
        @retry
        def chain_revisions(parent_rev, child_rev):
            parent_phid = self._search_one("differential.revision.search", {"ids": [int(parent_rev)]}, "revision %s" % parent_rev)['phid']
            self._edit_revision(child_rev, [{"type": "parents.add", "value": [parent_phid]}])

        parent_rev = phab_revisions[0]
        for child_rev in phab_revisions[1:]:
            chain_revisions(parent_rev, child_rev)
            parent_rev = child_rev

        # Associate the patches with the bug
        @retry
        def associate_bug_id(phab_revision):
            self._edit_revision(phab_revision, [{"type": "bugzilla.bug-id", "value": str(bug_id)}])

        for p in phab_revisions:
            associate_bug_id(p)

        # Done
        for p in phab_revisions:
            self.logger.log("Submitted phabricator patch at {0}".format(self.url + p), level=LogLevel.Info)
        return phab_revisions

    @logEntryExit
    @retry
    def set_reviewer(self, phab_revision, phab_username):
        # A review group is a project, with its own search endpoint
        if phab_username[0] == "#":
            phid = self._search_one("project.search", {"slugs": [phab_username]}, "project %s" % phab_username)['phid']
        else:
            phid = self._search_one("user.search", {"usernames": [phab_username]}, "username %s" % phab_username)['phid']

        # reviewers.add, not reviewers.set: anyone already reviewing should stay a reviewer
        self._edit_revision(phab_revision, [{"type": "reviewers.add", "value": [phid]}])

    @logEntryExit
    @retry
    def abandon(self, phab_revision):
        try:
            self._edit_revision(phab_revision, [{"type": "abandon", "value": True}])
        except ConduitError as e:
            if "You can not abandon this revision because it has already been closed." in e.error_message:
                self.logger.log("Strangely, the phabricator revision %s was already closed when we tried to abandon it. Oh well." % phab_revision, level=LogLevel.Warning)
            elif "You can not abandon this revision because you are not the author." in e.error_message:
                # Someone commandeered the revision, so it's theirs to keep or abandon
                self.logger.log("The phabricator revision %s has been commandeered by someone else, so we're leaving it alone instead of abandoning it." % phab_revision, level=LogLevel.Info)
            else:
                raise
