#!/bin/bash
git stash --include-untracked
git pull --rebase
git stash pop stash@{0}
docker compose up -d --force-recreate --build
