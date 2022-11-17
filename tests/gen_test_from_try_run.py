#!/usr/bin/env python3

import os
import sys
import requests
import argparse

sys.path.append(".")
sys.path.append("..")
from components.logging import LoggingProvider
from apis.taskcluster import TaskclusterProvider
from tests.mock_commandprovider import TestCommandProvider


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("try_run", help="The try run to generate a test for")
    parser.add_argument("shortname", help="A shortname to identify the tryrun")

    args = parser.parse_args()

    # ---------------------
    # Setup

    api = TaskclusterProvider({})

    tcp = TestCommandProvider({})
    lp = LoggingProvider({})
    config = {"CommandProvider": tcp, "LoggingProvider": lp}
    api.update_config(config)

    HEADERS = {"User-Agent": "Updatebot"}

    root_path = "tests" if "tests" not in os.getcwd() else ""

    # ---------------------
    # Jobs

    push_list_url = api._get_push_list_url(args.try_run)
    print("Requesting", push_list_url)
    r = requests.get(push_list_url, headers=HEADERS)

    try:
        push_list = r.json()
    except Exception:
        raise Exception(
            "Could not parse the result of the push_list as json. Url: %s Response:\n%s"
            % (push_list_url, r.text)
        )

    try:
        push_id = push_list["results"][0]["id"]
    except Exception as e:
        raise Exception(
            "Could not find the expected ['results'][0]['id'] from %s" % r.text
        ) from e

    indx = 1
    job_details_url = api._get_job_details_url(push_id)
    try:
        while job_details_url:
            print("Requesting", job_details_url)
            r = requests.get(job_details_url, headers=HEADERS)
            try:
                j = r.json()
            except Exception:
                raise Exception("Could not parse the result of the jobs list as json. Url: %s" % (job_details_url))

            with open(
                os.path.join(root_path, "treeherder_api_responses", "jobs_%s_%s.txt" % (args.shortname, indx)), "w"
            ) as jobs_file:
                jobs_file.write(r.text)
                print("Wrote", jobs_file.name)

            indx += 1
            job_details_url = j['next'] if 'next' in j else None
    except Exception as e:
        raise Exception("Could not obtain all the job results for push id %s" % push_id) from e

    # ---------------------
    # Push Health

    push_health_url = api._get_push_health_url(args.try_run)
    print("Requesting", push_health_url)
    r = requests.get(push_health_url, headers=HEADERS)

    with open(
        os.path.join(root_path, "treeherder_api_responses", "health_" + args.shortname + ".txt"),
        "w",
    ) as health_file:
        health_file.write(r.text)
        print("Wrote", health_file.name)
