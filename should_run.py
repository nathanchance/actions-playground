#!/usr/bin/env python3

import os

if __name__ == '__main__':
    if 'GITHUB_ACTIONS' not in os.environ:
        raise RuntimeError('Not running on GitHub Actions?')
    for var in sorted(os.environ):
        print(f"{var}: {os.environ[var]}")
