#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import json

from components.logging import logEntryExit
from components.providerbase import BaseProvider, INeedsCommandProvider, INeedsLoggingProvider


class PhabricatorProvider(BaseProvider, INeedsCommandProvider, INeedsLoggingProvider):
    def __init__(self, config):
        pass

    @logEntryExit
    def submit_patch(self):
        ret = self.run(["arc", "diff", "--verbatim"])
        output = ret.stdout.decode()

        isNext = False
        phab_revision = "Unknown"
        for l in output.split("\n"):
            if isNext:
                phab_revision = l.split(" ")[0].replace("(D", "").replace(")", "")
                break
            if "Completed" == l.strip():
                isNext = True

        return phab_revision

    @logEntryExit
    def set_reviewer(self, phab_revision, phab_username):
        # First get the user's phid
        cmd = """echo '{"constraints": {"usernames":["%s"]}}' | arc call-conduit user.search""" \
            % (phab_username)
        ret = self.run([cmd], shell=True)
        result = json.loads(ret.stdout.decode())
        if result['error']:
            raise Exception("Got an error from phabricator when trying to search for %s" % (phab_username))

        assert 'response' in result
        assert 'data' in result['response']
        if len(result['response']['data']) != 1:
            raise Exception("When querying conduit for username %s, we got back %i results"
                            % (phab_username, len(result['data'])))

        phid = result['response']['data'][0]['phid']

        cmd = """echo '{"transactions": [{"type":"reviewers.set", "value":["%s"]}], "objectIdentifier": "%s"}' | arc call-conduit differential.revision.edit""" \
            % (phid, phab_revision)
        ret = self.run([cmd], shell=True)
        result = json.loads(ret.stdout.decode())
        if result['error']:
            raise Exception("Got an error from phabricator when trying to set reviewers to %s (%s) for %s: %s" % (phab_username, phid, phab_revision, result))

    @logEntryExit
    def abandon(self, phab_revision):
        cmd = """echo '{"transactions": [{"type":"abandon", "value":true}],"objectIdentifier": "%s"}' | arc call-conduit differential.revision.edit""" \
            % phab_revision
        ret = self.run([cmd], shell=True)
        result = json.loads(ret.stdout.decode())
        if result['error']:
            raise Exception("Got an error from phabricator when trying to abandon %s: %s" % (phab_revision, result))
