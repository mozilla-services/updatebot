#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from enum import unique, IntEnum
import json
import jsone
import platform
import requests
from collections import defaultdict
from urllib.parse import quote_plus

from components.utilities import retry, Struct, merge_dictionaries, PUSH_HEALTH_IGNORED_DICTS, PUSH_HEALTH_IGNORED_KEYS
from components.logging import logEntryExit, logEntryExitNoArgs, LogLevel
from components.providerbase import BaseProvider, INeedsCommandProvider, INeedsLoggingProvider

# We want to run tests a total of four times
TRIGGER_TOTAL = 4


# These are intentionally ordered so that the ones that override the others have a higher value
@unique
class Classification(IntEnum):
    NotYourFault = 4
    NewFailure = 3
    PossibleIntermittent = 2
    Unassigned = 1

    def mini(self):
        if self.value == Classification.NotYourFault:
            return "NYF"
        elif self.value == Classification.NewFailure:
            return "F"
        elif self.value == Classification.PossibleIntermittent:
            return "I"
        elif self.value == Classification.Unassigned:
            return "U"

    @staticmethod
    def from_string(s, logger):
        if s == "New Failure":  # from Push Health
            return Classification.NewFailure
        elif s == "new failure not classified":  # from TC
            return Classification.NewFailure
        elif s == "fixedByCommit":  # from Push Health
            return Classification.NotYourFault
        elif s in ["autoclassified intermittent", "expected fail", "fixed by commit", "infra"]:  # from TC
            return Classification.NotYourFault
        elif s == "intermittent":  # from Push Health
            return Classification.PossibleIntermittent
        elif s in ["intermittent", "not classified"]:  # from TC
            return Classification.PossibleIntermittent
        logger.log_exception(Exception("Received an unknown suggestedClassification from push health: %s." % s))
        return Classification.Unassigned


class Task:
    def __init__(self, task, classification):
        self.task_id = task.task_id
        self.name = self.job_type_name = task.job_type_name
        self.failed = task.result != "success"
        self.classification = classification
        self.task = task

    def __eq__(self, other):
        if isinstance(other, Task):
            return self.task_id == other.task_id
        return False

    def __repr__(self):
        return self.task_id

    def __hash__(self):
        """
        Hash method based on task_id.
        """
        return hash(self.task_id)


class ResultGroup:
    """
    Result group is a group of tasks that all share a commonality - they either ran the same test, or they ran the same job
    It will contain both the failed and the successful jobs for that group.
    We will upgrade the classification of the entire group after every new task we see.
    """

    def __init__(self, name):
        self.name = name
        self.tasks = {}
        self.classification = Classification.PossibleIntermittent

    def all(self):
        return self.tasks.values()

    def failed(self):
        return [t for t in self.tasks.values() if t.failed]

    def task_ids(self):
        return [t.task_id for t in self.tasks]

    def add_task(self, task, classification):
        t = Task(task, classification)

        self.classification = max(self.classification, classification)
        if t.task_id not in self.tasks:
            self.tasks[t.task_id] = t

    # This gets used from the Push Health results, and Push Health might have
    # its own classification information that would override things
    def add_tasks(self, tasks, classification):
        for t in tasks:
            assert(isinstance(t, Task))
            self.classification = max(self.classification, classification, t.classification)
            self.tasks[t.task_id] = t

    def __repr__(self):
        return "%s:(%s)" % (self.classification.mini(), ", ".join(["%s:%s:%s" % (t.task_id, "F" if t.failed else "P", t.classification.mini()) for t in self.tasks.values()]))


