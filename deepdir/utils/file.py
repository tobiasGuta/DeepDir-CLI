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

import os
from pathlib import Path
from typing import Union, List


class File:
    def __init__(self, *path_components):
        self._path = FileUtils.build_path(*path_components)

    @property
    def path(self):
        return self._path

    @path.setter
    def path(self, value):
        raise NotImplementedError

    def is_valid(self):
        return FileUtils.is_file(self.path)

    def exists(self):
        return FileUtils.exists(self.path)

    def can_read(self):
        return FileUtils.can_read(self.path)

    def can_write(self):
        return FileUtils.can_write(self.path)

    def read(self):
        return FileUtils.read(self.path)

    def get_lines(self):
        return FileUtils.get_lines(self.path)

    def __enter__(self):
        return self

    def __exit__(self, type, value, tb):
        pass


class FileUtils:
    @staticmethod
    def build_path(*path_components: str) -> str:
        if path_components:
            return str(Path(*path_components))
        return ""

    @staticmethod
    def get_abs_path(file_name: str) -> str:
        return str(Path(file_name).resolve())

    @staticmethod
    def exists(file_name: str) -> bool:
        return Path(file_name).exists()

    @staticmethod
    def is_empty(file_name: str) -> bool:
        return Path(file_name).stat().st_size == 0

    @staticmethod
    def can_read(file_name: str) -> bool:
        try:
            with open(file_name):
                pass
        except OSError:
            return False
        return True

    @classmethod
    def can_write(cls, path: str) -> bool:
        p = Path(path)
        while not p.exists():
            p = p.parent
            if str(p) == str(p.parent): # Root
                break
        return os.access(str(p), os.W_OK)

    @staticmethod
    def read(file_name: str) -> str:
        return Path(file_name).read_text(encoding="utf-8", errors="replace")

    @classmethod
    def get_files(cls, directory: str) -> List[str]:
        files = []
        p = Path(directory)
        if not p.exists():
            return []
            
        for item in p.rglob("*"):
            if item.is_file():
                files.append(str(item))
        return files

    @staticmethod
    def get_lines(file_name: str) -> List[str]:
        with open(file_name, "r", errors="replace") as fd:
            return fd.read().splitlines()

    @staticmethod
    def is_dir(path: str) -> bool:
        return Path(path).is_dir()

    @staticmethod
    def is_file(path: str) -> bool:
        return Path(path).is_file()

    @staticmethod
    def parent(path: str, depth: int = 1) -> str:
        p = Path(path)
        for _ in range(depth):
            p = p.parent
        return str(p)

    @classmethod
    def create_dir(cls, directory: str) -> None:
        Path(directory).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def write_lines(file_name: str, lines: Union[List[str], str], overwrite: bool = False) -> None:
        mode = "w" if overwrite else "a"
        if isinstance(lines, list):
            lines = os.linesep.join(lines)
        
        with open(file_name, mode) as f:
            f.writelines(lines)
