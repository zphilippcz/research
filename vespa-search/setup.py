#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Setup script for Vespa Client Library
"""

from setuptools import setup, find_packages
import os

# Read the README file
def read_readme():
    with open("README.md", "r", encoding="utf-8") as fh:
        return fh.read()

# Read requirements
def read_requirements():
    with open("requirements.txt", "r", encoding="utf-8") as fh:
        return [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="vespa-client",
    version="1.0.0",
    author="Vespa Search Team",
    author_email="",
    description="Kompletní knihovna pro práci s Vespa search engine v Pythonu",
    long_description=read_readme(),
    long_description_content_type="text/markdown",
    url="",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Internet :: WWW/HTTP :: Indexing/Search",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    python_requires=">=3.7",
    install_requires=read_requirements(),
    extras_require={
        "dev": [
            "pytest>=6.0",
            "pytest-cov>=2.0",
            "black>=21.0",
            "flake8>=3.8",
            "mypy>=0.800",
        ],
        "examples": [
            "flask>=2.0",
            "sqlite3",
        ],
    },
    entry_points={
        "console_scripts": [
            "vespa-client=vespa_client:main",
        ],
    },
    include_package_data=True,
    zip_safe=False,
    keywords="vespa search engine client library",
    project_urls={
        "Bug Reports": "",
        "Source": "",
        "Documentation": "",
    },
)
