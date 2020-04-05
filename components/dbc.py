#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from components.db import MySQLDatabase


class Database:
    def __init__(self, database_config):
        self.db = MySQLDatabase(database_config)

    def check_database(self):
        return self.db.check_database()

    def delete_database(self):
        return self.db.delete_database()

    def get_libraries(self):
        return self.db.get_libraries()

    def get_all_statuses(self):
        return self.db.get_all_statuses()

    def get_all_jobs(self):
        return self.db.get_all_jobs()

    def get_job(self, library, new_version):
        return self.db.get_job(library, new_version)

    # Only used for testing purposes, in the real database, we don't delete records.
    def delete_job(self, library, new_version):
        return self.db.delete_job(library, new_version)

    def save_job(self, library, new_version, bug_id, try_run):
        return self.db.save_job(library, new_version, bug_id, try_run)

    def print(self):
        def get_column_widths(objects, columns):
            widths = []

            for c in columns:
                thiswidth = len(c) + 2
                for o in objects:
                    thislen = len(str(getattr(o, c))) + 2
                    if thislen > thiswidth:
                        thiswidth = thislen
                widths.append(thiswidth)
            return widths

        def print_line(widths):
            print("+", sep='', end='')
            for w in widths:
                print("-" * w, "+", sep='', end='')
            print("")

        def print_values(values, widths):
            assert(len(values) == len(widths))

            print("|", end=' ')
            for i in range(len(values)):
                print(str(values[i]).ljust(widths[i] - 2), "|", end=' ')
            print("")

        def print_object_values(obj, columns, widths):
            print_values([getattr(obj, c) for c in columns], widths)

        def print_objects(name, objects, columns):
            widths = get_column_widths(objects, columns)
            print("")
            print("")
            print(name)
            print_line(widths)
            print_values(columns, widths)
            print_line(widths)
            for o in objects:
                print_object_values(o, columns, widths)
                print_line(widths)

        status_columns = ['id', 'name']
        print_objects("STATUSES", self.get_all_statuses(), status_columns)

        job_columns = ['id', 'library_shortname', 'version',
                       'status', 'bugzilla_id', 'try_revision']
        print_objects("JOBS", self.get_all_jobs(), job_columns)

        library_columns = ['id', 'shortname', 'bugzilla_product',
                           'bugzilla_component', 'fuzzy_query']
        print_objects("LIBRARIES", self.get_libraries(), library_columns)
