#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import re
import json

from components.logging import logEntryExit, LogLevel
from components.providerbase import BaseProvider, INeedsCommandProvider, INeedsLoggingProvider


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
    def submit_patch(self, bug_id):
        ret = self.run(["arc", "diff", "--verbatim", "--conduit-uri", self.url, "--"])
        output = ret.stdout.decode()

        phab_revision = None
        r = re.compile(self.url + "D([0-9]+)")
        for line in output.split("\n"):
            s = r.search(line)
            if s:
                phab_revision = s.groups(0)[0]
                break

        if not phab_revision:
            raise Exception("Could not find a phabricator revision in the output of arc diff using regex %s" % r.pattern)

        cmd = """echo '{"transactions": [{"type":"bugzilla.bug-id", "value":"%s"}], "objectIdentifier": "%s"}' | arc call-conduit --conduit-uri='%s' differential.revision.edit --""" \
            % (bug_id, phab_revision, self.url)
        ret = self.run([cmd], shell=True)
        result = json.loads(ret.stdout.decode())
        if result['error']:
            raise Exception("Got an error from phabricator when trying to set the bugzilla id for %s" % (phab_revision))

        self.logger.log("Submitted phabricator patch at {0}".format(self.url + phab_revision), level=LogLevel.Info)
        return phab_revision

    @logEntryExit
    def set_reviewer(self, phab_revision, phab_username):
        # First get the user's phid
        cmd = """echo '{"constraints": {"usernames":["%s"]}}' | arc call-conduit --conduit-uri='%s' user.search --""" \
            % (phab_username, self.url)
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

        cmd = """echo '{"transactions": [{"type":"reviewers.set", "value":["%s"]}], "objectIdentifier": "%s"}' | arc call-conduit --conduit-uri='%s' differential.revision.edit --""" \
            % (phid, phab_revision, self.url)
        ret = self.run([cmd], shell=True)
        result = json.loads(ret.stdout.decode())
        if result['error']:
            raise Exception("Got an error from phabricator when trying to set reviewers to %s (%s) for %s: %s" % (phab_username, phid, phab_revision, result))

    @logEntryExit
    def abandon(self, phab_revision):
        cmd = """echo '{"transactions": [{"type":"abandon", "value":true}],"objectIdentifier": "%s"}' | arc call-conduit --conduit-uri='%s' differential.revision.edit --""" \
            % (phab_revision, self.url)
        ret = self.run([cmd], shell=True)
        result = json.loads(ret.stdout.decode())
        if result['error']:
            if "You can not abandon this revision because it has already been closed." in result['errorMessage']:
                self.logger.log("Strangely, the phabricator revision %s was already closed when we tried to abandon it. Oh well." % phab_revision, level=LogLevel.Warning)
            else:
                raise Exception("Got an error from phabricator when trying to abandon %s: %s" % (phab_revision, result))
