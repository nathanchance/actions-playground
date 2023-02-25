#!/usr/bin/env python3

import argparse
import contextlib
import hashlib
from pathlib import Path
import sys
import yaml

from utils import get_config_from_generator, get_llvm_versions, get_repo_ref, patch_series_flag, print_red


def parse_args(trees):
    parser = argparse.ArgumentParser(
        description="Generate GitHub Action Workflow YAML.")
    parser.add_argument("tree",
                        help="The git repo and ref to filter in.",
                        choices=[tree["name"] for tree in trees])
    return parser.parse_args()


def initial_workflow(name, cron, tuxsuite_yml, workflow_yml):
    return {
        "name": name,
        "on": {
            # https://docs.github.com/en/actions/reference/workflow-syntax-for-github-actions#onpushpull_requestpaths
            "push": {
                "branches": [
                    # Allow testing on branches with a presubmit/ prefix
                    "presubmit/*",
                ],
                "paths": [
                    "check_logs.py",
                    "utils.py",
                    tuxsuite_yml,
                    workflow_yml,
                ],
            },
            # https://docs.github.com/en/free-pro-team@latest/actions/reference/events-that-trigger-workflows#scheduled-events
            "schedule": [
                {"cron": cron},
            ],
            # https://docs.github.com/en/free-pro-team@latest/actions/reference/events-that-trigger-workflows#workflow_dispatch
            "workflow_dispatch": None,
        },
        "permissions": "read-all",
        "jobs": {},
    }  # yapf: disable


def print_config(build):
    config = build["config"]
    if isinstance(config, list):
        config_name = config[0]
        i = 1
        while i < len(config):
            config_name += "+" + config[i]
            i += 1
    else:
        config_name = config
    return config_name


def get_job_name(build):
    job = "ARCH=" + (build["ARCH"] if "ARCH" in build else "x86_64")
    # BOOT=1 is the default, only show if we have disabled it
    if not build["boot"]:
        job += " BOOT=0"
    # LLVM=0 does not make much sense. Translate LLVM=0 into CC=clang
    if build["llvm"]:
        job += " LLVM=1"
    else:
        job += " CC=clang"
    # If LD was specified, show what it is
    if "make_variables" in build and "LD" in build["make_variables"]:
        job += " LD=" + str(build["make_variables"]["LD"])
    job += " LLVM_IAS=" + str(build["make_variables"]["LLVM_IAS"])
    # Having "LLVM <VER>" is a little hard to parse, make it look like
    # an environment variable
    job += " LLVM_VERSION=" + str(build["llvm_version"])
    job += " " + print_config(build)
    return job


def sanitize_job_name(name):
    return "_" + hashlib.new("md5", name.encode("utf-8")).hexdigest()


def tuxsuite_setups(job_name, tuxsuite_yml, repo, ref):
    tuxsuite_yml_name = Path(tuxsuite_yml).name
    # Input: '<tree>-clang-<num>.tux.yml'
    # Output: [<tree_parts>, 'clang', <num>]
    workflow_parts = tuxsuite_yml_name.replace('.tux.yml', '').split('-')

    tree = '-'.join(workflow_parts[0:-2])
    patch_series = patch_series_flag(tree)

    ci_folder = Path(__file__).resolve().parent
    with Path(ci_folder, 'LLVM_TOT_VERSION').open(encoding='utf-8') as file:
        max_version = int(file.read())
    llvm_version = workflow_parts[-1]
    with contextlib.suppress(ValueError):
        if int(llvm_version) == max_version:
            llvm_version = 'nightly'
    return {
        f"cache_check_{job_name}": {
            "name": f"cache check ({job_name})",
            "runs-on": "ubuntu-latest",
            "container": f"tuxmake/clang-{llvm_version}",
            "outputs": {
                "should_run": "${{ steps.should_run.outputs.should_run }}",
            },
            "permissions": "write-all",
            "steps": [
                {
                    "uses": "actions/checkout@v3",
                },
                {
                    "name": "Should build run?",
                    "id": "should_run",
                    "run": ('if python3 should_run.py || { ret=$?; ( exit $ret ) }; then\n'
                            '  echo "should_run=true" >>$GITHUB_OUTPUT\n'
                            'else\n'
                            '    case $ret in\n'
                            '      2) echo "should_run=false" >>$GITHUB_OUTPUT ;;\n'
                            '      *) exit 1 ;;\n'
                            '    esac\n'
                            'fi\n'),
                    "env": {"GITHUB_TOKEN": '${{ secrets.GITHUB_TOKEN }}'},
                },
            ],
        },
        f"kick_tuxsuite_{job_name}": {
            "name": f"TuxSuite ({job_name})",
            "needs": f"cache_check_{job_name}",
            "if": f"${{{{ needs.cache_check_{job_name}.outputs.should_run == 'true' }}}}",
            # https://docs.github.com/en/free-pro-team@latest/actions/reference/workflow-syntax-for-github-actions#jobsjob_idruns-on
            "runs-on": "ubuntu-latest",
            "container": "tuxsuite/tuxsuite",
            "timeout-minutes": 480,
            "steps": [
                {
                    "uses": "actions/checkout@v3",
                },
                {
                    "name": "tuxsuite",
                    "run": f"echo tuxsuite plan --git-repo {repo} --git-ref {ref} --job-name {job_name} --json-out builds.json {patch_series}{tuxsuite_yml}",
                },
                {
                    "name": "save output",
                    "run": "echo save output",
                },
            ],
        },
    }  # yapf: disable


