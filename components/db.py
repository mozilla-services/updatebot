#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from components.utilities import Struct
from components.logging import logEntryExit
from components.providerbase import BaseProvider, INeedsLoggingProvider
from components.logging import LogLevel
from components.dbmodels import TryRun, transform_job_and_try_results_into_objects, JOBSTATUS, JOBOUTCOME

import pymysql


# ==================================================================================


class HardcodedDatabase:
    def __init__(self, database_config):
        pass

    def check_database(self):
        return 1

    def have_job(self, library, new_version):
        return False

    def create_job(self, library, new_version, bug_id, try_run):
        pass

# ==================================================================================


CURRENT_DATABASE_CONFIG_VERSION = 6

CREATION_QUERIES = {
    "config": """
      CREATE TABLE `config` (
        `k` varchar(255) NOT NULL,
        `v` varchar(255) NOT NULL
      )
      ENGINE = InnoDB DEFAULT CHARSET = UTF8MB4
      """,
    "status_types": """
      CREATE TABLE `status_types` (
        `id` TINYINT NOT NULL,
        `name` VARCHAR(255) NOT NULL,
        PRIMARY KEY (`id`)
      ) ENGINE = InnoDB;
      """,
    "outcome_types": """
      CREATE TABLE `outcome_types` (
        `id` TINYINT NOT NULL,
        `name` VARCHAR(255) NOT NULL,
        PRIMARY KEY (`id`)
      ) ENGINE = InnoDB;
      """,
    "jobs": """
      CREATE TABLE `jobs` (
        `id` INT NOT NULL AUTO_INCREMENT,
        `library` VARCHAR(255) NOT NULL,
        `version` VARCHAR(64) NOT NULL ,
        `status` TINYINT NOT NULL,
        `outcome` TINYINT NOT NULL,
        `bugzilla_id` INT NULL,
        `phab_revision` INT NULL,
        `try_revision` VARCHAR(40) NULL,
        PRIMARY KEY (`id`)
      ) ENGINE = InnoDB;
      """,
    "try_runs": """
      CREATE TABLE `try_runs` (
        `id` INT NOT NULL AUTO_INCREMENT,
        `revision` VARCHAR(40) NULL,
        `job_id` INT NOT NULL,
        `purpose` VARCHAR(255) NOT NULL,
        PRIMARY KEY (`id`)
      ) ENGINE = InnoDB;
      """,
}

# To support the --delete-database option, the key to this dictionary must be table_name|constraint_name
ALTER_QUERIES = {
    'jobs|fk_job_outcome':
        "ALTER TABLE jobs ADD CONSTRAINT fk_job_outcome FOREIGN KEY (outcome) REFERENCES outcome_types(id)",
    'jobs|fk_job_status':
        "ALTER TABLE jobs ADD CONSTRAINT fk_job_status FOREIGN KEY (status) REFERENCES status_types(id)",
    'try_runs|fk_tryrun_job':
        "ALTER TABLE try_runs ADD CONSTRAINT fk_tryrun_job FOREIGN KEY (job_id) REFERENCES jobs(id)",
}

INSERTION_QUERIES = [
    Struct(**{
        'query': "INSERT INTO `config` (`k`, `v`) VALUES ('enabled', %s)",
        'args': (1)
    }),
    Struct(**{
        'query': "INSERT INTO `config` (`k`, `v`) VALUES ('database_version', %s)",
        'args': (CURRENT_DATABASE_CONFIG_VERSION)
    })
]

for p in dir(JOBSTATUS):
    if p[0] != '_':
        INSERTION_QUERIES.append(
            Struct(**{
                'query': "INSERT INTO `status_types` (`id`, `name`) VALUES (%s, %s)",
                'args': (getattr(JOBSTATUS, p), p)
            }))

for p in dir(JOBOUTCOME):
    if p[0] != '_':
        INSERTION_QUERIES.append(
            Struct(**{
                'query': "INSERT INTO `outcome_types` (`id`, `name`) VALUES (%s, %s)",
                'args': (getattr(JOBOUTCOME, p), p)
            }))
