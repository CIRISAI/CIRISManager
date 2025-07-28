#!/usr/bin/env python3
"""
Setup script for CIRISManager.
This is a lightweight installation that only installs the manager component.
"""

from setuptools import setup, find_packages

# Most configuration is in pyproject.toml
# This file exists for compatibility with older pip versions

setup(
    packages=find_packages(include=["ciris_manager", "ciris_manager.*"]),
)