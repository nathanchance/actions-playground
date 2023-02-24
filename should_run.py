#!/usr/bin/env python3

import json
import os
from pathlib import Path
import subprocess
import sys

import yaml

import utils

# An exit code of 1 means that the workflow should run, while an exit code
# of zero means that it should not. This is backwards from the traditional
# "0 for yes, 1 for no" but it makes it simpler to make the tuxsuite step
# depend on the failure of this step and it takes the conservative approach to
# internal errors within this script not causing workflows runs to be skipped.

if 'GITHUB_ACTIONS' not in os.environ:
    raise RuntimeError('Not running on GitHub Actions?')

if 'GITHUB_TOKEN' not in os.environ:
    raise RuntimeError('No GITHUB_TOKEN was specified?')

if os.environ['GITHUB_REPOSITORY_OWNER'] != 'nathanchance':
    raise RuntimeError('Not running in nathanchance repo, exiting...')

# Get name of calling workflow for branch name (without .yml)
# GITHUB_WORKFLOW_REF is <owner>/<repo>/.github/workflows/<workflow>.yml@refs/heads/<branch>
branch = Path(os.environ['GITHUB_WORKFLOW_REF'].split('@', 1)[0]).stem

# Configure git
actor = os.environ['GITHUB_ACTOR']
workspace = Path(os.environ['GITHUB_WORKSPACE'])
repo = Path(workspace, workspace.name)
git_configs = {
    'safe.directory': repo,
    'user.name': actor,
    'user.email': f"{actor}@users.noreply.github.com",
}
for key, val in git_configs.items():
    subprocess.run(['git', 'config', '--global', key, val], check=True)

# Clone repository
github_repo = os.environ['GITHUB_REPOSITORY']
subprocess.run(['git', 'clone', f"https://github.com/{github_repo}", repo],
               check=True)

# Down out of band to avoid leaking GITHUB_TOKEN, the push will fail later
# if this does not work, so check=False.
new_remote = f"https://{actor}:{os.environ['GITHUB_TOKEN']}@github.com/{github_repo}"
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
# pylint: disable-next=invalid-name
tree_name = '-'.join(branch.split('-')[0:-2])
with Path(workspace, 'generator.yml').open(encoding='utf-8') as file:
    config = yaml.safe_load(file)
url, ref = utils.get_repo_ref(config, tree_name)
ls_rem = subprocess.run(['git', 'ls-remote', url, ref],
                        capture_output=True,
                        check=True,
                        text=True)
sha = ls_rem.stdout.split('\t', 1)[0]

info_json = Path(repo, 'last_run_info.json')
new_run_info = {
    'compiler': compiler,
    'sha': sha,
}

if info_json.exists():
    with info_json.open('r+', encoding='utf-8') as file:
        old_run_info = json.load(file)
        for key in old_run_info:
            if old_run_info[key] != new_run_info[key]:
                json.dump(new_run_info, file)
                break
else:
    with info_json.open('w', encoding='utf-8') as file:
        json.dump(new_run_info, file)
subprocess.run(['git', 'add', info_json.name], check=True, cwd=repo)

status = subprocess.run(['git', 'status', '--porcelain', '-u'],
                        capture_output=True,
                        check=True,
                        cwd=repo,
                        text=True)
if not status.stdout:  # No changes, we do not need to run
    sys.exit(0)

subprocess.run(['git', 'commit', '-m', 'Update last_run_info.json'],
               check=True,
               cwd=repo)
subprocess.run(['git', 'push', 'origin', f"HEAD:{branch}"],
               check=True,
               cwd=repo)
sys.exit(1)
