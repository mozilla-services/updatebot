#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import copy
import functools
import subprocess

from tasktypes.base import BaseTaskRunner
from apis.taskcluster import Classification
from components.bugzilla import CommentTemplates
from components.mach_vendor import VendorResult
from components.dbmodels import JOBSTATUS, JOBOUTCOME, JOBTYPE
from components.logging import LogLevel, logEntryExit, logEntryExitNoArgs
from components.hg import reset_repository


class VendorTaskRunner(BaseTaskRunner):
    def __init__(self, provider_dictionary, config_dictionary):
        self.jobType = JOBTYPE.VENDORING
        self.__dict__.update(provider_dictionary)
        self.logger = copy.deepcopy(self.loggingProvider)
        self.logger.log = functools.partial(self.logger.log, category=self.__class__.mro()[0].__name__)
        self.config = config_dictionary

    # ====================================================================

    def process_task(self, library, task):
        assert task.type == 'vendoring'

        # Collect all the existing jobs, and figure out which have open bugs
        all_jobs = self.dbProvider.get_all_jobs_for_library(library, JOBTYPE.VENDORING)
        open_bugs = self.bugzillaProvider.find_open_bugs_info([j.bugzilla_id for j in all_jobs])
        for j in all_jobs:
            j.bugzilla_is_open = j.bugzilla_id in open_bugs
            j.bugzilla_assignee = open_bugs[j.bugzilla_id]['assigned_to_detail']['email'] if j.bugzilla_id in open_bugs else None
            j.bugzilla_assignee = None if j.bugzilla_assignee in ["nobody@mozilla.org", "update-bot@bmo.tld"] else j.bugzilla_assignee

        # Get the list of all jobs we want to do something about
        all_jobs_not_done = [j for j in all_jobs if j.status != JOBSTATUS.DONE or j.bugzilla_is_open]

        # Then process all of them
        for j in all_jobs_not_done:
            self.logger.set_context(library.name, j.id)
            self.logger.log("Processing job id %s for %s which is currently %s and has a %s bug" % (j.id, library.name, j.status, "open" if j.bugzilla_is_open else "closed"))
            self._process_existing_job(library, task, j)
            self._reset_for_new_job()
        self.logger.set_context(library.name)

        # See if we have a new upstream commit to process
        new_version, timestamp = self.vendorProvider.check_for_update(library)
        if not new_version:
            self.logger.log("No new version for %s was found." % library.name, level=LogLevel.Info)
            return

        # Then see if we already made a job for it.
        existing_job = [j for j in all_jobs if j.version == new_version]
        assert len(existing_job) < 2, "We found more than two jobs for version %s" % new_version
        if any(existing_job):
            existing_job = existing_job[0]
            self.logger.log("Job id %s was already created for the latest upstream revision %s" % (existing_job.id, new_version), level=LogLevel.Info)
            return

        # We didn't, so we'll process it, but first:
        # sanity-check - there should be at most one non-relinquished job, and if it is present, it should be the most recent.
        non_relinquished_jobs = [j for j in all_jobs if not j.relinquished]
        assert len(non_relinquished_jobs) <= 1, "We got more than one non-relinquished job: %s" % non_relinquished_jobs

        most_recent_job = all_jobs[0] if all_jobs else None
        assert most_recent_job is None or 0 == len(non_relinquished_jobs) or (len(non_relinquished_jobs) == 1 and most_recent_job == non_relinquished_jobs[0]), \
            "Most Recent Job is %s, we have %s non-relinquished jobs (%s), and they don't match." % (
            most_recent_job.id if most_recent_job else "nothing",
            len(non_relinquished_jobs), non_relinquished_jobs)

        # Now process it.
        self.logger.log("Processing %s for a new upstream revision %s, the most recent job is %s." % (library.name, new_version, most_recent_job.id if most_recent_job else "(none)"), level=LogLevel.Info)
        self._process_new_job(library, task, new_version, timestamp, most_recent_job)
        self._reset_for_new_job()

    # ====================================================================
    @logEntryExit
    def _reset_for_new_job(self):
        # remove commits generated from processing this library, will return success
        # regardless of if outgoing commits exist or not.
        self.logger.log("Removing any outgoing commits before moving on.", level=LogLevel.Info)

        # If we are on TC, update to the HEAD commit to avoid stripping WIP commits on holly
        self.cmdProvider.run(["hg", "status"])
        reset_repository(self.cmdProvider)

    # ====================================================================
    @logEntryExit
    def _process_prior_job(self, prior_job, superseceding_bugzilla_id):
        self.logger.log("The prior job id %s is not relinquished, so processing it." % prior_job.id, level=LogLevel.Info)

        if not prior_job.bugzilla_is_open:
            self.logger.log("The prior job's bugzilla bug is closed, so we only need to relinquish it.", level=LogLevel.Info)
        elif superseceding_bugzilla_id:
            self.logger.log("The prior job's bugzilla bug is open, marking it as superseded by Bug ID %s ." % superseceding_bugzilla_id, level=LogLevel.Info)

            self.bugzillaProvider.dupe_bug(prior_job.bugzilla_id, CommentTemplates.BUG_SUPERSEDED(), superseceding_bugzilla_id)
            if prior_job.phab_revisions:
                for p in prior_job.phab_revisions:
                    try:
                        self.phabricatorProvider.abandon(p.revision)
                    except Exception as e:
                        self.bugzillaProvider.comment_on_bug(prior_job.bugzilla_id, CommentTemplates.COULD_NOT_GENERAL_ERROR("abandon the phabricator patch %s." % p.revision))
                        self.logger.log_exception(e)  # We're going to log this exception, but not stop processing the new job

        self.dbProvider.update_job_relinquish(prior_job)

    @logEntryExit
    def _process_new_job(self, library, task, new_version, timestamp, most_recent_job):
        if not self._should_process_new_job(library, task, new_version):
            self.logger.log("Because of the task's frequency restrictions (%s) we are not processing this new revision now." % task.frequency, level=LogLevel.Info)
            return

        # Vendor ------------------------------
        (result, msg) = self.vendorProvider.vendor(library, new_version)

        # Check for spurious update -----------
        if result == VendorResult.SPURIOUS_UPDATE:
            self.logger.log("Version %s was a spruious update." % new_version)
            return

        # Create the job ----------------------
        created_job = self.dbProvider.create_job(JOBTYPE.VENDORING, library, new_version, JOBSTATUS.CREATED, JOBOUTCOME.PENDING)
        self.logger.set_context(library.name, created_job.id)

        # File the bug ------------------------
        all_upstream_commits, unseen_upstream_commits = self.scmProvider.check_for_update(library, task, new_version, most_recent_job)
        commit_stats = self.mercurialProvider.diff_stats()
        commit_details = self.scmProvider.build_bug_description(all_upstream_commits, 65534 - len(commit_stats) - 220) if library.should_show_commit_details else ""

        created_job.bugzilla_id = self.bugzillaProvider.file_bug(library, CommentTemplates.UPDATE_SUMMARY(library, new_version, timestamp), CommentTemplates.UPDATE_DETAILS(len(all_upstream_commits), len(unseen_upstream_commits), commit_stats, commit_details), task.cc, blocks=task.blocking)
        self.dbProvider.update_job_add_bug_id(created_job, created_job.bugzilla_id)

        # Address any prior bug ---------------
        if most_recent_job and not most_recent_job.relinquished:
            self._process_prior_job(most_recent_job, created_job.bugzilla_id)

        # Handle other vendoring outcomes -----
        if result == VendorResult.GENERAL_ERROR:
            # We're not going to commit these changes; so clean them out.
            reset_repository(self.cmdProvider)

            # Handle `./mach vendor` failing
            self.dbProvider.update_job_status(created_job, JOBSTATUS.DONE, JOBOUTCOME.COULD_NOT_VENDOR)
            self.bugzillaProvider.comment_on_bug(created_job.bugzilla_id, CommentTemplates.COULD_NOT_VENDOR(library, msg), needinfo=library.maintainer_bz)
            return
        elif result == VendorResult.MOZBUILD_ERROR:
            # Add a comment but do not abort
            self.bugzillaProvider.comment_on_bug(created_job.bugzilla_id, CommentTemplates.COULD_NOT_VENDOR_ALL_FILES(library, msg))
        elif result == VendorResult.SUCCESS:
            pass
        else:
            raise Exception("Unexpected VendorResult: %s " % result)

        # Commit ------------------------------
        try:
            self.mercurialProvider.commit(library, created_job.bugzilla_id, new_version)
        except Exception as e:
            self.dbProvider.update_job_status(created_job, JOBSTATUS.DONE, JOBOUTCOME.COULD_NOT_COMMIT)
            self.bugzillaProvider.comment_on_bug(created_job.bugzilla_id, CommentTemplates.COULD_NOT_GENERAL_ERROR("commit the updated library."), needinfo=library.maintainer_bz)
            raise e

        if library.has_patches:
            # Apply Patches -------------------
            try:
                self.vendorProvider.patch(library, new_version)
            except Exception as e:
                if isinstance(e, subprocess.CalledProcessError):
                    msg = ("stderr:\n" + e.stderr.decode().rstrip() + "\n\n") if e.stderr else ""
                    msg += ("stdout:\n" + e.stdout.decode().rstrip()) if e.stdout else ""
                else:
                    msg = str(e)
                self.dbProvider.update_job_status(created_job, JOBSTATUS.DONE, JOBOUTCOME.COULD_NOT_PATCH)
                self.bugzillaProvider.comment_on_bug(created_job.bugzilla_id, CommentTemplates.COULD_NOT_GENERAL_ERROR("apply the mozilla patches.", errormessage=msg), needinfo=library.maintainer_bz)
                return
            # Commit Patches ------------------
            try:
                self.mercurialProvider.commit_patches(library, created_job.bugzilla_id, new_version)
            except Exception as e:
                self.dbProvider.update_job_status(created_job, JOBSTATUS.DONE, JOBOUTCOME.COULD_NOT_COMMIT_PATCHES)
                self.bugzillaProvider.comment_on_bug(created_job.bugzilla_id, CommentTemplates.COULD_NOT_GENERAL_ERROR("commit after applying mozilla patches."), needinfo=library.maintainer_bz)
                raise e

        # Submit to Try -----------------------
        try:
            platform_restriction = "linux64" if self.config['General']['separate-platforms'] else ""
            next_status = JOBSTATUS.AWAITING_INITIAL_PLATFORM_TRY_RESULTS if self.config['General']['separate-platforms'] else JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS
            try_run_type = 'initial platform' if self.config['General']['separate-platforms'] else 'all platforms'
            try_revision = self.taskclusterProvider.submit_to_try(library, platform_restriction)
            self.dbProvider.add_try_run(created_job, try_revision, try_run_type)
            self.dbProvider.update_job_status(created_job, newstatus=next_status)
            self.bugzillaProvider.comment_on_bug(created_job.bugzilla_id, CommentTemplates.TRY_RUN_SUBMITTED(try_revision))
        except Exception as e:
            self.dbProvider.update_job_status(created_job, JOBSTATUS.DONE, JOBOUTCOME.COULD_NOT_SUBMIT_TO_TRY)
            self.bugzillaProvider.comment_on_bug(created_job.bugzilla_id, CommentTemplates.COULD_NOT_GENERAL_ERROR("submit to try."), needinfo=library.maintainer_bz)
            raise e

        # Submit Phab Revision ----------------
        try:
            phab_revisions = self.phabricatorProvider.submit_patches(created_job.bugzilla_id, library.has_patches)
            assert len(phab_revisions) == 2 if library.has_patches else 1, "We don't have the correct number of phabricator patches; we have %s, expected %s" % (len(phab_revisions), 2 if library.has_patches else 1)
            self.dbProvider.add_phab_revision(created_job, phab_revisions[0], 'vendoring commit')
            if len(phab_revisions) > 1:
                self.dbProvider.add_phab_revision(created_job, phab_revisions[1], 'patches commit')
        except Exception as e:
            self.dbProvider.update_job_status(created_job, JOBSTATUS.DONE, JOBOUTCOME.COULD_NOT_SUBMIT_TO_PHAB)
            self.bugzillaProvider.comment_on_bug(created_job.bugzilla_id, CommentTemplates.COULD_NOT_GENERAL_ERROR("submit to phabricator."), needinfo=library.maintainer_bz)
            raise e

    # ====================================================================
    # ====================================================================

    @logEntryExit
    def _process_existing_job(self, library, task, existing_job):
        """
        AWAITING_INITIAL_PLATFORM_TRY_RESULTS
          If we see still-running jobs, keep state as-is, and finish.
          If we see a build failure, comment, set assignee, needinfo, and state to JOB_PROCESSING_DONE. Finish.
          Otherwise, trigger the rest of the platforms, set state to AWAITING_SECOND_PLATFORMS_TRY_RESULTS

        AWAITING_SECOND_PLATFORMS_TRY_RESULTS
          If we see still-running jobs, keep state as-is, and finish.
          If we see a build failure, comment, set assignee, needinfo, and state to JOB_PROCESSING_DONE. Finish.
          If we see test failures, accumulate them all, then retrigger each TRIGGER_TOTAL-1 times, set state to AWAITING_RETRIGGER_RESULTS. Finish
          If we see a lint failure, add ths note to a comment we will post.
          If we see a failures labeled intermittent, add this note to a comment we will post.
          If we have a comment accumulated, post it, set assignee, needinfo, set reviewer, and set state to JOB_PROCESSING_DONE
          If we have no comment accumulated, post that everything succeeded, set assignee, reviewer, and set state to JOB_PROCESSING_DONE

        AWAITING_RETRIGGER_RESULTS
          For every test failure, find the other failures.
            If every job in this set failed, add this note to a comment we will post.
            If some of the jobs succeeded, add this note to a comment we will post.
          Post the comment, set assignee, needinfo, set reviewr, and set state to JOB_PROCESSING_DONE
        """
        my_ff_version = self.config['General']['ff-version']

        if existing_job.status == JOBSTATUS.CREATED:
            # The job has been created; but for some reason was never set to a final status
            # (This has been observed when the worker the cronjob was running on shut down in the middle)
            self.logger.log("On job id %s for library %s revision %s we encountered an unexpected state." % (
                existing_job.id, existing_job.library_shortname, existing_job.version), level=LogLevel.Warning)
            if existing_job.bugzilla_id:
                self.bugzillaProvider.comment_on_bug(existing_job.bugzilla_id, CommentTemplates.UNEXPECTED_JOB_STATE())

            self.dbProvider.update_job_status(existing_job, JOBSTATUS.DONE, JOBOUTCOME.UNEXPECTED_CREATED_STATUS)
            self.dbProvider.update_job_relinquish(existing_job)

            # We also need to address the job _prior_ to this one and relinquish it as well to ensure that there is
            # at most one non-relinquished job and if present, it is the most recent
            self._process_prior_job(existing_job.prior_job, existing_job.bugzilla_id)

            raise Exception("Handled a Job with unexpected CREATED status in _process_existing_job")

        elif existing_job.status == JOBSTATUS.DONE:
            assert existing_job.bugzilla_is_open, "We are processing a job %s that is Done and the bugzilla bug is closed" % existing_job.id
            # The job has been completed, but the bugzilla bug is open and we need to double check if it has acknowleged our current FF version

            if my_ff_version in existing_job.ff_versions:
                self.logger.log("We found a job with id %s for revision %s that was already processed for this ff version (%s)." % (
                    existing_job.id, existing_job.version, my_ff_version), level=LogLevel.Info)
                return

            if existing_job.outcome in [JOBOUTCOME.SPURIOUS_UPDATE]:
                self.logger.log("We found a job with id %s for revision %s but its outcome (%s) is not relevant for firefox tracking." % (
                    existing_job.id, existing_job.version, existing_job.outcome), level=LogLevel.Info)
                return

            if not existing_job.bugzilla_id:
                raise Exception("We found a job with id %s for revision %s and we should mark a ff version for tracking but it does not have a bugzilla ID." % (
                    existing_job.id, existing_job.version))

            self.logger.log("We found a job with id %s for revision %s but it hasn't been processed for this ff version (%s) yet." % (
                existing_job.id, existing_job.version, my_ff_version), level=LogLevel.Info)
            self.bugzillaProvider.mark_ff_version_affected(existing_job.bugzilla_id, my_ff_version, affected=True)

            self.dbProvider.update_job_ff_versions(existing_job, my_ff_version)
            existing_job.ff_versions.add(my_ff_version)
            return

        elif existing_job.status == JOBSTATUS.AWAITING_INITIAL_PLATFORM_TRY_RESULTS:
            assert len(existing_job.try_runs) == 1, "State is AWAITING_INITIAL_PLATFORM_TRY_RESULTS, but we have %s try runs, not 1 (%s)." % (len(existing_job.try_runs), existing_job.get_try_run_ids())
            self._process_job_details_for_awaiting_initial_platform_results(library, task, existing_job)
        elif existing_job.status == JOBSTATUS.RELINQUISHED:
            self.logger.log("Job ID %s has the (obsolete) status RELINQUISHED so I am not going to try to process it." % existing_job.id, level=LogLevel.Info)
        else:
            if not self.config['General']['separate-platforms']:
                assert len(existing_job.try_runs) == 1, "Status is %s, but we have %s try runs, not 1 (%s)." % (existing_job.status, len(existing_job.try_runs), existing_job.get_try_run_ids())
            else:
                assert len(existing_job.try_runs) == 2, "Status is %s, but we have %s try runs, not 2 (%s)." % (existing_job.status, len(existing_job.try_runs), existing_job.get_try_run_ids())

            if existing_job.status == JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS:
                self._process_job_details_for_awaiting_second_platform_results(library, task, existing_job)
            elif existing_job.status == JOBSTATUS.AWAITING_RETRIGGER_RESULTS:
                self._process_job_details_for_awaiting_retrigger_results(library, task, existing_job)
            else:
                raise Exception("In _process_job_details for job with try revisions %s got a status %s I don't know how to handle." % (existing_job.get_try_run_ids(), existing_job.status))

    # ==================================

    # Returns (no_build_failures, results, comment_lines)
    @logEntryExit
    def _get_comments_on_push(self, library, existing_job):
        # Fetch the job list (and double check its status), and the push health
        job_list = []
        push_health = {}
        for t in existing_job.try_runs:
            this_job_list = self.taskclusterProvider.get_job_details(t.revision)
            job_list = self.taskclusterProvider.combine_job_lists(job_list, this_job_list)

            this_push_health = self.taskclusterProvider.get_push_health(t.revision)
            push_health = self.taskclusterProvider.combine_push_healths(push_health, this_push_health)

        if not self._job_is_completed_without_build_failures(library, existing_job, this_job_list):
            return (False, None, None)

        results = self.taskclusterProvider.determine_jobs_to_retrigger(push_health, job_list)

        def get_failed_summary_string(result_obj, include_task_ids):
            fails_tuple = (len(result_obj.failed()), len(result_obj.all()))
            if len(result_obj.all()) == 1:
                result = "%s of %s failed" % fails_tuple
            elif len(set([j.job_type_name for j in result_obj.all()])) != 1:
                result = "%s of %s failed on different tasks" % fails_tuple
            else:
                result = "%s of %s failed on the same (retriggered) task" % fails_tuple
            if include_task_ids:
                result += " (failed: " + ", ".join([j.task_id for j in result_obj.failed()]) + ")"

            return result

        # Once (Bug 1804797) push health returned an odd name I hadn't seen before
        # this function handles this scenario so the comment is readable
        def handle_multiline_name(s):
            if "\n" not in s:
                return s
            return "> " + s.replace("\n", "\n  > ")

        task_ids_weve_reported = set()

        # The order in which we go through the results matter, and is tied to the priority we want to give to the classifications.
        # For example, if Push Health says something is a New Failure, but Taskcluster says it's NotYourFault.
        # Our Priority List is: NotYourFault, NewFailure, Possible Intermittent

        # First lint failures though.
        lint_lines = ["**Lint Jobs Failed**"]
        for j in job_list:
            if j.result not in ["retry", "success"]:
                if "mozlint" in j.job_type_name:
                    task_ids_weve_reported.add(j.task_id)
                    lint_lines.append("- %s (%s)" % (j.job_type_name, j.task_id))

        # Then Not Your Fault
        not_your_fault_lines = ["**Known Issues**:"]
        for t in results['tasks_by_testname']:
            if not results['tasks_by_testname'][t].failed():
                continue
            if results['tasks_by_testname'][t].classification == Classification.NotYourFault:
                not_your_fault_lines.append("")
                not_your_fault_lines.append("- " + handle_multiline_name(t))
                for j in results['tasks_by_testname'][t].failed():
                    task_ids_weve_reported.add(j.task_id)
                    not_your_fault_lines.append("\t\t- %s (%s)" % (j.job_type_name, j.task_id))

        for t in results['tasks_by_jobname']:
            if not results['tasks_by_jobname'][t].failed():
                continue
            if results['tasks_by_jobname'][t].classification == Classification.NotYourFault:
                if set([j.task_id for j in results['tasks_by_jobname'][t].failed()]) - task_ids_weve_reported:
                    not_your_fault_lines.append("- " + handle_multiline_name(t) + " - " + get_failed_summary_string(results['tasks_by_jobname'][t], True))

        # Then New Failures
        high_priority_lines = ["**Needs Close Investigation**:"]
        for t in results['tasks_by_testname']:
            if not results['tasks_by_testname'][t].failed():
                continue
            if results['tasks_by_testname'][t].classification == Classification.NewFailure:
                high_priority_lines.append("")
                high_priority_lines.append("- " + handle_multiline_name(t))
                if len(results['tasks_by_testname'][t].all()) > 1:
                    high_priority_lines.append("  - " + get_failed_summary_string(results['tasks_by_testname'][t], False))
                for j in results['tasks_by_testname'][t].failed():
                    task_ids_weve_reported.add(j.task_id)
                    high_priority_lines.append("\t\t- %s (%s)" % (j.job_type_name, j.task_id))

        for t in results['tasks_by_jobname']:
            if not results['tasks_by_jobname'][t].failed():
                continue
            if results['tasks_by_jobname'][t].classification == Classification.NewFailure:
                # Only report this group if we haven't reported all the failed tasks already
                if set([j.task_id for j in results['tasks_by_jobname'][t].failed()]) - task_ids_weve_reported:
                    high_priority_lines.append("- " + handle_multiline_name(t) + " - " + get_failed_summary_string(results['tasks_by_jobname'][t], True))

        # Finally intermittents
        intermittent_lines = ["**Needs Investigation (Possible Intermittents)**:"]
        for t in results['tasks_by_testname']:
            if not results['tasks_by_testname'][t].failed():
                continue
            if results['tasks_by_testname'][t].classification == Classification.PossibleIntermittent:
                intermittent_lines.append("")
                intermittent_lines.append("- " + handle_multiline_name(t))
                if len(results['tasks_by_testname'][t].all()) > 1:
                    intermittent_lines.append("  - " + get_failed_summary_string(results['tasks_by_testname'][t], False))
                for j in results['tasks_by_testname'][t].failed():
                    task_ids_weve_reported.add(j.task_id)
                    intermittent_lines.append("\t\t- %s (%s)" % (j.job_type_name, j.task_id))

        for t in results['tasks_by_jobname']:
            if not results['tasks_by_jobname'][t].failed():
                continue
            if results['tasks_by_jobname'][t].classification == Classification.PossibleIntermittent:
                if set([j.task_id for j in results['tasks_by_jobname'][t].failed()]) - task_ids_weve_reported:
                    intermittent_lines.append("- " + handle_multiline_name(t) + " - " + get_failed_summary_string(results['tasks_by_jobname'][t], True))

        comment_lines = list()
        comment_lines.extend((lint_lines + [""]) if len(lint_lines) > 1 else [])
        comment_lines.extend((high_priority_lines + [""]) if len(high_priority_lines) > 1 else [])
        comment_lines.extend((intermittent_lines + [""]) if len(intermittent_lines) > 1 else [])
        comment_lines.extend((not_your_fault_lines + [""]) if len(not_your_fault_lines) > 1 else [])

        results['classifications'] = set()
        results['classifications'].add(Classification.NewFailure if len(high_priority_lines) > 1 else None)
        results['classifications'].add(Classification.PossibleIntermittent if len(intermittent_lines) > 1 else None)
        results['classifications'].add(Classification.NotYourFault if len(not_your_fault_lines) > 1 else None)

        return (True, results, comment_lines)

    @logEntryExitNoArgs
    def _job_is_completed_without_build_failures(self, library, existing_job, job_list):
        if not job_list:
            self.logger.log("Try revision had no job results. Skipping this job.", level=LogLevel.Warning)
            return False

        # If there's only one job, and it's an exception we hit a really bad luck
        # case where the Decision task excepted. Ordinarily we would try to retrigger
        # it, but that will fail, so we should handle this case.
        if len(job_list) == 1 and job_list[0].result in ["exception", "busted"]:
            self.bugzillaProvider.comment_on_bug(existing_job.bugzilla_id, CommentTemplates.COULD_NOT_GENERAL_ERROR("submit to try. It appears that the Decision task did not succeed."), needinfo=library.maintainer_bz if existing_job.bugzilla_is_open else None)
            self.dbProvider.update_job_status(existing_job, JOBSTATUS.DONE, JOBOUTCOME.COULD_NOT_SUBMIT_TO_TRY)
            return False

        for j in job_list:
            if j.state not in ["completed", "failed", "exception"]:
                self.logger.log("Not all jobs on the try revision are completed, so skipping this job until they are.", level=LogLevel.Info)
                return False

        # First, look for any failed build jobs
        for j in job_list:
            if j.result not in ["retry", "success"]:
                if "build" in j.job_type_name:
                    self.bugzillaProvider.comment_on_bug(existing_job.bugzilla_id, CommentTemplates.DONE_BUILD_FAILURE(library), needinfo=library.maintainer_bz if existing_job.bugzilla_is_open else None)
                    if not existing_job.relinquished:
                        for p in existing_job.phab_revisions:
                            try:
                                self.phabricatorProvider.abandon(p.revision)
                            except Exception:
                                self.bugzillaProvider.comment_on_bug(existing_job.bugzilla_id, CommentTemplates.COULD_NOT_GENERAL_ERROR("abandon the phabricator revision %s" % p.revision), needinfo=library.maintainer_bz)
                    self.dbProvider.update_job_status(existing_job, JOBSTATUS.DONE, JOBOUTCOME.BUILD_FAILED)
                    return False

        return True

    # ==================================

    @logEntryExitNoArgs
    def _process_job_details_for_awaiting_initial_platform_results(self, library, task, existing_job):
        try_revision_1 = existing_job.try_runs[0].revision
        self.logger.log("Handling try revision %s in Awaiting Initial Platform Results" % try_revision_1)

        job_list = self.taskclusterProvider.get_job_details(try_revision_1)
        if not self._job_is_completed_without_build_failures(library, existing_job, job_list):
            return

        if not existing_job.bugzilla_is_open:
            self.logger.log("The bugzilla bug has been closed, so we will only summarize results.", level=LogLevel.Info)
            self._process_job_details_for_awaiting_retrigger_results(library, task, existing_job)
            return

        self.logger.log("All jobs completed, we're going to go to the next set of platforms.", level=LogLevel.Info)

        # Re-Vendor -------------------
        try:
            self.vendorProvider.vendor(library, existing_job.version)
        except Exception as e:
            self.dbProvider.update_job_status(existing_job, JOBSTATUS.DONE, JOBOUTCOME.COULD_NOT_REVENDOR)
            self.bugzillaProvider.comment_on_bug(existing_job.bugzilla_id, CommentTemplates.COULD_NOT_GENERAL_ERROR("re-vendor the library."), needinfo=library.maintainer_bz)
            raise e

        # Re-Commit -------------------
        try:
            self.mercurialProvider.commit(library, existing_job.bugzilla_id, existing_job.version)
        except Exception as e:
            self.dbProvider.update_job_status(existing_job, JOBSTATUS.DONE, JOBOUTCOME.COULD_NOT_COMMIT)
            self.bugzillaProvider.comment_on_bug(existing_job.bugzilla_id, CommentTemplates.COULD_NOT_GENERAL_ERROR("commit the updated library."), needinfo=library.maintainer_bz)
            raise e

        if library.has_patches:
            # Apply Patches -------------------
            try:
                self.vendorProvider.patch(library, existing_job.version)
            except Exception as e:
                if isinstance(e, subprocess.CalledProcessError):
                    msg = ("stderr:\n" + e.stderr.decode().rstrip() + "\n\n") if e.stderr else ""
                    msg += ("stdout:\n" + e.stdout.decode().rstrip()) if e.stdout else ""
                else:
                    msg = str(e)
                self.dbProvider.update_job_status(existing_job, JOBSTATUS.DONE, JOBOUTCOME.COULD_NOT_PATCH)
                self.bugzillaProvider.comment_on_bug(existing_job.bugzilla_id, CommentTemplates.COULD_NOT_GENERAL_ERROR("apply the mozilla patches.", errormessage=msg), needinfo=library.maintainer_bz)
                return
            # Commit Patches ------------------
            try:
                self.mercurialProvider.commit_patches(library, existing_job.bugzilla_id, existing_job.version)
            except Exception as e:
                self.dbProvider.update_job_status(existing_job, JOBSTATUS.DONE, JOBOUTCOME.COULD_NOT_COMMIT_PATCHES)
                self.bugzillaProvider.comment_on_bug(existing_job.bugzilla_id, CommentTemplates.COULD_NOT_GENERAL_ERROR("commit after applying mozilla patches."), needinfo=library.maintainer_bz)
                raise e

        # Submit to Try -------------------
        try:
            try_revision_2 = self.taskclusterProvider.submit_to_try(library, "!linux64")
            self.dbProvider.add_try_run(existing_job, try_revision_2, 'more platforms')
            self.bugzillaProvider.comment_on_bug(existing_job.bugzilla_id, CommentTemplates.TRY_RUN_SUBMITTED(try_revision_2, another=True))
            self.dbProvider.update_job_status(existing_job, newstatus=JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS)
        except Exception as e:
            self.dbProvider.update_job_status(existing_job, JOBSTATUS.DONE, JOBOUTCOME.COULD_NOT_SUBMIT_TO_TRY)
            self.bugzillaProvider.comment_on_bug(existing_job.bugzilla_id, CommentTemplates.COULD_NOT_GENERAL_ERROR("submit to try."), needinfo=library.maintainer_bz)
            raise e

    # ==================================

    @logEntryExitNoArgs
    def _process_job_details_for_awaiting_second_platform_results(self, library, task, existing_job):
        try_run_index = 1 if self.config['General']['separate-platforms'] else 0
        try_revision = existing_job.try_runs[try_run_index].revision
        self.logger.log("Handling try revision number %i (%s) in Awaiting Second Platform Results" % (try_run_index + 1, try_revision), level=LogLevel.Info)

        # Get the push health and a comment string we may use in the bug.
        # Along the way, confirm that all the jobs have succeeded and there are no build failures
        no_build_failures, results, comment_lines = self._get_comments_on_push(library, existing_job)
        if not no_build_failures:
            return

        # If we need to retrigger jobs
        if results['to_retrigger'] and existing_job.bugzilla_is_open:
            self.logger.log("All jobs completed, we found failures we need to retrigger, going to retrigger %s jobs: " % len(results['to_retrigger']), level=LogLevel.Info)
            for j in results['to_retrigger']:
                self.logger.log(j.job_type_name + " " + j.task_id, level=LogLevel.Debug)
            self.taskclusterProvider.retrigger_jobs(results['to_retrigger'])
            self.dbProvider.update_job_status(existing_job, newstatus=JOBSTATUS.AWAITING_RETRIGGER_RESULTS)
            return
        elif results['to_retrigger']:
            self.logger.log("While there were things we'd retrigger, the bugzilla bug has been closed, so we will only summarize results.", level=LogLevel.Info)

        self._process_job_results(library, task, existing_job, results, comment_lines)

    # ==================================

    @logEntryExitNoArgs
    def _process_job_details_for_awaiting_retrigger_results(self, library, task, existing_job):
        self.logger.log("Handling try runs in Awaiting Retrigger Results")

        # Get the push health and a comment string we will use in the bug
        no_build_failures, results, comment_lines = self._get_comments_on_push(library, existing_job)
        if no_build_failures:
            self._process_job_results(library, task, existing_job, results, comment_lines)

    # ==================================

    @logEntryExitNoArgs
    def _process_job_results(self, library, task, existing_job, results, comment_lines):
        # We don't need to retrigger jobs, but we do have unclassified failures:
        if results['classifications'].intersection(set([Classification.PossibleIntermittent, Classification.NewFailure])):
            self._process_unclassified_failures(library, task, existing_job, comment_lines)

        # We don't need to retrigger and we don't have unclassified failures but we do have failures
        elif results['classifications'].intersection(set([Classification.NotYourFault])):
            self._process_classified_failures(library, task, existing_job, comment_lines)

        # Everything.... succeeded?
        else:
            self._process_success(library, task, existing_job, comment_lines)

    # ==================================

    @logEntryExitNoArgs
    def _process_unclassified_failures(self, library, task, existing_job, comment_lines):
        comment = "The try push is done, we found jobs with unclassified failures.\n\n"
        self.logger.log(comment.strip(), level=LogLevel.Info)

        for c in comment_lines:
            comment += c + "\n"
            self.logger.log(c, level=LogLevel.Debug)

        self.bugzillaProvider.comment_on_bug(
            existing_job.bugzilla_id,
            CommentTemplates.DONE_UNCLASSIFIED_FAILURE(comment, library),
            needinfo=library.maintainer_bz if existing_job.bugzilla_is_open else None,
            assignee=(existing_job.bugzilla_assignee or library.maintainer_bz) if existing_job.bugzilla_is_open else None)

        self.dbProvider.update_job_status(existing_job, JOBSTATUS.DONE, JOBOUTCOME.UNCLASSIFIED_FAILURES)

    # ==================================

    @logEntryExitNoArgs
    def _process_classified_failures(self, library, task, existing_job, comment_lines):
        comment = "All jobs completed, we found the following issues.\n\n"
        self.logger.log(comment.strip(), level=LogLevel.Info)

        for c in comment_lines:
            self.logger.log(c, level=LogLevel.Debug)
            comment += c + "\n"

        self.bugzillaProvider.comment_on_bug(
            existing_job.bugzilla_id,
            CommentTemplates.DONE_CLASSIFIED_FAILURE(comment, library),
            assignee=(existing_job.bugzilla_assignee or library.maintainer_bz) if existing_job.bugzilla_is_open else None)

        self.dbProvider.update_job_status(existing_job, JOBSTATUS.DONE, JOBOUTCOME.CLASSIFIED_FAILURES)

        if existing_job.bugzilla_is_open:
            try:
                for p in existing_job.phab_revisions:
                    self.phabricatorProvider.set_reviewer(p.revision, library.maintainer_phab)
            except Exception as e:
                self.dbProvider.update_job_status(existing_job, JOBSTATUS.DONE, JOBOUTCOME.COULD_NOT_SET_PHAB_REVIEWER)
                self.bugzillaProvider.comment_on_bug(
                    existing_job.bugzilla_id,
                    CommentTemplates.COULD_NOT_GENERAL_ERROR("set you as a reviewer in phabricator."),
                    needinfo=library.maintainer_bz)
                raise e

    # ==================================

    @logEntryExitNoArgs
    def _process_success(self, library, task, existing_job, comment_lines):
        self.logger.log("All jobs completed and we got a clean try run!", level=LogLevel.Info)

        self.bugzillaProvider.comment_on_bug(
            existing_job.bugzilla_id,
            CommentTemplates.DONE_ALL_SUCCESS(),
            assignee=(existing_job.bugzilla_assignee or library.maintainer_bz) if existing_job.bugzilla_is_open else None)

        self.dbProvider.update_job_status(existing_job, JOBSTATUS.DONE, JOBOUTCOME.ALL_SUCCESS)

        if existing_job.bugzilla_is_open:
            try:
                for p in existing_job.phab_revisions:
                    self.phabricatorProvider.set_reviewer(p.revision, library.maintainer_phab)
            except Exception as e:
                self.dbProvider.update_job_status(existing_job, JOBSTATUS.DONE, JOBOUTCOME.COULD_NOT_SET_PHAB_REVIEWER)
                self.bugzillaProvider.comment_on_bug(
                    existing_job.bugzilla_id,
                    CommentTemplates.COULD_NOT_GENERAL_ERROR("set you as a reviewer in phabricator."),
                    needinfo=library.maintainer_bz)
                raise e
