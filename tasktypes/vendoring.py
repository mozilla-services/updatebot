#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from components.bugzilla import CommentTemplates
from components.dbmodels import JOBSTATUS, JOBOUTCOME, JOBTYPE
from components.logging import LogLevel, logEntryExit, logEntryExitNoArgs


class VendorTaskRunner:
    def __init__(self, provider_dictionary, config_dictionary):
        self.__dict__.update(provider_dictionary)
        self.logger = self.loggingProvider
        self.config_dictionary = config_dictionary

    # ====================================================================

    def process_task(self, library, task):
        assert task.type == 'vendoring'

        new_version, timestamp = self.vendorProvider.check_for_update(library)
        if not new_version:
            self.logger.log("Processing %s but no new version was found." % library.name, level=LogLevel.Info)
            return

        self.logger.log("Processing %s for an upstream revision %s." % (library.name, new_version), level=LogLevel.Info)
        existing_job = self.dbProvider.get_job(library, new_version)
        if existing_job:
            self.logger.log("%s has an existing job with %s try revisions (%s) and status %s" % (new_version, len(existing_job.try_runs), existing_job.get_try_run_ids(), existing_job.status), level=LogLevel.Info)
            self._process_existing_job(library, task, existing_job)
        else:
            self.logger.log("%s is a brand new revision to updatebot." % (new_version), level=LogLevel.Info)
            self._process_new_job(library, task, new_version, timestamp)

        # TODO #119: We need to remove any commits we made so the repo is clean for the next library.

    # ====================================================================

    @logEntryExit
    def _process_new_job(self, library, task, new_version, timestamp):
        see_also = []

        # First, we need to see if there was a previously active job for this library.
        # If so, we need to close that job out.
        active_jobs = self.dbProvider.get_all_active_jobs_for_library(library)
        assert len(active_jobs) <= 1, "Got more than one active job for library %s" % (library.name)
        self.logger.log("Found %i active jobs for this library" % len(active_jobs), level=LogLevel.Info)
        if len(active_jobs) == 1:
            active_job = active_jobs[0]
            self.bugzillaProvider.close_bug(active_job.bugzilla_id, CommentTemplates.BUG_SUPERSEDED())
            self.phabricatorProvider.abandon(active_job.phab_revision)
            active_job.status = JOBSTATUS.DONE
            active_job.outcome = JOBOUTCOME.ABORTED
            self.dbProvider.update_job_status(active_job)
            see_also.append(active_job.bugzilla_id)

        # Now we can process the new job
        bugzilla_id = self.bugzillaProvider.file_bug(library, CommentTemplates.UPDATE_SUMMARY(library, new_version, timestamp), "", task.cc, see_also)

        try_run_type = 'initial platform' if self.config_dictionary['General']['separate-platforms'] else 'all platforms'

        try:
            self.vendorProvider.vendor(library)
        except Exception:
            # Handle `./mach vendor` failing
            self.dbProvider.create_job(JOBTYPE.VENDORING, library, new_version, JOBSTATUS.DONE, JOBOUTCOME.COULD_NOT_VENDOR, bugzilla_id, phab_revision=None)
            self.bugzillaProvider.comment_on_bug(bugzilla_id, CommentTemplates.COULD_NOT_VENDOR(""))  # TODO, put error message
            return

        self.mercurialProvider.commit(library, bugzilla_id, new_version)

        platform_restriction = "linux64" if self.config_dictionary['General']['separate-platforms'] else ""
        next_status = JOBSTATUS.AWAITING_INITIAL_PLATFORM_TRY_RESULTS if self.config_dictionary['General']['separate-platforms'] else JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS
        try_revision = self.taskclusterProvider.submit_to_try(library, platform_restriction)

        self.bugzillaProvider.comment_on_bug(bugzilla_id, CommentTemplates.TRY_RUN_SUBMITTED(try_revision))
        phab_revision = self.phabricatorProvider.submit_patch()
        self.dbProvider.create_job(JOBTYPE.VENDORING, library, new_version, next_status, JOBOUTCOME.PENDING, bugzilla_id, phab_revision, try_revision, try_run_type)

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
        if existing_job.status == JOBSTATUS.DONE:
            self.logger.log("This job has already been completed")
            return

        if existing_job.status == JOBSTATUS.AWAITING_INITIAL_PLATFORM_TRY_RESULTS:
            if len(existing_job.try_runs) != 1:
                self.logger.log("State is AWAITING_INITIAL_PLATFORM_TRY_RESULTS, but we have %s try runs, not 1 (%s)." % (len(existing_job.try_runs), existing_job.get_try_run_ids()), level=LogLevel.Error)
                return
            self._process_job_details_for_awaiting_initial_platform_results(library, task, existing_job)
        elif existing_job.status == JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS:
            if not self.config_dictionary['General']['separate-platforms'] and len(existing_job.try_runs) != 1:
                self.logger.log("State is AWAITING_SECOND_PLATFORMS_TRY_RESULTS, but we have %s try runs, not 1 (%s)." % (len(existing_job.try_runs), existing_job.get_try_run_ids()), level=LogLevel.Error)
                return
            elif self.config_dictionary['General']['separate-platforms'] and len(existing_job.try_runs) != 2:
                self.logger.log("State is AWAITING_SECOND_PLATFORMS_TRY_RESULTS, but we have %s try runs, not 2 (%s)." % (len(existing_job.try_runs), existing_job.get_try_run_ids()), level=LogLevel.Error)
                return
            self._process_job_details_for_awaiting_second_platform_results(library, task, existing_job)
        elif existing_job.status == JOBSTATUS.AWAITING_RETRIGGER_RESULTS:
            if not self.config_dictionary['General']['separate-platforms'] and len(existing_job.try_runs) != 1:
                self.logger.log("State is AWAITING_RETRIGGER_RESULTS, but we have %s try runs, not 1 (%s)." % (len(existing_job.try_runs), existing_job.get_try_run_ids()), level=LogLevel.Error)
                return
            elif self.config_dictionary['General']['separate-platforms'] and len(existing_job.try_runs) != 2:
                self.logger.log("State is AWAITING_RETRIGGER_RESULTS, but we have %s try runs, not 2 (%s)." % (len(existing_job.try_runs), existing_job.get_try_run_ids()), level=LogLevel.Error)
                return
            self._process_job_details_for_awaiting_retrigger_results(library, task, existing_job)
        else:
            raise Exception("In _process_job_details for job with try revisions %s got a status %s I don't know how to handle." % (existing_job.get_try_run_ids(), existing_job.status))

    # ==================================

    @logEntryExit
    def _get_comments_on_push(self, library, existing_job):
        # Fetch the job list (and double check its status), and the push health
        job_list = []
        push_health = {}
        for t in existing_job.try_runs:
            this_job_list = self.taskclusterProvider.get_job_details(t.revision)
            if not self._job_is_completed_without_build_failures(library, existing_job, this_job_list):
                return (False, None, None)
            job_list = self.taskclusterProvider.combine_job_lists(job_list, this_job_list)

            this_push_health = self.taskclusterProvider.get_push_health(t.revision)
            push_health = self.taskclusterProvider.combine_push_healths(push_health, this_push_health)

        results = self.taskclusterProvider.determine_jobs_to_retrigger(push_health, job_list)

        # Before we retrieve the push health, process the failed jobs for build or lint failures.
        comment_lines = []
        printed_lint_header = False
        for j in job_list:
            if j.result not in ["retry", "success"]:
                if "mozlint" in j.job_type_name:
                    if not printed_lint_header:
                        comment_lines.append("**Lint Jobs Failed**:")
                        printed_lint_header = True
                    comment_lines.append("\t\t- %s (%s)" % (j.job_type_name, j.task_id))

        # Build up the comment we will leave
        if results['known_issues']:
            comment_lines.append("**Known Issues (From Push Health)**:")
            for t in results['known_issues']:
                comment_lines.append("\t" + t)
                for j in results['known_issues'][t]:
                    comment_lines.append("\t\t- %s (%s)" % (j.job_type_name, j.task_id))

        if results['taskcluster_classified']:
            comment_lines.append("**Known Issues (From Taskcluster)**:")
            for j in results['taskcluster_classified']:
                comment_lines.append("\t\t- %s (%s) - %s" % (j.job_type_name, j.task_id, self.taskclusterProvider.failure_classifications[j.failure_classification_id]))

        if results['to_investigate']:
            comment_lines.append("**Needs Investigation**:")
            for t in results['to_investigate']:
                comment_lines.append("\t" + t)
                for j in results['to_investigate'][t]:
                    comment_lines.append("\t\t- %s (%s)" % (j.job_type_name, j.task_id))

        return (True, results, comment_lines)

    @logEntryExitNoArgs
    def _job_is_completed_without_build_failures(self, library, existing_job, job_list):
        if not job_list:
            self.logger.log("Try revision had no job results. Skipping this job.", level=LogLevel.Warning)
            return False

        for j in job_list:
            if j.state not in ["completed", "failed", "exception"]:
                self.logger.log("Not all jobs on the try revision are completed, so skipping this job until they are.", level=LogLevel.Info)
                return False

        # First, look for any failed build jobs
        for j in job_list:
            if j.result not in ["retry", "success"]:
                if "build" in j.job_type_name:
                    self.bugzillaProvider.comment_on_bug(existing_job.bugzilla_id, CommentTemplates.DONE_BUILD_FAILURE(library), needinfo=library.maintainer_bz)
                    self.phabricatorProvider.abandon(existing_job.phab_revision)
                    existing_job.status = JOBSTATUS.DONE
                    existing_job.outcome = JOBOUTCOME.BUILD_FAILED
                    self.dbProvider.update_job_status(existing_job)
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

        self.logger.log("All jobs completed, we're going to go to the next set of platforms.", level=LogLevel.Info)

        self.vendorProvider.vendor(library)
        self.mercurialProvider.commit(library, existing_job.bugzilla_id, existing_job.version)

        try_revision_2 = self.taskclusterProvider.submit_to_try(library, "!linux64")
        self.dbProvider.add_try_run(existing_job, try_revision_2, 'more platforms')
        self.bugzillaProvider.comment_on_bug(existing_job.bugzilla_id, CommentTemplates.TRY_RUN_SUBMITTED(try_revision_2, another=True))
        existing_job.status = JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS
        self.dbProvider.update_job_status(existing_job)

    # ==================================

    @logEntryExitNoArgs
    def _process_job_details_for_awaiting_second_platform_results(self, library, task, existing_job):
        try_run_index = 1 if self.config_dictionary['General']['separate-platforms'] else 0
        try_revision = existing_job.try_runs[try_run_index].revision
        self.logger.log("Handling try revision number %i (%s) in Awaiting Second Platform Results" % (try_run_index + 1, try_revision), level=LogLevel.Info)

        # Get the push health and a comment string we may use in the bug.
        # Along the way, confirm that all the jobs have succeeded and there are no build failures
        success, results, comment_lines = self._get_comments_on_push(library, existing_job)
        if not success:
            return

        # If we need to retrigger jobs
        if results['to_retrigger']:
            self.logger.log("All jobs completed, we found failures we need to retrigger, going to retrigger %s jobs: " % len(results['to_retrigger']), level=LogLevel.Info)
            for j in results['to_retrigger']:
                self.logger.log(j.job_type_name + " " + j.task_id, level=LogLevel.Debug)
            self.taskclusterProvider.retrigger_jobs(results['to_retrigger'])
            existing_job.status = JOBSTATUS.AWAITING_RETRIGGER_RESULTS
            self.dbProvider.update_job_status(existing_job)
            return

        # We don't need to retrigger jobs, but we do have unclassified failures:
        if results['to_investigate'] and comment_lines:
            # This updates the job status to DONE, so return immediately after
            self._process_unclassified_failures(library, task, existing_job, comment_lines)
            return

        # We don't need to retrigger and we don't have unclassified failures but we do have failures
        if comment_lines:
            comment = "All jobs completed, we found the following issues.\n"
            self.logger.log(comment, level=LogLevel.Info)
            existing_job.outcome = JOBOUTCOME.CLASSIFIED_FAILURES
            for c in comment_lines:
                self.logger.log(c, level=LogLevel.Debug)
                comment += c + "\n"

            self.bugzillaProvider.comment_on_bug(existing_job.bugzilla_id, CommentTemplates.DONE_CLASSIFIED_FAILURE(comment, library), needinfo=library.maintainer_bz, assignee=library.maintainer_bz)
            self.phabricatorProvider.set_reviewer(existing_job.phab_revision, library.maintainer_phab)

        # Everything.... succeeded?
        else:
            self.logger.log("All jobs completed and we got a clean try run!", level=LogLevel.Info)
            existing_job.outcome = JOBOUTCOME.ALL_SUCCESS
            self.bugzillaProvider.comment_on_bug(existing_job.bugzilla_id, CommentTemplates.DONE_ALL_SUCCESS(), assignee=library.maintainer_bz)
            self.phabricatorProvider.set_reviewer(existing_job.phab_revision, library.maintainer_phab)

        existing_job.status = JOBSTATUS.DONE
        self.dbProvider.update_job_status(existing_job)

    # ==================================

    @logEntryExitNoArgs
    def _process_job_details_for_awaiting_retrigger_results(self, library, task, existing_job):
        self.logger.log("Handling try runs in Awaiting Retrigger Results")

        # Get the push health and a comment string we will use in the bug
        success, results, comment_lines = self._get_comments_on_push(library, existing_job)
        if success:
            self._process_unclassified_failures(library, task, existing_job, comment_lines)

    # ==================================

    @logEntryExitNoArgs
    def _process_unclassified_failures(self, library, task, existing_job, comment_bullets):
        comment = "The try push is done, we found jobs with unclassified failures.\n"
        self.logger.log(comment.strip(), level=LogLevel.Info)

        for c in comment_bullets:
            comment += c + "\n"
            self.logger.log(c, level=LogLevel.Debug)

        self.bugzillaProvider.comment_on_bug(existing_job.bugzilla_id, CommentTemplates.DONE_UNCLASSIFIED_FAILURE(comment, library), needinfo=library.maintainer_bz)
        self.phabricatorProvider.abandon(existing_job.phab_revision)
        existing_job.outcome = JOBOUTCOME.UNCLASSIFIED_FAILURES
        existing_job.status = JOBSTATUS.DONE
        self.dbProvider.update_job_status(existing_job)
