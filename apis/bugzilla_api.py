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


def fileBug(url, apikey, ff_version, product, component, summary, description, cc_list, needinfo, see_also, depends_on, blocks, moco_confidential):
    assert isinstance(cc_list, list)

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

    if is_prod(url):
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

    j = _load_json_or_raise(r, "fileBug")

    if 'id' in j:
        return j['id']

    raise Exception(j)


def commentOnBug(url, apikey, bugID, comment, needinfo=None, assignee=None):
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

    j = _load_json_or_raise(r, "commentOnBug")

    if 'bugs' in j:
        if len(j['bugs']) > 0:
            if j['bugs'][0]['id'] == bugID:
                return

    raise Exception(j)


def closeBug(url, apikey, bugID, resolution, comment, dup_id=None):
    assert dup_id is None or resolution == 'DUPLICATE'
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

    j = _load_json_or_raise(r, "closeBug")

    if 'bugs' in j:
        if len(j['bugs']) > 0:
            if j['bugs'][0]['id'] == bugID:
                return

    raise Exception(j)


@retry
def openBugsMetadata(url, bugIDs):
    r = requests.get(url + "bug?resolution=---&id=%s&include_fields=id,assigned_to" % ",".join([str(b) for b in bugIDs]))

    j = _load_json_or_raise(r, "openBugsMetadata")

    try:
        return {b['id']: b for b in j['bugs']}
    except KeyError as e:
        raise Exception(j) from e


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

    j = _load_json_or_raise(r, "markFFVersionAffected")

    if 'bugs' in j:
        if len(j['bugs']) > 0:
            if j['bugs'][0]['id'] == bugID:
                return

    raise Exception(j)
