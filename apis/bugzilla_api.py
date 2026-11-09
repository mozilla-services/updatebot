#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import json
import requests

from components.utilities import retry


def sq(s):
    return '[' + s + ']'


def kw(s):
    return sq('3pl-' + s)


def task_id_comment_tag():
    return os.environ.get('TASK_ID', 'missing')


def task_log_url():
    if "TASK_ID" not in os.environ:
        return None
    root = os.environ.get('TASKCLUSTER_ROOT_URL', 'https://firefox-ci-tc.services.mozilla.com')
    return root.rstrip('/') + '/tasks/' + os.environ['TASK_ID']


class BugzillaGatewayError(Exception):
    """Bugzilla's front end failed the request (e.g. '504 stream timeout'). The request
    may or may not have been processed."""
    pass


# Bugzilla's front end answers with these when a request times out or doesn't reach
# Bugzilla. The ones we've seen weren't processed, but that can't be relied on, so
# before retrying a write we check whether the failed attempt went through.
GATEWAY_STATUSES = (502, 503, 504)


def _raise_if_gateway_error(r, where):
    if getattr(r, "status_code", None) not in GATEWAY_STATUSES:
        return
    message = "%s: Bugzilla's front end failed the request (status=%s): %s" % (where, r.status_code, r.text[:2000])
    # We can only tell whether a write went through from the task id it was marked
    # with, so outside of Taskcluster we don't retry it
    if "TASK_ID" not in os.environ:
        raise Exception(message)
    raise BugzillaGatewayError(message)


def _bug_filed_by_this_task(url, apikey, summary):
    r = requests.get(url + "bug", params={
        'api_key': apikey,
        'f1': 'status_whiteboard', 'o1': 'substring', 'v1': 'task_id: ' + os.environ['TASK_ID'],
        'f2': 'short_desc', 'o2': 'equals', 'v2': summary,
        'include_fields': 'id'})
    # A gateway error here is retried too, and the next attempt checks again
    _raise_if_gateway_error(r, "fileBug check")
    bugs = _load_json_or_raise(r, "fileBug check")['bugs']
    return bugs[0]['id'] if bugs else None


def _comment_posted_by_this_task(url, apikey, bugID, comment):
    r = requests.get(url + "bug/" + str(bugID) + "/comment", params={'api_key': apikey})
    _raise_if_gateway_error(r, "comment check")
    bugs = _load_json_or_raise(r, "comment check")['bugs']
    for c in bugs.get(str(bugID), {}).get('comments', []):
        if os.environ['TASK_ID'] in c.get('tags', []) and c.get('text', '').strip() == comment.strip():
            return True
    return False


# Writes are retried only for gateway errors, with checks that they didn't go through
retry_write = retry(times=3, sleep_s=30, exceptions=(BugzillaGatewayError,))


class CommentRejectedError(Exception):
    """Bugzilla's web filter (not Bugzilla itself) refused the comment, with an
    empty 406 response. It has done this for comments quoting shell trace output."""
    pass


def task_id_whiteboard():
    if "TASK_ID" in os.environ:
        return sq('task_id: ' + os.environ['TASK_ID'])
    return ''


def is_prod(url):
    return "allizom" not in url


def _load_json_or_raise(r, where: str):
    # Work off bytes, decode once, tolerate bad unicode, and truncate preview.
    raw = getattr(r, "content", b"") or b""
    body = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(body)
    except Exception as e:
        status = getattr(r, "status_code", "unknown")
        ctype = getattr(r, "headers", {}).get("Content-Type", "unknown")
        preview = body[:2000]
        raise Exception(
            f"{where}: Could not decode a Bugzilla response as JSON "
            f"(status={status}, content_type={ctype}, len={len(body)}): {preview}"
        ) from e


