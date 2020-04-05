#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from components.utilities import Struct, logEntryExit
from components.dbmodels import Job, Library, JOBSTATUS

import pymysql

LIBRARIES = [
    Struct(**{
        'shortname': 'dav1d',
        'bugzilla_product': 'Core',
        'bugzilla_component': 'ImageLib',
        'fuzzy_query': "'build-linux64/debug"
        # 'fuzzy_query' : "'test 'gtest | 'media !'asan"
    })
]

# ==================================================================================


class HardcodedDatabase:
    def __init__(self, database_config):
        self.libraries = LIBRARIES

    def check_database(self):
        return 1

    def get_libraries(self):
        return self.libraries

    def have_job(self, library, new_version):
        return False

    def save_job(self, library, new_version, bug_id, try_run):
        pass

# ==================================================================================


CREATION_QUERIES = {
    "config": """
      CREATE TABLE `config` (
        `k` varchar(255) NOT NULL,
        `v` varchar(255) NOT NULL
      )
      ENGINE = InnoDB DEFAULT CHARSET = utf8
      """,
    "status_types": """
      CREATE TABLE `status_types` (
        `id` TINYINT NOT NULL,
        `name` VARCHAR(255) NOT NULL
      ) ENGINE = InnoDB;
      """,
    "jobs": """
      CREATE TABLE `jobs` (
        `id` INT NOT NULL AUTO_INCREMENT,
        `library` VARCHAR(255) NOT NULL,
        `version` VARCHAR(64) NOT NULL ,
        `status` TINYINT NOT NULL,
        `bugzilla_id` INT NULL,
        `try_revision` VARCHAR(40) NULL,
        PRIMARY KEY (`id`)
      ) ENGINE = InnoDB;
      """,
    "libraries": """
      CREATE TABLE `libraries` (
        `id` INT NOT NULL AUTO_INCREMENT,
        `shortname` VARCHAR(255) NOT NULL,
        `bugzilla_product` VARCHAR(255) NOT NULL ,
        `bugzilla_component` VARCHAR(255) NOT NULL,
        `fuzzy_query` VARCHAR(255) NULL,
        PRIMARY KEY (`id`)
      ) ENGINE = InnoDB;
      """
}

CURRENT_DATABASE_CONFIG_VERSION = 1

INSERTION_QUERIES = [
    Struct(**{
        'query': "INSERT INTO `config` (`k`, `v`) VALUES ('database_version', %s)",
        'args': (CURRENT_DATABASE_CONFIG_VERSION)
    })
]

for l in LIBRARIES:
    INSERTION_QUERIES.append(
        Struct(**{
            'query': "INSERT INTO `libraries` (`shortname`, `bugzilla_product`, `bugzilla_component`, `fuzzy_query`) VALUES (%s, %s, %s, %s)",
            'args': (l.shortname, l.bugzilla_product, l.bugzilla_component, l.fuzzy_query)
        }))

# ==================================================================================


class MySQLDatabase:
    @logEntryExit
    def __init__(self, database_config):
        self.connection = pymysql.connect(
            host=database_config['host'],
            user=database_config['user'],
            password=database_config['password'],
            db=database_config['db'],
            charset='utf8',
            cursorclass=pymysql.cursors.DictCursor)

        self.libraries = None

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
        with self.connection.cursor() as cursor:
            cursor.execute(query, args)
        self.connection.commit()

    @logEntryExit
    def _check_and_get_configuration(self):
        query = "SELECT * FROM information_schema.tables WHERE table_schema = 'updatebot' AND table_name = 'config' LIMIT 1"
        cursor = self.connection.cursor()
        cursor.execute(query)
        if not cursor.fetchall():
            self._create_database()
            return CURRENT_DATABASE_CONFIG_VERSION
        else:
            config_version = self._query_get_single(
                "SELECT CAST(v as UNSIGNED) FROM config WHERE k = 'database_version'")
            # In the future, we will put commands in here to handle database updates
            if config_version != CURRENT_DATABASE_CONFIG_VERSION:
                raise Exception(
                    "Do not known how to process a database with a config version of " + str(config_version))
            return config_version

    @logEntryExit
    def _create_database(self):
        try:
            for table_name in CREATION_QUERIES:
                self._query_execute(CREATION_QUERIES[table_name])
            for q in INSERTION_QUERIES:
                self._query_execute(q.query, q.args)
        except Exception as e:
            print(e)
            print("We don't handle exceptions raised during database creation elegantly. Your database is in an unknown state.")
            raise e

    @logEntryExit
    def check_database(self):
        return self._check_and_get_configuration()

    @logEntryExit
    def delete_database(self):
        try:
            for table_name in CREATION_QUERIES:
                self._query_execute("DROP TABLE " + table_name)
        except Exception as e:
            print("We don't handle exceptions raised during database deletion elegantly. Your database is in an unknown state.")
            raise e

    def get_libraries(self):
        if not self.libraries:
            query = "SELECT * FROM libraries"
            results = self._query_get_rows(query)
            self.libraries = [Library(r) for r in results]

        return self.libraries

    @logEntryExit
    def get_all_jobs(self):
        query = "SELECT * FROM jobs ORDER BY id ASC"
        results = self._query_get_rows(query)
        return [Job(r) for r in results]

    @logEntryExit
    def get_job(self, library, new_version):
        query = "SELECT * FROM jobs WHERE library = %s AND version = %s"
        args = (library.shortname, new_version)
        results = self._query_get_row_maybe(query, args)
        return Job(results) if results else None

    @logEntryExit
    def save_job(self, library, new_version, bug_id, try_run):
        query = "INSERT INTO jobs(library, version, status, bugzilla_id, try_revision) VALUES(%s, %s, %s, %s, %s)"
        args = (library.shortname, new_version,
                JOBSTATUS.SUBMITTED_TRY, bug_id, try_run)
        self._query_execute(query, args)

    def delete_job(self, library, new_version):
        query = "DELETE FROM jobs WHERE library = %s AND version = %s"
        args = (library.shortname, new_version)
        self._query_execute(query, args)