class TaskclusterProvider(BaseProvider, INeedsCommandProvider, INeedsLoggingProvider):
    def __init__(self, config):
        self._vcs_setup_initialized = False
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
    def _vcs_setup(self):
        if platform.system() == 'Windows' and not self._vcs_setup_initialized:
            self.run(["./mach", "vcs-setup", "--update-only"])
        self._vcs_setup_initialized = True

    @logEntryExit
    @retry
    def submit_to_try(self, library, platform_filter, recursed=0):
        self._vcs_setup()
        if not platform_filter:
            platform_filter_args = []
        elif platform_filter[0] == "!":
            platform_filter_args = ["--tasks-regex-exclude", platform_filter[1:]]
        else:
            platform_filter_args = ["--tasks-regex", platform_filter]

        if library.try_preset:
            try_arguments = ["./mach", "try", "--update", "--preset", library.try_preset]
        elif library.fuzzy_query or library.fuzzy_paths:
            try_arguments = ["./mach", "try", "fuzzy", "--update"]
            if library.fuzzy_query:
                try_arguments += ["--query", library.fuzzy_query + " " + (platform_filter or "")]
            else:  # If you don't give a --query it goes into interactive mode
                try_arguments += ["--query", " " + (platform_filter or "")]
            if library.fuzzy_paths:
                try_arguments += library.fuzzy_paths
        else:
            try_arguments = ["./mach", "try", "auto"] + platform_filter_args

        ret = self.run(try_arguments, clean_return=False if recursed < 5 else True)
        output = ret.stdout.decode()

        if "timed out waiting for lock held by" in output:
            return self.submit_to_try(library, platform_filter, recursed + 1)

        isNext = False
        try_link = None
        for line in output.split("\n"):
            if isNext:
                try_link = line.replace("remote:", "").strip()
                break
            if "Follow the progress of your build on Treeherder:" in line:
                isNext = True

        self.logger.log("Submitted try run at {0}".format(try_link), level=LogLevel.Info)
        if not try_link or "jobs?repo=try&revision=" not in try_link:
            raise Exception("Could not find the try link in output:\n" + output)
        try_link = try_link[try_link.index("jobs?repo=try&revision=") + len("jobs?repo=try&revision="):]
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
    def determine_jobs_to_retrigger(self, push_health, all_jobs):
        # The Push Health API is a bit long in the tooth. The difference between needsInvestigation and knownIssues has kind
        # of faded over time.  The failureclassification from Taskcluster is manually set though, so it's fairly useful.
        # What are left with is:
        # High Priority You Should Investigate:
        #   jobs w/ Push Health.suggestedClassification="New Issue" or jobs where failureClassification = "new failure not classified"
        # Jobs that are 'Not Your Fault'
        #   jobs with failureclassification = "fixed by commit", "expected fail", "infra", or "autoclassified intermittent"
        # 'Possibly Intermittent - you should check'
        #   everything else (failureclassification=intermittent, not classified)

        # First ignore all the retry jobs for everything.
        all_jobs = [j for j in all_jobs if j.result != "retry"]

        tasks_by_jobname = {}
        for j in all_jobs:
            if j.job_type_name not in tasks_by_jobname:
                tasks_by_jobname[j.job_type_name] = ResultGroup(j.job_type_name)
            group = tasks_by_jobname[j.job_type_name]

            group.add_task(j, Classification.from_string(self.failure_classifications[j.failure_classification_id], self.logger))

        tasks_by_testname = {}
        for t in push_health['metrics']['tests']['details']['needInvestigation'] + push_health['metrics']['tests']['details']['knownIssues']:
            if t['testName'] not in tasks_by_testname:
                tasks_by_testname[t['testName']] = ResultGroup(t['testName'])
            group = tasks_by_testname[t['testName']]

            group.add_tasks(tasks_by_jobname[t['jobName']].all(), Classification.from_string(t['suggestedClassification'], self.logger))

        # Now, go through and determine what jobs we need to retrigger.
        tasks_to_retrigger = set()
        tasks_not_to_retrigger = set()
        for testname in tasks_by_testname:
            group = tasks_by_testname[testname]

            if group.classification != Classification.NotYourFault and len(group.failed()) > 0 and len(group.all()) <= 2:
                tasks_to_retrigger.update(group.failed())
            else:
                tasks_not_to_retrigger.update(group.failed())

        for jobname in tasks_by_jobname:
            group = tasks_by_jobname[jobname]

            if "build" in jobname:
                continue
            if "lint" in jobname:
                continue
            if group.classification == Classification.NotYourFault:
                continue

            if len(group.failed()) > 0 and len(group.all()) <= 2:
                for t in group.failed():
                    # Do not retrigger jobs unless they were not seen in push health
                    if t not in tasks_not_to_retrigger:
                        tasks_to_retrigger.add(t)

        self.logger.log("tasks_by_jobname: %s" % tasks_by_jobname, level=LogLevel.Debug)
        self.logger.log("tasks_by_testname: %s" % tasks_by_testname, level=LogLevel.Debug)
        self.logger.log("tasks_to_retrigger: %s" % tasks_to_retrigger, level=LogLevel.Debug)

        # Return the list of jobs to retrigger, as well as information about the test failures
        #    and job mappings
        return {
            'to_retrigger': [t.task for t in tasks_to_retrigger],

            'tasks_by_jobname': tasks_by_jobname,
            'tasks_by_testname': tasks_by_testname,
        }

    # =================================================================
    # =================================================================

    def _get_push_list_url(self, revision):
        return self.url_treeherder + "api/%spush/?revision=%s" % (self.url_project_path, revision)

    def _get_job_details_url(self, push_id):
        return self.url_treeherder + "api/jobs/?push_id=%s" % push_id

    @logEntryExit
    def get_job_details(self, revision):
        push_list_url = self._get_push_list_url(revision)
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
        job_details_url = self._get_job_details_url(push_id)
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

    def _get_push_health_url(self, revision):
        return self.url_treeherder + "api/%spush/health/?revision=%s" % (self.url_project_path, revision)

    @logEntryExit
    def get_push_health(self, revision):
        push_health_url = self._get_push_health_url(revision)
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
        decision_task_groups = defaultdict(list)
        for j in retrigger_list:
            assert j.decision_task is not None
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