# ==================================================================================


class MySQLDatabase(BaseProvider, INeedsLoggingProvider):
    def __init__(self, database_config):
        self._successfully_created_tmp_db = False
        self.database_config = database_config
        self.connection = pymysql.connect(
            host=database_config['host'],
            user=database_config['user'],
            password=database_config['password'],
            charset='utf8',
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True)

        if database_config.get('use_tmp_db', False):
            with self.connection.cursor() as cursor:
                cursor.execute("create database " + database_config['db'] + ";")
                self._successfully_created_tmp_db = True
                cursor.execute("use " + database_config['db'])

            with self.connection.cursor() as cursor:
                cursor.execute("show tables")
                results = cursor.fetchall()
                for r in results:
                    print(r)
        else:
            with self.connection.cursor() as cursor:
                cursor.execute("use " + database_config['db'])

    def __del__(self):
        if self.database_config.get('use_tmp_db', False) and self._successfully_created_tmp_db:
            with self.connection.cursor() as cursor:
                self.logger.log("Dropping database " + self.database_config['db'], level=LogLevel.Info)
                cursor.execute("drop database " + self.database_config['db'])

    def _query_get_single(self, query):
        with self.connection.cursor() as cursor:
            cursor.execute(query)
            results = cursor.fetchall()
            if len(results) != 1:
                raise Exception(
                    "get_single database query returned multiple rows")
            if len(results[0].values()) != 1:
                raise Exception(
                    "get_single database query returned multiple columns")
            return list(results[0].values())[0]

    def _query_get_rows(self, query, args=()):
        with self.connection.cursor() as cursor:
            cursor.execute(query, args)
            results = cursor.fetchall()
            return results

    def _query_get_row_maybe(self, query, args=()):
        results = self._query_get_rows(query, args)
        if len(results) > 1:
            raise Exception(
                "get_row_maybe database query returned multiple rows")
        return results[0] if results else None

    def _query_execute(self, query, args=()):
        insert_id = None
        with self.connection.cursor() as cursor:
            cursor.execute(query, args)
            insert_id = cursor.lastrowid
        self.connection.commit()
        return insert_id

    @logEntryExit
    def _check_and_get_configuration(self):
        query = "SELECT * FROM information_schema.tables WHERE table_schema = '%s' AND table_name = 'config' LIMIT 1" % self.database_config['db']
        cursor = self.connection.cursor()
        cursor.execute(query)
        if not cursor.fetchall():
            self._create_database()
            return CURRENT_DATABASE_CONFIG_VERSION
        else:
            config_version = self._query_get_single(
                "SELECT CAST(v as UNSIGNED) FROM config WHERE k = 'database_version'")
            # This is how we handle database upgrades
            if config_version != CURRENT_DATABASE_CONFIG_VERSION:
                self.logger.log("Going to try to process a database configuration upgrade from %s to %s" % (config_version, CURRENT_DATABASE_CONFIG_VERSION), level=LogLevel.Warning)
                try:
                    if config_version == 1 and CURRENT_DATABASE_CONFIG_VERSION == 2:
                        # From Database version 1 to 2 we added the outcome_types table, which I noticed was missing.
                        # Because I have a completed try run in the database I don't want to lose, I decided to take
                        # the opportunity to flesh out what a real database upgrade process would look like so we have
                        # sample code to use in the future.
                        for table_name in CREATION_QUERIES:
                            if table_name == 'outcome_types':
                                self._query_execute(CREATION_QUERIES[table_name])

                        for q in INSERTION_QUERIES:
                            if 'outcome_types' in q.query:
                                self._query_execute(q.query, q.args)

                    elif config_version == 2 and CURRENT_DATABASE_CONFIG_VERSION == 3:
                        # Add (all of) the constraints
                        for query_name in ALTER_QUERIES:
                            self._query_execute(ALTER_QUERIES[query_name])

                    elif config_version == 3 and CURRENT_DATABASE_CONFIG_VERSION == 4:
                        # Add killswitch
                        for q in INSERTION_QUERIES:
                            if 'config' in q.query and 'enabled' in q.query:
                                self._query_execute(q.query, q.args)

                    elif config_version == 4 and CURRENT_DATABASE_CONFIG_VERSION == 5:
                        # Remove libraries table
                        self._query_execute("DROP TABLE IF EXISTS libraries")

                    elif config_version == 5 and CURRENT_DATABASE_CONFIG_VERSION == 6:
                        # Create the try_runs table, and port the existing try runs across to it
                        for table_name in CREATION_QUERIES:
                            if table_name == 'try_runs':
                                self._query_execute(CREATION_QUERIES[table_name])

                        for query_name in ALTER_QUERIES:
                            if 'tryrun' in query_name:
                                self._query_execute(ALTER_QUERIES[query_name])

                        results = None
                        with self.connection.cursor() as cursor:
                            cursor.execute("SELECT * FROM jobs")
                            results = cursor.fetchall()
                        for r in results:
                            self._query_execute("INSERT INTO `try_runs` (`revision`, `job_id`, `purpose`) VALUES (%s, %s, %s)",
                                                (r['try_revision'], r['id'], 'ported from job table'))

                        self._query_execute("ALTER TABLE jobs DROP try_revision")

                    query = "UPDATE config SET v=%s WHERE k = 'database_version'"
                    args = (CURRENT_DATABASE_CONFIG_VERSION)
                    self._query_execute(query, args)
                    return CURRENT_DATABASE_CONFIG_VERSION
                except Exception as e:
                    self.logger.log("We don't handle exceptions raised during database upgrade elegantly. Your database is in an unknown state.", level=LogLevel.Fatal)
                    self.logger.log_exception(e)
                    raise e

                # If we've reached here, we didn't know how to process the database upgrade
                raise Exception(
                    "Do not know how to process a database configuration upgrade from %s to %s" % (config_version, CURRENT_DATABASE_CONFIG_VERSION))

            return config_version

    @logEntryExit
    def _create_database(self):
        try:
            for table_name in CREATION_QUERIES:
                self._query_execute(CREATION_QUERIES[table_name])
            for query_name in ALTER_QUERIES:
                self._query_execute(ALTER_QUERIES[query_name])
            for q in INSERTION_QUERIES:
                self._query_execute(q.query, q.args)
        except Exception as e:
            self.logger.log("We don't handle exceptions raised during database creation elegantly. Your database is in an unknown state.", level=LogLevel.Fatal)
            self.logger.log_exception(e)
            raise e

    @logEntryExit
    def updatebot_is_enabled(self):
        enabled = self._query_get_single(
            "SELECT CAST(v as UNSIGNED) FROM config WHERE k = 'enabled'")
        return enabled

    @logEntryExit
    def check_database(self):
        return self._check_and_get_configuration()

    @logEntryExit
    def delete_database(self):
        try:
            for constraint_key in ALTER_QUERIES:
                (constraint_table, constraint_name) = constraint_key.split("|")
                self._query_execute("ALTER TABLE " + constraint_table + " DROP FOREIGN KEY " + constraint_name)
            for table_name in CREATION_QUERIES:
                self._query_execute("DROP TABLE " + table_name)
        except Exception as e:
            self.logger.log("We don't handle exceptions raised during database deletion elegantly. Your database is in an unknown state.", level=LogLevel.Fatal)
            self.logger.log_exception(e)
            raise e

    def get_configuration(self):
        query = "SELECT * FROM config"
        results = self._query_get_rows(query)
        return [Struct(**r) for r in results]

    def get_all_statuses(self):
        query = "SELECT * FROM status_types ORDER BY id ASC"
        results = self._query_get_rows(query)
        return [Struct(**r) for r in results]

    def get_all_outcomes(self):
        query = "SELECT * FROM outcome_types ORDER BY id ASC"
        results = self._query_get_rows(query)
        return [Struct(**r) for r in results]

    @logEntryExit
    def get_all_jobs(self):
        query = """SELECT j.*, t.id as try_run_id, t.revision, j.id as job_id, t.purpose
                   FROM jobs as j
                   INNER JOIN try_runs as t
                       ON j.id = t.job_id
                   ORDER BY j.id ASC"""
        results = self._query_get_rows(query)
        return transform_job_and_try_results_into_objects(results)

    @logEntryExit
    def get_all_try_runs(self):
        query = "SELECT * FROM try_runs ORDER BY id ASC"
        results = self._query_get_rows(query)
        return [TryRun(r) for r in results]

    @logEntryExit
    def get_all_active_jobs_for_library(self, library):
        query = """SELECT j.*, t.id as try_run_id, t.revision, j.id as job_id, t.purpose
                   FROM jobs as j
                   INNER JOIN try_runs as t
                       ON j.id = t.job_id
                   WHERE j.library = %s
                     AND j.status<>%s
                   ORDER BY j.id ASC"""
        args = (library.origin["name"], JOBSTATUS.DONE)
        results = self._query_get_rows(query, args)
        return transform_job_and_try_results_into_objects(results)

    @logEntryExit
    def get_job(self, library, new_version):
        query = """SELECT j.*, t.id as try_run_id, t.revision, j.id as job_id, t.purpose
                   FROM jobs as j
                   INNER JOIN try_runs as t
                       ON j.id = t.job_id
                   WHERE j.library = %s
                     AND j.version = %s
                   ORDER BY j.id ASC"""
        args = (library.origin["name"], new_version)
        results = self._query_get_rows(query, args)
        jobs = transform_job_and_try_results_into_objects(results)
        return jobs[0] if jobs else None

    @logEntryExit
    def create_job(self, library, new_version, status, outcome, bug_id, phab_revision, try_run):
        query = "INSERT INTO jobs(library, version, status, outcome, bugzilla_id, phab_revision) VALUES(%s, %s, %s, %s, %s, %s)"
        args = (library.origin["name"], new_version, status, outcome, bug_id, phab_revision)
        job_id = self._query_execute(query, args)

        if try_run:
            query = "INSERT INTO try_runs(revision, job_id, purpose) VALUES(%s, %s, %s)"
            args = (try_run, job_id, 'initial platform')
            self._query_execute(query, args)

    @logEntryExit
    def update_job_status(self, existing_job):
        query = "UPDATE jobs SET status=%s, outcome=%s WHERE library = %s AND version = %s"
        args = (existing_job.status, existing_job.outcome, existing_job.library_shortname, existing_job.version)
        self._query_execute(query, args)

    @logEntryExit
    def add_try_run(self, existing_job, try_revision):
        query = "INSERT INTO try_runs(revision, job_id, purpose) VALUES(%s, %s, %s)"
        args = (try_revision, existing_job.id, 'more platforms')
        self._query_execute(query, args)

    @logEntryExit
    def delete_job(self, library=None, version=None, job_id=None):
        assert job_id or (library and version), "You must provide a way to delete a job"

        if job_id:
            query = "DELETE FROM try_runs WHERE job_id = %s"
            args = (job_id)
            self._query_execute(query, args)

            query = "DELETE FROM jobs WHERE id = %s"
            args = (job_id)
            self._query_execute(query, args)
        else:
            query = """DELETE t.*
                       FROM try_runs as t
                       INNER JOIN jobs as j
                          ON j.id = t.job_id
                       WHERE j.library = %s
                         AND j.version = %s"""
            args = (library.origin["name"], version)
            self._query_execute(query, args)

            query = "DELETE FROM jobs WHERE library = %s AND version = %s"
            args = (library.origin["name"], version)
            self._query_execute(query, args)
