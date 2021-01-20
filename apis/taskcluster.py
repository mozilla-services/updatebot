#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import json
import jsone
import requests
from urllib.parse import quote_plus

from components.utilities import Struct, merge_dictionaries, PUSH_HEALTH_IGNORED_DICTS, PUSH_HEALTH_IGNORED_KEYS
from components.logging import logEntryExit, logEntryExitNoArgs, LogLevel
from components.providerbase import BaseProvider, INeedsCommandProvider, INeedsLoggingProvider

# We want to run tests a total of four times
TRIGGER_TOTAL = 4


class TaskclusterProvider(BaseProvider, INeedsCommandProvider, INeedsLoggingProvider):
    def __init__(self, config):
        self._failure_classifications = None

        self.url_treeherder = "https://treeherder.mozilla.org/"
        self.url_taskcluster = "https://firefox-ci-tc.services.mozilla.com/"
        if 'url_treeherder' in config:
            self.url_treeherder = config['url_treeherder']
        if 'url_taskcluster' in config:
            self.url_taskcluster = config['url_taskcluster']

        # The project path is always try. Updatebot runs in mozilla-central (where there
        #   would be no project path), but it submits try runs to try; and this API is
        #   only about reading from try.
        self.url_project_path = "project/try/"

        self.HEADERS = {
            'User-Agent': 'Updatebot'
        }

    # =================================================================
    # =================================================================
    @logEntryExit
    def submit_to_try(self, library, platform_filter):
        if platform_filter[0] == "!":
            platform_filter = ["--tasks-regex-exclude", platform_filter[1:]]
        else:
            platform_filter = ["--tasks-regex", platform_filter]

        ret = self.run(
            ["./mach", "try", "auto"] + platform_filter)
        output = ret.stdout.decode()

        isNext = False
        try_link = None
        for line in output.split("\n"):
            if isNext:
                try_link = line.replace("remote:", "").strip()
                break
            if "Follow the progress of your build on Treeherder:" in line:
                isNext = True

        self.logger.log("Submitted try run at {0}".format(try_link), level=LogLevel.Info)
        if not try_link or "#/jobs?repo=try&revision=" not in try_link:
            raise Exception("Could not find the try link in output:\n" + output)
        try_link = try_link[try_link.index("#/jobs?repo=try&revision=") + len("#/jobs?repo=try&revision="):]
        return try_link

    # =================================================================
    # =================================================================

    @staticmethod
    def _transform_job_list(property_names, job_list):
        decision_task = None
        new_job_list = []
        # We will need to reference the decision task, so we find populate that here also.
        for j in job_list:
            d = {}
            for i in range(len(property_names)):
                d[property_names[i]] = j[i]

            job_obj = Struct(**d, decision_task=None)
            new_job_list.append(job_obj)

            if "Gecko Decision Task" == job_obj.job_type_name:
                decision_task = job_obj

        for j in new_job_list:
            j.decision_task = decision_task

        return new_job_list

    # =================================================================

    def _get_failure_classifications(self):
        if not self._failure_classifications:
            self.logger.log("Requesting failure classifications", level=LogLevel.Info)
            r = requests.get(self.url_treeherder + "api/failureclassification/", headers=self.HEADERS)
            try:
                j = r.json()
            except Exception:
                raise Exception("Could not parse the result of the failureclassification request as json. Response:\n%s" % (r.text))

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

    @logEntryExitNoArgs
    def determine_jobs_to_retrigger(self, push_health, job_details):
        need_investigation = push_health['metrics']['tests']['details']['needInvestigation']
        known_issues = push_health['metrics']['tests']['details']['knownIssues']

        # This function goes through the need_investigation and known_issues results
        #    and produces a mapping of test-failure to jobs that test failed in
        def _correlate(detail_obj):
            detail_by_testname = {}

            for i in detail_obj:
                jobs = [j for j in job_details if ("%s" % (j.job_type_name)) == i['jobName'] and j.result not in ["retry"]]

                if i['testName'] not in detail_by_testname:
                    detail_by_testname[i['testName']] = jobs
                else:
                    detail_by_testname[i['testName']].extend(jobs)

            return detail_by_testname

        need_investigation_by_test = _correlate(need_investigation)
        known_issues_by_test = _correlate(known_issues)

        # Now get all the failed jobs in the push - not just those indicated in the ni/ki push health data
        failed_jobs = set().union([j for j in job_details if j.result not in ["retry", "success"]])

        # We need a unique key for each job
        failed_jobs_task_ids = set().union([j.task_id for j in failed_jobs])
        self.logger.log("failed_jobs_task_ids: %s" % failed_jobs_task_ids, level=LogLevel.Debug)

        # Now get all the unique keys for the jobs that failed due to something classified by push health
        failed_jobs_with_health_classifications_task_ids = set()
        failed_jobs_with_health_classifications_task_ids = failed_jobs_with_health_classifications_task_ids.union([j.task_id for job_list in need_investigation_by_test.values() for j in job_list])
        failed_jobs_with_health_classifications_task_ids = failed_jobs_with_health_classifications_task_ids.union([j.task_id for job_list in known_issues_by_test.values() for j in job_list])
        self.logger.log("failed_jobs_with_health_classifications_task_ids: %s" % failed_jobs_with_health_classifications_task_ids, level=LogLevel.Debug)

        # Now get all the jobs that failed that were classified by Taskcluster as a known intermittent or issue
        failed_jobs_with_taskcluster_classification = [j for j in failed_jobs if self.failure_classifications[j.failure_classification_id] != "not classified"]
        failed_jobs_with_taskcluster_classification_task_ids = set([j.task_id for j in failed_jobs_with_taskcluster_classification])
        self.logger.log("failed_jobs_with_taskcluster_classification_task_ids: %s" % failed_jobs_with_taskcluster_classification_task_ids, level=LogLevel.Debug)

        # Now get all the unique keys for failed jobs that *weren't* classified by push health or Taskcluster
        jobs_failed_with_no_health_classification_task_ids = failed_jobs_task_ids - failed_jobs_with_health_classifications_task_ids - failed_jobs_with_taskcluster_classification_task_ids
        self.logger.log("jobs_failed_with_no_health_classification_task_ids: %s" % jobs_failed_with_no_health_classification_task_ids, level=LogLevel.Debug)

        # And go back from unique key to the full job object
        jobs_failed_with_no_health_classification = [j for j in failed_jobs if j.task_id in jobs_failed_with_no_health_classification_task_ids]

        # Now, go through and determine what jobs we need to retrigger.
        jobs_to_retrigger = set()

        # We retrigger jobs where it contained a test that failed on only a single job
        #    We omit jobs where a test failed more than one time. BUT that same job might
        #    still be retriggered if it contained a test that did only fail one time.
        for t in need_investigation_by_test:
            jobs = need_investigation_by_test[t]
            if len(jobs) == 1:
                jobs_to_retrigger.add(jobs[0])

        # And we retrigger non-build, non-lint jobs that weren't classified by push health
        #    We don't retrigger jobs that failed because of a known issue.
        for j in jobs_failed_with_no_health_classification:
            if "build" in j.job_type_name:
                pass
            elif "lint" in j.job_type_name:
                pass
            else:
                jobs_to_retrigger.add(j)

        # Return the list of jobs to retrigger, as well as information about the test failures
        #    and job mappings
        return {
            'to_retrigger': jobs_to_retrigger,
            'to_investigate': need_investigation_by_test,
            'known_issues': known_issues_by_test,
            'taskcluster_classified': failed_jobs_with_taskcluster_classification
        }

    # =================================================================
    # =================================================================

    @logEntryExit
    def get_job_details(self, revision):
        push_list_url = self.url_treeherder + "api/%spush/?revision=%s" % (self.url_project_path, revision)
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
        job_details_url = self.url_treeherder + "api/jobs/?push_id=%s" % push_id
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

    @logEntryExitNoArgs
    def combine_job_lists(self, job_list_1, job_list_2):
        return job_list_1 + job_list_2

    # =================================================================
    # =================================================================

    @logEntryExit
    def get_push_health(self, revision):
        push_health_url = self.url_treeherder + "api/%spush/health/?revision=%s" % (self.url_project_path, revision)
        self.logger.log("Requesting push health for revision %s from %s" % (revision, push_health_url), level=LogLevel.Info)

        r = requests.get(push_health_url, headers=self.HEADERS)
        try:
            push_health = r.json()
        except Exception:
            raise Exception("Could not parse the result of the push health as json. Url: %s Response:\n%s" % (push_health_url, r.text))

        return push_health

    @logEntryExitNoArgs
    def combine_push_healths(self, push_health_1, push_health_2):
        combined = merge_dictionaries(push_health_1, push_health_2,
                                      ignored_dicts=PUSH_HEALTH_IGNORED_DICTS,
                                      ignored_keys=PUSH_HEALTH_IGNORED_KEYS)
        return combined

    # =================================================================
    # =================================================================
    @logEntryExitNoArgs
    def retrigger_jobs(self, retrigger_list):
        # Group the jobs to retrigger by decision task
        decision_task_groups = {}
        for j in retrigger_list:
            assert j.decision_task is not None
            if j.decision_task not in decision_task_groups:
                decision_task_groups[j.decision_task] = []
            decision_task_groups[j.decision_task].append(j)

        retrigger_decision_task_ids = []
        # Go through each group:
        for decision_task in decision_task_groups:
            self.logger.log("Processing decision task %s" % decision_task.task_id, level=LogLevel.Info)
            to_retrigger = decision_task_groups[decision_task]

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

            # Fill in the taskId of the jobs I want to retrigger using JSON-E
            retrigger_tasks = [i.job_type_name for i in to_retrigger]
            context = {
                'taskGroupId': retrigger_action['hookPayload']['decision']['action']['taskGroupId'],
                'taskId': None,
                'input': {'requests': [{'tasks': retrigger_tasks, 'times': TRIGGER_TOTAL - 1}]}
            }
            template = retrigger_action['hookPayload']

            payload = jsone.render(template, context)
            payload = json.dumps(payload).replace("\\n", " ")

            trigger_url = self.url_taskcluster + "api/hooks/v1/hooks/%s/%s/trigger" % \
                (quote_plus(retrigger_action["hookGroupId"]), quote_plus(retrigger_action["hookId"]))

            self.logger.log("Issuing a retrigger to %s" % (trigger_url), level=LogLevel.Info)
            r = requests.post(trigger_url, data=payload)
            try:
                if r.status_code == 200:
                    output = r.json()
                    retrigger_decision_task_ids.append(output["status"]["taskId"])
                    self.logger.log("Succeeded, the response taskid is %s" % output["status"]["taskId"], level=LogLevel.Info)
                else:
                    raise Exception("Task retrigger did not complete successfully, status code is " + str(r.status_code) + "\n\n" + r.text)
            except Exception as e:
                raise Exception("Task retrigger did not complete successfully (exception raised during json parsing), response is\n" + r.text) from e

        return retrigger_decision_task_ids
