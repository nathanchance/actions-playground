#!/usr/bin/env python3

import os

if __name__ == '__main__':
    if 'GITHUB_ACTIONS' not in os.environ:
        raise RuntimeError('Not running on GitHub Actions?')
    print(f"GITHUB_WORKFLOW_REF: {os.environ['GITHUB_WORKFLOW_REF']}")
