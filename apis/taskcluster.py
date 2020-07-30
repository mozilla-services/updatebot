#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import json
import jsone
import requests

from components.utilities import Struct
from components.logging import logEntryExit, logEntryExitNoArgs, LogLevel
from components.providerbase import BaseProvider, INeedsCommandProvider, INeedsLoggingProvider

RETRIGGER_NUMBER = 3


class TaskclusterProvider(BaseProvider, INeedsCommandProvider, INeedsLoggingProvider):
    def __init__(self, config):
        self._vcs_setup_initialized = False
        self._failure_classifications = None

        self.url = "https://treeherder.mozilla.org/"
        if 'url' in config:
            self.url = config['url']

        self.project = ""
        if 'project' in config:
            self.project = "project/" + config['project'] + "/"

        self.HEADERS = {
            'User-Agent': 'Updatebot'
        }

    # =================================================================
    # =================================================================
    @logEntryExit
    def _vcs_setup(self):
        if not self._vcs_setup_initialized:
            self.run(["./mach", "vcs-setup", "--update"])
            self._vcs_setup_initialized = True
        self._vcs_setup_initialized = False

    @logEntryExit
    def submit_to_try(self, library):
        self._vcs_setup()
        ret = self.run(
            ["./mach", "try", "auto"])
        output = ret.stdout.decode()

        isNext = False
        try_link = None
        for l in output.split("\n"):
            if isNext:
                try_link = l.replace("remote:", "").strip()
                break
            if "Follow the progress of your build on Treeherder:" in l:
                isNext = True

        if not try_link or "#/jobs?repo=try&revision=" not in try_link:
            raise Exception("Could not find the try link in output:\n" + output)
        try_link = try_link[try_link.index("#/jobs?repo=try&revision=") + len("#/jobs?repo=try&revision="):]
        return try_link

    # =================================================================
    # =================================================================

    @staticmethod
    def _transform_job_list(property_names, job_list):
        new_job_list = []
        for j in job_list:
            d = {}
            for i in range(len(property_names)):
                d[property_names[i]] = j[i]
            new_job_list.append(Struct(**d))
        return new_job_list

    # =================================================================

    def _get_failure_classifications(self):
        if not self._failure_classifications:
            self.logger.log("Requesting failure classifications", level=LogLevel.Info)
            r = requests.get(self.url + "api/failureclassification/", headers=self.HEADERS)
            j = r.json()

            failureclassifications = {}
            for f in j:
                failureclassifications[f['id']] = f['name']
            self._failure_classifications = failureclassifications
        return self._failure_classifications

    def _set_failure_classifications(self, v):
        self._failure_classifications = v

    def _del_failure_classifications(self):
        del self._failure_classifications

    failure_classifications = property(_get_failure_classifications, _set_failure_classifications, _del_failure_classifications)

    # =================================================================
    # =================================================================

    @logEntryExit
    def get_job_details(self, revision):
        push_list_url = self.url + "api/" + self.project + "push/?revision=%s" % revision
        self.logger.log("Requesting revision %s from %s" % (revision, push_list_url), level=LogLevel.Info)

        r = requests.get(push_list_url, headers=self.HEADERS)
        try:
            push_list = r.json()
        except Exception:
            raise Exception("Could not parse the result of the push_list as json. Url: %s Response:\n%s" % (push_list_url, r.text))

        try:
            push_id = push_list['results'][0]['id']
        except Exception as e:
            raise Exception("Could not find the expected ['results'][0]['id'] from %s" % r.text) from e

        job_list = []
        property_names = []
        job_details_url = self.url + "api/jobs/?push_id=%s" % push_id
        try:
            while job_details_url:
                self.logger.log("Requesting push id %s from %s" % (push_id, job_details_url), level=LogLevel.Info)
                r = requests.get(job_details_url, headers=self.HEADERS)
                try:
                    j = r.json()
                except Exception:
                    raise Exception("Could not parse the result of the jobs list as json. Url: %s Response:\n%s" % (job_details_url, r.text))

                job_list.extend(j['results'])
                if not property_names:
                    property_names = j['job_property_names']
                else:
                    for i in range(len(property_names)):
                        if len(property_names) != len(j['job_property_names']):
                            raise Exception("The first j['job_property_names'] was %i elements long, but a subsequant one was %i for url %s" % (len(property_names), len(j['job_property_names']), job_details_url))
                        elif property_names[i] != j['job_property_names'][i]:
                            raise Exception("Property name %s (index %i) doesn't match %s" % (property_names[i], i, j['job_property_names'][i]))

                job_details_url = j['next'] if 'next' in j else None
        except Exception as e:
            raise Exception("Could not obtain all the job results for push id %s" % push_id) from e

        new_job_list = TaskclusterProvider._transform_job_list(property_names, job_list)

        return new_job_list

    # =================================================================
    # =================================================================

    @logEntryExitNoArgs
    def retrigger_jobs(self, job_list, retrigger_list):
        # Go through the jobs and find the decision task
        decision_task = None
        for j in job_list:
            if "Gecko Decision Task" == j.job_type_name:
                decision_task = j
                break
        assert decision_task is not None

        # Download its actions.json
        artifact_url = self.url_taskcluster + "api/queue/v1/task/%s/runs/0/artifacts/public/actions.json" % (decision_task.task_id)
        r = requests.get(artifact_url, headers=self.HEADERS)
        try:
            actions = r.json()
        except Exception:
            raise Exception("Could not parse the result of the actions.json artifact as json. Url: %s Response:\n%s" % (artifact_url, r.text))

        # Find the retrigger action
        retrigger_action = None
        for a in actions['actions']:
            if "retrigger-multiple" == a['name']:
                retrigger_action = a
                break
        assert retrigger_action is not None

        # Fill in the taskId of the job I want to retrigger using JSON-E
        retrigger_tasks = [i.job_type_name for i in retrigger_list]
        context = {
            'taskGroupId': retrigger_action['hookPayload']['decision']['action']['taskGroupId'],
            'taskId': None,
            'input': {'requests': [{'tasks': retrigger_tasks, 'times': RETRIGGER_NUMBER}]}
        }
        template = retrigger_action['hookPayload']

        payload = jsone.render(template, context)
        payload = json.dumps(payload).replace("\\n", " ")

        # Shell out to the taskcluster binary
        cmd = "echo -n '" + payload + "' | ./taskcluster-darwin-amd64 api hooks triggerHook " + \
            retrigger_action['hookGroupId'] + " " + retrigger_action['hookId']
        ret = self.run([cmd], shell=True)

        # Check if it worked
        output = ret.stdout.decode()
        try:
            output = json.loads(output)
            self.logger.log("Issued a retrigger, and the decision taskid is %s" % output['status']['taskId'], level=LogLevel.Info)
            return output['status']['taskId']
        except Exception as e:
            raise Exception("Task retrigger did not complete successfully, job output is\n" + output) from e
