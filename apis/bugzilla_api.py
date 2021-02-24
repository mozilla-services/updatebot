#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import json
import requests


def sq(s):
    return '[' + s + ']'


def kw(s):
    return sq('3pl-' + s)


def fileBug(url, apikey, product, component, summary, description, severity, cc_list, see_also, depends_on):
    data = {
        'version': "unspecified",
        'op_sys': "unspecified",

        'product': product,
        'component': component,
        'type': "enhancement",
        'severity': severity,
        'summary': summary,
        'description': description,
        'whiteboard': kw('filed'),
        'cc': ['tom@mozilla.com'] + cc_list
    }
    if see_also:
        data['see_also'] = see_also
    if depends_on:
        data['depends_on'] = depends_on

    r = requests.post(url + "bug?api_key=" + apikey, json=data)

    try:
        j = json.loads(r.text)
    except Exception as e:
        raise Exception("Could not decode a bugzilla response as JSON: " + r.text) from e

    if 'id' in j:
        return j['id']

    raise Exception(j)


def commentOnBug(url, apikey, bugID, comment, needinfo=None, assignee=None):
    data = {
        'id': bugID,
        'comment': {'body': comment}
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

    try:
        j = json.loads(r.text)
    except Exception as e:
        raise Exception("Could not decode a bugzilla response as JSON: " + r.text) from e

    if 'bugs' in j:
        if len(j['bugs']) > 0:
            if j['bugs'][0]['id'] == bugID:
                return

    raise Exception(j)


def closeBug(url, apikey, bugID, comment):
    data = {
        'id': bugID,
        'status': 'RESOLVED',
        'resolution': 'WONTFIX',
        'comment': {'body': comment}
    }

    r = requests.put(
        url + "bug/" + str(bugID) + "?api_key=" + apikey,
        json=data
    )

    try:
        j = json.loads(r.text)
    except Exception as e:
        raise Exception("Could not decode a bugzilla response as JSON: " + r.text) from e

    if 'bugs' in j:
        if len(j['bugs']) > 0:
            if j['bugs'][0]['id'] == bugID:
                return

    raise Exception(j)
