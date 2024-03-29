#!/usr/bin/env bash

# Copyright (c) 2018 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.

export TRAVIS_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
export PIPENV_VENV_IN_PROJECT=1
export PIPENV_IGNORE_VIRTUALENVS=1  # Use own virtualenv instead of Travis' one

pip install pipenv
pipenv install --dev
pipenv check  # Checking potential dependency problems (PEP 508 requirements)

git clone git@github.com:dtr-org/unit-e.git "${TRAVIS_DIR}/unit-e"
