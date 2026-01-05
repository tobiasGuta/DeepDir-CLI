#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#
#  Author: Mauro Soria

from __future__ import annotations

import subprocess
import sys
import importlib.metadata
from pathlib import Path

from deepdir.core.exceptions import FailedDependenciesInstallation
from deepdir.core.settings import SCRIPT_PATH
from deepdir.utils.file import FileUtils

REQUIREMENTS_FILE = str(Path(SCRIPT_PATH) / "requirements.txt")


def get_dependencies() -> list[str]:
    try:
        return FileUtils.get_lines(REQUIREMENTS_FILE)
    except FileNotFoundError:
        # If requirements.txt is missing, assume we are running as an installed package
        # and dependencies are already satisfied.
        return []


# Check if all dependencies are satisfied
def check_dependencies() -> None:
    for requirement in get_dependencies():
        # Simple parsing of requirement string (e.g., "requests>=2.27.0")
        # Handle comments and empty lines
        requirement = requirement.strip()
        if not requirement or requirement.startswith("#"):
            continue
            
        package_name = requirement.split(">=")[0].split("==")[0].split("<")[0].strip()
        
        # Handle special cases where package name differs from import name
        # e.g. beautifulsoup4 -> bs4, PySocks -> socks
        import_name = package_name
        if package_name.lower() == "beautifulsoup4":
            import_name = "bs4"
        elif package_name.lower() == "pysocks":
            import_name = "socks"
        elif package_name.lower() == "mysql-connector-python":
            import_name = "mysql.connector"
        elif package_name.lower() == "fake-useragent":
            import_name = "fake_useragent"
            
        try:
            importlib.metadata.version(package_name)
        except importlib.metadata.PackageNotFoundError:
            # If package is not found, try to import it
            try:
                __import__(import_name)
            except ImportError:
                # If both fail, raise exception to trigger installation
                raise Exception(f"Dependency missing: {package_name}") from None


def install_dependencies() -> None:
    try:
        subprocess.check_output(
            [sys.executable, "-m", "pip", "install", "-r", REQUIREMENTS_FILE],
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError:
        raise FailedDependenciesInstallation
