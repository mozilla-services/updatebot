#!/bin/bash

poetry run autopep8 --in-place --recursive --ignore E501,E402,E275 .
poetry run flake8 --ignore=E501,E402,E275 .
