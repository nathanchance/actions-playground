#!/usr/bin/env python3

import json
import os
from pathlib import Path
import subprocess
import sys

import yaml

import utils

if 'GITHUB_ACTIONS' not in os.environ:
    raise RuntimeError('Not running on GitHub Actions?')

if 'GITHUB_TOKEN' not in os.environ:
    raise RuntimeError('No GITHUB_TOKEN was specified?')

if os.environ['GITHUB_REPOSITORY_OWNER'] != 'nathanchance':
    raise RuntimeError('Not running in nathanchance repo, exiting...')

github = {
    'actor': os.environ['GITHUB_ACTOR'],
    'token': os.environ['GITHUB_TOKEN'],
    'repository': os.environ['GITHUB_REPOSITORY'],
    'workflow_ref': os.environ['GITHUB_WORKFLOW_REF'],
    'workspace': Path(os.environ['GITHUB_WORKSPACE']),
}

# Get name of calling workflow for branch name (without .yml)
# GITHUB_WORKFLOW_REF is <owner>/<repo>/.github/workflows/<workflow>.yml@refs/heads/<branch>
branch = Path(github['workflow_ref'].split('@', 1)[0]).stem

# Configure git
repo = Path(github['workspace'], github['workspace'].name)
git_configs = {
    'safe.directory': repo,
    'user.name': f"{github['actor']} via GitHub Actions",
    'user.email': f"{github['actor']}@users.noreply.github.com",
}
for key, val in git_configs.items():
    subprocess.run(['git', 'config', '--global', key, val], check=True)

# Clone repository
subprocess.run(
    ['git', 'clone', f"https://github.com/{github['repository']}", repo],
    check=True)

# Down out of band to avoid leaking GITHUB_TOKEN, the push will fail later
# if this does not work, so check=False.
new_remote = f"https://{github['actor']}:{github['token']}@github.com/{github['repository']}"
subprocess.run(['git', 'remote', 'set-url', 'origin', new_remote],
               check=False,
               cwd=repo)

# If there is no branch in the repository for the current workflow, create one
try:
    subprocess.run(['git', 'checkout', branch], check=True, cwd=repo)
except subprocess.CalledProcessError:
    subprocess.run(['git', 'checkout', '--orphan', branch],
                   check=True,
                   cwd=repo)
    subprocess.run(['git', 'rm', '-fr', '.'], check=True, cwd=repo)

# Get compiler string
compiler = subprocess.run(['clang', '--version'],
                          capture_output=True,
                          check=True,
                          text=True).stdout.splitlines()[0]

# Get current sha of remote
# Input: <tree>-clang-<num>
# Output: <tree>
# Have to split then join because tree could have a hyphen
# pylint: disable-next=invalid-name ??
tree_name = '-'.join(branch.split('-')[0:-2])
with Path(github['workspace'], 'generator.yml').open(encoding='utf-8') as file:
    config = yaml.safe_load(file)
url, ref = utils.get_repo_ref(config, tree_name)
ls_rem = subprocess.run(['git', 'ls-remote', url, ref],
                        capture_output=True,
                        check=True,
                        text=True)
# Input: <sha>\tref/heads/<ref>
# Output: <sha>
sha = ls_rem.stdout.split('\t', 1)[0]

info_json = Path(repo, 'last_run_info.json')
new_run_info = {
    'compiler': compiler,
    'sha': sha,
}

# If the file already exists...
if info_json.exists():
    with info_json.open(encoding='utf-8') as file:
        old_run_info = json.load(file)
    # compare the two, writing to disk and breaking as soon as there is a
    # difference
    for key in old_run_info:
        if old_run_info[key] != new_run_info[key]:
            with info_json.open('w', encoding='utf-8') as file:
                json.dump(new_run_info, file, indent=4, sort_keys=True)
            break
else:
    # Otherwise, create and write to the file
    with info_json.open('w', encoding='utf-8') as file:
        json.dump(new_run_info, file, indent=4, sort_keys=True)

subprocess.run(['git', 'add', info_json.name], check=True, cwd=repo)
status = subprocess.run(['git', 'status', '--porcelain', '-u'],
                        capture_output=True,
                        check=True,
                        cwd=repo,
                        text=True)
if not status.stdout:  # No changes, we do not need to run
    sys.exit(2)

subprocess.run(['git', 'commit', '-m', f"{branch}: Update last_run_info.json"],
               check=True,
               cwd=repo)
subprocess.run(['git', 'push', 'origin', f"HEAD:{branch}"],
               check=True,
               cwd=repo)
