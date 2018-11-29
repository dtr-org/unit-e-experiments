#!/usr/bin/env bash

# Copyright (c) 2018 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.

export PIPENV_VENV_IN_PROJECT=1

pip install pipenv
pipenv install --dev
