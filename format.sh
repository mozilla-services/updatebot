#!/bin/bash

poetry run autopep8 .
poetry run flake8 .
