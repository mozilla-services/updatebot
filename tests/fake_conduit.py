#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""
A fake Phabricator Conduit API, enough for the real `arc diff` and `arc call-conduit`
to submit and edit revisions against it, so tests can run Updatebot with the real
arc. Responses follow the shapes in Phabricator's source (phacility/phabricator,
src/applications/*/conduit/). Every call is recorded in `calls`; a method it doesn't
implement is answered with an error, so a new call from arc fails loudly.
"""

import json
import base64
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

USER_PHID = "PHID-USER-updatebot0000000000"


class ConduitError(Exception):
    def __init__(self, code, info):
        super().__init__(info)
        self.code, self.info = code, info


class FakeConduit:
    def __init__(self):
        self.calls = []
        self.diffs = {}
        self.revisions = {}
        self.files = {}
        self.users = {USER_PHID: "updatebot"}
        self.projects = {}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = "http://127.0.0.1:%d/" % self.server.server_address[1]
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def methods_called(self):
        return [method for method, _ in self.calls]

    # ==================================================================
    def _handler(self):
        conduit = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
                form = urllib.parse.parse_qs(body)
                params = json.loads(form.get("params", ["{}"])[0])
                params.pop("__conduit__", None)
                method = self.path.split("/api/", 1)[-1]
                conduit.calls.append((method, params))
                handler = getattr(conduit, "_" + method.replace(".", "_"), None)
                if handler:
                    try:
                        response = {"result": handler(params), "error_code": None, "error_info": None}
                    except ConduitError as e:
                        response = {"result": None, "error_code": e.code, "error_info": e.info}
                    except Exception as e:
                        response = {"result": None, "error_code": "ERR-FAKE-CONDUIT",
                                    "error_info": "The fake Conduit server failed handling %s: %r" % (method, e)}
                else:
                    response = {"result": None, "error_code": "ERR-FAKE-CONDUIT",
                                "error_info": "The fake Conduit server doesn't implement %s" % method}
                out = json.dumps(response).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *args):
                pass

        return Handler

    # ==================================================================
    # People
    def _user_whoami(self, params):
        return {"phid": USER_PHID, "userName": "updatebot", "realName": "Updatebot",
                "primaryEmail": "updatebot@example.com", "roles": ["verified", "approved", "activated"]}

    def _user_search(self, params):
        names = params.get("constraints", {}).get("usernames", [])
        return {"data": [{"id": i, "type": "USER", "phid": phid, "fields": {"username": name}}
                         for i, (phid, name) in enumerate(self.users.items(), 1) if name in names],
                "cursor": {"after": None}}

    def _project_search(self, params):
        slugs = [s.lstrip("#") for s in params.get("constraints", {}).get("slugs", [])]
        return {"data": [{"id": i, "type": "PROJ", "phid": phid, "fields": {"slug": slug}}
                         for i, (phid, slug) in enumerate(self.projects.items(), 1) if slug in slugs],
                "cursor": {"after": None}}

    # ==================================================================
    # Differential: what `arc diff` calls to create a revision
    def _differential_parsecommitmessage(self, params):
        corpus = params["corpus"]
        title, _, summary = corpus.partition("\n")
        fields = {"title": title.strip(), "summary": summary.strip()}
        revision_id = None
        for line in corpus.splitlines():
            if line.startswith("Differential Revision:"):
                revision_id = int(line.rsplit("/D", 1)[1])
                fields["revisionID"] = revision_id
        return {"errors": [], "fields": fields,
                "revisionIDFieldInfo": {"value": revision_id, "validDomain": self.url},
                "transactions": [{"type": "title", "value": fields["title"]},
                                 {"type": "summary", "value": fields["summary"]}]}

    def _repository_query(self, params):
        # Firefox's .arcconfig names its repository by callsign. Mozilla's has no
        # staging area, as `arc diff` reports in Updatebot's logs.
        return [{"id": 1, "name": callsign, "phid": "PHID-REPO-%s" % callsign, "callsign": callsign,
                 "monogram": "r" + callsign, "vcs": "hg", "uri": self.url + "source/%s/" % callsign,
                 "remoteURI": "", "description": "", "isActive": True, "isHosted": False, "isImporting": False,
                 "encoding": "UTF-8", "staging": {"supported": True, "prefix": "phabricator", "uri": None}}
                for callsign in params.get("callsigns", [])]

    def _differential_creatediff(self, params):
        diff_id = len(self.diffs) + 1
        self.diffs[diff_id] = params
        return {"diffid": diff_id, "phid": "PHID-DIFF-%020d" % diff_id,
                "uri": self.url + "differential/diff/%d/" % diff_id}

    def _differential_setdiffproperty(self, params):
        return None

    def _harbormaster_queryautotargets(self, params):
        return {"targetMap": {}}

    def _differential_getcommitmessage(self, params):
        if params.get("revision_id"):
            revision = self.revisions[int(params["revision_id"])]
            fields = {"title": revision["title"], "summary": revision["summary"]}
        else:  # A new revision's message, from the fields parsed out of the commit
            revision, fields = None, params.get("fields", {})
        message = fields.get("title", "")
        if fields.get("summary"):
            message += "\n\n" + fields["summary"]
        if revision:
            message += "\n\nDifferential Revision: %sD%d" % (self.url, revision["id"])
        return message

    # ==================================================================
    # Differential: revisions, edited by `arc diff` and by Updatebot through `arc call-conduit`
    def _differential_revision_edit(self, params):
        if params.get("objectIdentifier"):
            identifier = str(params["objectIdentifier"])
            revision = next(r for r in self.revisions.values() if identifier in (str(r["id"]), "D%d" % r["id"], r["phid"]))
        else:
            revision_id = len(self.revisions) + 1
            revision = {"id": revision_id, "phid": "PHID-DREV-%020d" % revision_id, "title": "", "summary": "",
                        "authorPHID": USER_PHID, "status": "needs-review", "diffPHIDs": [], "bugzilla.bug-id": "",
                        "parents": [], "reviewers": []}
            self.revisions[revision_id] = revision
        for xaction in params["transactions"]:
            kind, value = xaction["type"], xaction.get("value")
            if kind in ("title", "summary", "bugzilla.bug-id"):
                revision[kind] = value
            elif kind == "update":
                revision["diffPHIDs"].append(value)
            elif kind == "parents.add":
                revision["parents"].extend(value)
            elif kind == "reviewers.add":
                revision["reviewers"].extend(v for v in value if v not in revision["reviewers"])
            elif kind == "abandon":
                if revision["status"] in ("published", "abandoned"):
                    raise ConduitError("ERR-CONDUIT-CORE", "You can not abandon this revision because it has already been closed.")
                if revision["authorPHID"] != USER_PHID:
                    raise ConduitError("ERR-CONDUIT-CORE", "You can not abandon this revision because you are not the author.")
                revision["status"] = "abandoned"
            else:
                raise ConduitError("ERR-CONDUIT-CORE", "The fake Conduit server doesn't handle %s transactions" % kind)
        return {"object": {"id": revision["id"], "phid": revision["phid"]},
                "transactions": [{"phid": "PHID-XACT-DREV-%d" % i} for i, _ in enumerate(params["transactions"])]}

    def _differential_revision_search(self, params):
        constraints = params.get("constraints", {})
        ids, phids = constraints.get("ids"), constraints.get("phids")
        revisions = [r for r in self.revisions.values() if (ids is None or r["id"] in ids) and (phids is None or r["phid"] in phids)]
        return {"data": [{"id": r["id"], "type": "DREV", "phid": r["phid"],
                          "fields": {"title": r["title"], "summary": r["summary"], "authorPHID": r["authorPHID"],
                                     "status": {"value": r["status"]}, "bugzilla.bug-id": r["bugzilla.bug-id"]}}
                         for r in revisions],
                "cursor": {"after": None}}

    # ==================================================================
    # Files: how `arc diff` uploads the contents of binary files
    def _file_allocate(self, params):
        return {"upload": True, "filePHID": None}

    def _file_upload(self, params):
        phid = "PHID-FILE-%020d" % (len(self.files) + 1)
        self.files[phid] = {"name": params.get("name"), "data": base64.b64decode(params["data_base64"])}
        return phid
