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

from components.utilities import Struct, merge_dictionaries, PUSH_HEALTH_IGNORED_DICTS, PUSH_HEALTH_IGNORED_KEYS
from components.logging import logEntryExit, logEntryExitNoArgs, LogLevel
from components.providerbase import BaseProvider, INeedsCommandProvider, INeedsLoggingProvider

# We want to run tests a total of four times
TRIGGER_TOTAL = 4

# These are intentionally ordered so that the ones that override the others have a higher value
@unique
class Classification(IntEnum):
    NewFailure = 3
    NotYourFault = 2
    PossibleIntermittent = 1

    @staticmethod
    def from_string(s):
        if s == "New Failure":
            return Classification.NewFailure
        elif s == "fixedByCommit":
            return Classification.NotYourFault
        elif s == "intermittent":
            return Classification.PossibleIntermittent
        self.logger.log_exception(Exception("Received an unknown suggestedClassification from push health: %s." % s))
        return Classification.PossibleIntermittent


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
        #   jobs with Push Health.suggestedClassification="fixedByCommit" or jobs where failureclassification = "fixed by commit", "expected fail", "infra", or "autoclassified intermittent" 
        # 'Possibly Intermittent - you should check'
        #   everything else (failureclassification=intermittent, not classified)

        # First ignore all the retry jobs for everything.
        all_jobs = [j for j in all_jobs if j.result != "retry"]

        # This function goes through the need_investigation and known_issues results
        #    and produces a mapping of test-failure to jobs that test ran in
        def _correlate_health_data(health_failures_by_testname, detail_obj):
            # You may have multiple entries in detail_obj for one test_name. This indicates the test failed on different platforms/settings
            # Each entry has its own suggestedClassification and its own confidence.
            # The Push Health website collapses all of these differences into one list, we are going to do the same.
            # I'm keeping the confidence score although presently we don't display it.
            for i in detail_obj:
                jobs = [j for j in all_jobs if ("%s" % (j.job_type_name)) == i['jobName']]
                health_failures_by_testname[i['testName']].jobs.extend(jobs)
                health_failures_by_testname[i['testName']].confidence = max(i['confidence'], health_failures_by_testname[i['testName']].confidence)
                health_failures_by_testname[i['testName']].suggestedClassification = max(Classification.from_string(i['suggestedClassification']), health_failures_by_testname[i['testName']].suggestedClassification)

        health_failures_by_testname = defaultdict(lambda:Struct(**{
            'jobs': list(),
            'confidence': 0,
            'suggestedClassification': Classification.PossibleIntermittent
            }))
        not_health_failures_by_jobTypeName_w_passes = defaultdict(lambda:Struct(**{
            'jobs': set(),
            'confidence': 0,
            'suggestedClassification': Classification.PossibleIntermittent
            }))
        not_health_failures_by_jobTypeName_wo_passes = defaultdict(lambda:Struct(**{
            'jobs': set(),
            'confidence': 0,
            'suggestedClassification': Classification.PossibleIntermittent
            }))

        # Ignoring the distinction between these two
        _correlate_health_data(health_failures_by_testname, push_health['metrics']['tests']['details']['needInvestigation'])
        _correlate_health_data(health_failures_by_testname, push_health['metrics']['tests']['details']['knownIssues'])

        # Get all the failed jobs in the push
        all_failed_jobs = [j for j in all_jobs if j.result != "success"]
        all_failed_jobs_task_ids = set([j.task_id for j in all_failed_jobs])
        self.logger.log("all_failed_jobs_task_ids: %s" % all_failed_jobs_task_ids, level=LogLevel.Debug)

        # All the high priority jobs
        high_priority_jobs = [j for j in all_failed_jobs if self.failure_classifications[j.failure_classification_id] in ["new failure not classified"]]
        for obj in health_failures_by_testname.values():
            if obj.suggestedClassification == Classification.NewFailure:
                high_priority_jobs.extend(obj.jobs)
        high_priority_jobs_task_ids = set([j.task_id for j in high_priority_jobs])
        self.logger.log("high_priority_jobs_task_ids: %s" % high_priority_jobs_task_ids, level=LogLevel.Debug)

        # All the jobs that are not your fault
        not_your_fault_jobs = [j for j in all_failed_jobs if self.failure_classifications[j.failure_classification_id] in ["autoclassified intermittent", "expected fail", "fixed by commit", "infra"] and j.task_id not in high_priority_jobs_task_ids]
        for obj in health_failures_by_testname.values():
            if obj.suggestedClassification == Classification.NotYourFault:
                not_your_fault_jobs.extend(obj.jobs)
        not_your_fault_jobs_task_ids = set([j.task_id for j in not_your_fault_jobs])
        self.logger.log("not_your_fault_jobs_task_ids: %s" % not_your_fault_jobs_task_ids, level=LogLevel.Debug)

        """
        # It's possible that Taskcluster has classified some failures, but Push Health didn't know that.
        # So go through the Push Health results and mark them if that is the case.
        # We don't need to do this before the 'not-your-fault' jobs because any jobs TC thought were NewFailure became NewFailure
        #   and any jobs TC thought were NotYourFault became NotYourFault as long as they weren't NewFailure
        # But we need to do this before PossibleIntermittent because 
        for testName in health_failures_by_testname:
            # At the same time, this happening is probably kind of rare, so I'm going to actually throw an exception so I can track (via email)
            # if and how often it occurs at the beginning.
            # These conditionals take the form "Are all the jobs for this test failure in the set of <this type of job>"
            this_tests_task_ids = set([j.task_id for j in health_failures_by_testname[testName].jobs])

            if health_failures_by_testname[testName].suggestedClassification != Classification.NewFailure and \
               len(this_tests_task_ids) == len(this_tests_task_ids.intersection(high_priority_jobs_task_ids)):
                self.logger.log_exception(Exception("Reclassifying a set of %s test failures from %s to High Priority." % (len(health_failures_by_testname[testName].jobs), health_failures_by_testname[testName].suggestedClassification)))
                health_failures_by_testname[testName].suggestedClassification = Classification.NewFailure

            if health_failures_by_testname[testName].suggestedClassification != Classification.NotYourFault and \
               len(this_tests_task_ids) == len(this_tests_task_ids.intersection(not_your_fault_jobs_task_ids)):
                self.logger.log_exception(Exception("Reclassifying a set of %s test failures from %s to Not Your Fault." % (len(health_failures_by_testname[testName].jobs), health_failures_by_testname[testName].suggestedClassification)))
                health_failures_by_testname[testName].suggestedClassification = Classification.NotYourFault
        """

        # And finally find all the intermittent jobs
        intermittent_jobs = [j for j in all_failed_jobs if self.failure_classifications[j.failure_classification_id] in ["intermittent", "not classified"] and j.task_id not in high_priority_jobs_task_ids and j.task_id not in not_your_fault_jobs_task_ids]
        for obj in health_failures_by_testname.values():
            if obj.suggestedClassification == Classification.PossibleIntermittent:
                intermittent_jobs.extend(obj.jobs)
        intermittent_jobs_task_ids = set([j.task_id for j in intermittent_jobs])
        self.logger.log("intermittent_jobs_task_ids: %s" % intermittent_jobs_task_ids, level=LogLevel.Debug)

        # Then, to make sure we got everything, confirm we've classified all the failures
        leftover_check_task_ids = all_failed_jobs_task_ids - intermittent_jobs_task_ids - not_your_fault_jobs_task_ids - high_priority_jobs_task_ids
        if len(leftover_check_task_ids) > 0:
            self.logger.log_exception(Exception("We had %s jobs leftover after trying to classify everything: %s" % (len(leftover_check_task_ids), ", ".join(leftover_check_task_ids))))

        #####################################################################
        # Now, go through and determine what jobs we need to retrigger.
        jobs_to_retrigger = set()

        # We retrigger 'New Failures' if we've seen 1 or even 2 of those failures. We retrigger
        # other jobs if they're possibly our fault and there's only one failure.
        # This loop only looks at jobs classified by push health.
        for t in health_failures_by_testname:
            jobs = health_failures_by_testname[t].jobs
            # Retrigger if we have 2 or fewer failures
            if health_failures_by_testname[t].suggestedClassification != Classification.NotYourFault:
                if len(jobs) <= 2:
                    jobs_to_retrigger.update(jobs)

        # We also need to retrigger jobs that failed that weren't classified by Push Health though. 
        # Specifically, if a job is in leftover_failures AND not classified by push_health,
        # we probably want to retrigger it.
        push_health_failed_jobs_task_ids = set()
        for obj in health_failures_by_testname.values():
            push_health_failed_jobs_task_ids.update([j.task_id for j in obj.jobs])
        self.logger.log("push_health_failed_jobs_task_ids: %s" % push_health_failed_jobs_task_ids, level=LogLevel.Debug)

        not_push_health_failed_jobs_task_ids = all_failed_jobs_task_ids - push_health_failed_jobs_task_ids
        not_push_health_failed_jobs = [j for j in all_failed_jobs if j.task_id in not_push_health_failed_jobs_task_ids]
        self.logger.log("not_push_health_failed_jobs_task_ids: %s" % not_push_health_failed_jobs_task_ids, level=LogLevel.Debug)
        
        remaining_failures_jobs_task_ids = not_push_health_failed_jobs_task_ids.intersection(high_priority_jobs.union(intermittent_jobs))
        remaining_failures_jobs = [j for j in all_failed_jobs if j.task_id in remaining_failures_jobs_task_ids]
        self.logger.log("remaining_failures_jobs_task_ids: %s" % remaining_failures_jobs_task_ids, level=LogLevel.Debug)

        # remaining_failures_jobs is the failed jobs not classified by Push Health. We're going to group them by job name
        # (similar to how Push Health groups by test name)
        for failed_job in not_push_health_failed_jobs:
            for j in all_jobs:
                if j.job_type_name == failed_job.job_type_name:
                    not_health_failures_by_jobTypeName[j.job_type_name].jobs.add(j)

        # So finally, we can retrigger jobs that failed, weren't classified by Push Health weren't in high_priority,
        # weren't in not_you_fault, and aren't build or lint jobs.
        for j in remaining_failures_jobs:
            if "build" in j.job_type_name:
                pass
            elif "lint" in j.job_type_name:
                pass
            else:
                jobs_to_retrigger.add(j)

        # And for commenting purposes, we group any failed not-push-health jobs by job type name (including the passing jobs)
        for failed_job in not_push_health_failed_jobs:
            for j in all_jobs:
                if j.job_type_name == failed_job.job_type_name:
                    not_health_failures_by_jobTypeName[j.job_type_name].jobs.add(j)

        # Then go through each grouping, and decide if its High Priority, Not Your Fault, or Intermittent
        for name in not_health_failures_by_jobTypeName:
            sc = Classification.PossibleIntermittent
            for j in not_health_failures_by_jobTypeName[name].jobs:
                if j.task_id in high_priority_jobs_task_ids:
                    sc = max(sc, Classification.NewFailure)
                elif j.task_id in not_your_fault_jobs_task_ids:
                    sc = max(sc, Classification.NotYourFault)
            not_health_failures_by_jobTypeName[name].suggestedClassification = sc

                
        # Return the list of jobs to retrigger, as well as information about the test failures and job mappings
        return {
            'to_retrigger': jobs_to_retrigger,

            'health_failures_by_testname': health_failures_by_testname,
            'not_health_failures_by_jobTypeName': not_health_failures_by_jobTypeName,

            'not_your_fault_jobs': not_your_fault_jobs,
            'high_priority_jobs': high_priority_jobs,
            'intermittent_jobs': intermittent_jobs
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