@retry_write
def fileBug(url, apikey, ff_version, product, component, summary, description, cc_list, needinfo, see_also, depends_on, blocks, moco_confidential, mark_affected=True, retry_attempt=1):
    assert isinstance(cc_list, list)

    if retry_attempt > 1:
        filed_id = _bug_filed_by_this_task(url, apikey, summary)
        if filed_id:
            return filed_id

    data = {
        'version': "unspecified",
        'op_sys': "unspecified",

        'product': product,
        'component': component,
        'type': "enhancement",
        'summary': summary,
        'description': description,
        'whiteboard': kw('filed') + task_id_whiteboard(),
        'cc': ['tom@mozilla.com', 'jewilde@mozilla.com'] + cc_list
    }

    if is_prod(url) and mark_affected:
        data['cf_status_firefox' + str(ff_version)] = 'affected'

    if see_also:
        data['see_also'] = see_also
    if depends_on:
        data['depends_on'] = depends_on
    if blocks:
        data['blocks'] = blocks
    if moco_confidential:
        data['groups'] = ['mozilla-employee-confidential']
    if needinfo:
        data['flags'] = []
        if isinstance(needinfo, str):
            needinfo = [needinfo]

        for n in needinfo:
            data['flags'].append({
                'name': 'needinfo',
                'status': '?',
                'requestee': n
            })

    r = requests.post(url + "bug?api_key=" + apikey, json=data)
    _raise_if_gateway_error(r, "fileBug")

    j = _load_json_or_raise(r, "fileBug")

    if 'id' in j:
        return j['id']

    raise Exception(j)


@retry_write
def commentOnBug(url, apikey, bugID, comment, needinfo=None, assignee=None, retry_attempt=1):
    if retry_attempt > 1 and _comment_posted_by_this_task(url, apikey, bugID, comment):
        return

    data = {
        'id': bugID,
        'comment': {'body': comment},
        'comment_tags': [task_id_comment_tag()]
    }

    if assignee:
        data['assigned_to'] = assignee
    if needinfo:
        data['flags'] = [{
            'name': 'needinfo',
            'status': '?',
            'requestee': needinfo
        }]

    r = requests.put(
        url + "bug/" + str(bugID) + "?api_key=" + apikey,
        json=data
    )

    _raise_if_gateway_error(r, "commentOnBug")
    if r.status_code == 406:
        raise CommentRejectedError("Bugzilla rejected the comment on Bug %s (status=406)" % bugID)

    j = _load_json_or_raise(r, "commentOnBug")

    if 'bugs' in j:
        if len(j['bugs']) > 0:
            if j['bugs'][0]['id'] == bugID:
                return

    raise Exception(j)


@retry_write
def closeBug(url, apikey, bugID, resolution, comment, dup_id=None, retry_attempt=1):
    assert dup_id is None or resolution == 'DUPLICATE'
    # Closing the bug and its comment happen together, so finding the comment means it closed
    if retry_attempt > 1 and _comment_posted_by_this_task(url, apikey, bugID, comment):
        return
    data = {
        'id': bugID,
        'status': 'RESOLVED',
        'resolution': resolution,
        'comment': {'body': comment},
        'comment_tags': [task_id_comment_tag()]
    }

    if dup_id:
        data['dup_id'] = dup_id

    r = requests.put(
        url + "bug/" + str(bugID) + "?api_key=" + apikey,
        json=data
    )

    _raise_if_gateway_error(r, "closeBug")
    j = _load_json_or_raise(r, "closeBug")

    if 'bugs' in j:
        if len(j['bugs']) > 0:
            if j['bugs'][0]['id'] == bugID:
                return

    raise Exception(j)


@retry
def getBugComments(url, bugID):
    r = requests.get(url + "bug/" + str(bugID) + "/comment")

    j = _load_json_or_raise(r, "getBugComments")

    try:
        bugs = j['bugs']
        bug_data = bugs.get(str(bugID), bugs.get(bugID, {}))
        comments = bug_data.get('comments', [])
        return [c.get('text', '') for c in comments if isinstance(c, dict)]
    except Exception as e:
        raise Exception(j) from e


@retry
def openBugsMetadata(url, bugIDs):
    r = requests.get(url + "bug?resolution=---&id=%s&include_fields=id,assigned_to" % ",".join([str(b) for b in bugIDs]))

    j = _load_json_or_raise(r, "openBugsMetadata")

    try:
        return {b['id']: b for b in j['bugs']}
    except KeyError as e:
        raise Exception(j) from e


@retry_write
def markFFVersionAffected(url, apikey, bugID, ff_version, affected):
    if not is_prod(url):
        return

    data = {
        'id': bugID,
        'cf_status_firefox' + str(ff_version): 'affected' if affected else 'unaffected'
    }

    r = requests.put(
        url + "bug/" + str(bugID) + "?api_key=" + apikey,
        json=data
    )

    # Setting a field again is harmless, so a retry needs no check
    _raise_if_gateway_error(r, "markFFVersionAffected")
    j = _load_json_or_raise(r, "markFFVersionAffected")

    if 'bugs' in j:
        if len(j['bugs']) > 0:
            if j['bugs'][0]['id'] == bugID:
                return

    raise Exception(j)