def get_steps(build, build_set):
    name = get_job_name(build)
    return {
        sanitize_job_name(name): {
            "runs-on": "ubuntu-latest",
            "needs": f"kick_tuxsuite_{build_set}",
            "name": name,
            "env": {
                "ARCH": build["ARCH"] if "ARCH" in build else "x86_64",
                "LLVM_VERSION": build["llvm_version"],
                "BOOT": int(build["boot"]),
                "CONFIG": print_config(build),
            },
            "container": {
                "image": "ghcr.io/clangbuiltlinux/qemu",
                "options": "--ipc=host",
            },
            "steps": [
                {
                    "uses": "actions/checkout@v3",
                    "with": {
                        "submodules": True,
                    },
                },
                {
                    "name": "Check Build and Boot Logs",
                    "run": "echo ./check_logs.py",
                },
            ],
        },
    }  # yapf: disable


def get_cron_schedule(schedules, tree_name, llvm_version):
    for item in schedules:
        if item["name"] == tree_name and \
           item["llvm_version"] == llvm_version:
            return item["schedule"]
    print_red(f"Could not find schedule for {tree_name} clang-{llvm_version}?")
    sys.exit(1)


def print_builds(config, tree_name, llvm_version):
    repo, ref = get_repo_ref(config, tree_name)
    toolchain = f"clang-{llvm_version}"
    tuxsuite_yml = f"tuxsuite/{tree_name}-{toolchain}.tux.yml"
    github_yml = f".github/workflows/{tree_name}-{toolchain}.yml"

    check_logs_defconfigs = {}
    check_logs_distribution_configs = {}
    check_logs_allconfigs = {}
    for build in config["builds"]:
        if build["git_repo"] == repo and \
           build["git_ref"] == ref and \
           build["llvm_version"] == llvm_version:
            cfg_str = str(build["config"])
            if "defconfig" in cfg_str or "chromeos" in cfg_str:
                check_logs_defconfigs.update(get_steps(build, "defconfigs"))
            elif "https://" in cfg_str:
                check_logs_distribution_configs.update(
                    get_steps(build, "distribution_configs"))
            else:
                check_logs_allconfigs.update(get_steps(build, "allconfigs"))

    workflow_name = f"{tree_name} ({toolchain})"
    cron_schedule = get_cron_schedule(config["tree_schedules"], tree_name,
                                      llvm_version)
    workflow = initial_workflow(workflow_name, cron_schedule, tuxsuite_yml,
                                github_yml)
    workflow["jobs"].update(
        tuxsuite_setups("defconfigs", tuxsuite_yml, repo, ref))
    workflow["jobs"].update(check_logs_defconfigs)

    if check_logs_distribution_configs:
        workflow["jobs"].update(
            tuxsuite_setups("distribution_configs", tuxsuite_yml, repo, ref))
        workflow["jobs"].update(check_logs_distribution_configs)

    if check_logs_allconfigs:
        workflow["jobs"].update(
            tuxsuite_setups("allconfigs", tuxsuite_yml, repo, ref))
        workflow["jobs"].update(check_logs_allconfigs)

    with open(github_yml, "w", encoding='utf-8') as file:
        orig_stdout = sys.stdout
        sys.stdout = file
        print("# DO NOT MODIFY MANUALLY!")
        print("# This file has been autogenerated by invoking:")
        print(f"# $ ./generate_workflow.py {tree_name}")
        print(
            yaml.dump(workflow,
                      Dumper=yaml.Dumper,
                      width=1000,
                      sort_keys=False))
        sys.stdout = orig_stdout


# https://github.com/yaml/pyyaml/issues/240
def str_presenter(dumper, data):
    """configures yaml for dumping multiline strings
    Ref: https://stackoverflow.com/questions/8640959/how-can-i-control-what-scalar-form-pyyaml-uses-for-my-data"""
    if data.count('\n') > 0:  # check for multiline string
        return dumper.represent_scalar('tag:yaml.org,2002:str',
                                       data,
                                       style='|')
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)


yaml.add_representer(str, str_presenter)

if __name__ == "__main__":
    generated_config = get_config_from_generator()
    print_builds(generated_config, 'mainline', 17)