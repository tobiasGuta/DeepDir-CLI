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

import re
from typing import Any, Iterator, Generator
from pathlib import Path

from deepdir.core.data import options
from deepdir.core.decorators import locked
from deepdir.core.settings import (
    SCRIPT_PATH,
    EXTENSION_TAG,
    EXCLUDE_OVERWRITE_EXTENSIONS,
    EXTENSION_RECOGNITION_REGEX,
)
from deepdir.parse.url import clean_path
from deepdir.utils.common import lstrip_once
from deepdir.utils.file import FileUtils


# Get ignore paths for status codes.
# Reference: https://github.com/maurosoria/DeepDir#Blacklist
def get_blacklists() -> dict[int, Dictionary]:
    blacklists = {}

    for status in [400, 403, 500]:
        blacklist_file_name = FileUtils.build_path(SCRIPT_PATH, "db")
        blacklist_file_name = FileUtils.build_path(
            blacklist_file_name, f"{status}_blacklist.txt"
        )

        if not FileUtils.can_read(blacklist_file_name):
            # Skip if cannot read file
            continue

        blacklists[status] = Dictionary(
            files=[blacklist_file_name],
            is_blacklist=True,
        )

    return blacklists


class Dictionary:
    def __init__(self, files: list[str] = [], is_blacklist: bool = False) -> None:
        self._files = files
        self._is_blacklist = is_blacklist
        self._generator = self.generate()
        self._extra = []
        self._extra_index = 0
        self._re_ext_tag = re.compile(EXTENSION_TAG, re.IGNORECASE)
        self._count = 0
        
        # Pre-calculate length if possible (approximate)
        if not is_blacklist:
            for file in files:
                try:
                    with open(file, 'r', encoding='utf-8', errors='ignore') as f:
                        for _ in f:
                            self._count += 1
                except Exception:
                    pass

    @property
    def index(self) -> int:
        # This is an approximation for progress bars since we're streaming
        return 0 

    @locked
    def __next__(self) -> str:
        if len(self._extra) > self._extra_index:
            self._extra_index += 1
            return self._extra[self._extra_index - 1]
        
        return next(self._generator)

    def __iter__(self) -> Iterator[str]:
        return self

    def __len__(self) -> int:
        return self._count

    def process_line(self, line: str) -> Generator[str, None, None]:
        # Removing leading "/" to work with prefixes later
        line = lstrip_once(line.strip(), "/")

        if not self.is_valid(line):
            return

        # Classic DeepDir wordlist processing (with %EXT% keyword)
        if EXTENSION_TAG in line.lower():
            for extension in options.extensions:
                yield self._re_ext_tag.sub(extension, line)
        else:
            yield line

            # "Forcing extensions" and "overwriting extensions" shouldn't apply to
            # blacklists otherwise it might cause false negatives
            if self._is_blacklist:
                return

            # If "forced extensions" is used and the path is not a directory (terminated by /)
            # or has had an extension already, append extensions to the path
            if (
                options.force_extensions
                and "." not in line
                and not line.endswith("/")
            ):
                yield line + "/"

                for extension in options.extensions:
                    yield f"{line}.{extension}"
            # Overwrite unknown extensions with selected ones (but also keep the origin)
            elif (
                options.overwrite_extensions
                and not line.endswith(options.extensions + EXCLUDE_OVERWRITE_EXTENSIONS)
                # Paths that have queries in wordlist are usually used for exploiting
                # disclosed vulnerabilities of services, skip such paths
                and "?" not in line
                and "#" not in line
                and re.search(EXTENSION_RECOGNITION_REGEX, line)
            ):
                base = line.split(".")[0]

                for extension in options.extensions:
                    yield f"{base}.{extension}"

    def apply_transformations(self, path: str) -> Generator[str, None, None]:
        if self._is_blacklist:
            yield path
            return

        # Prefixes
        if options.prefixes:
            for pref in options.prefixes:
                if not path.startswith(("/", pref)):
                    yield pref + path
        
        # Suffixes
        if options.suffixes:
            for suff in options.suffixes:
                if (
                    not path.endswith(("/", suff))
                    and "?" not in path
                    and "#" not in path
                ):
                    yield path + suff
        
        # Original path (if no prefixes/suffixes or in addition to them depending on logic)
        # The original logic replaced the list with altered_wordlist if it existed.
        # Here we yield the transformed versions. If prefixes/suffixes are set, 
        # the original logic implies ONLY transformed versions are yielded if altered_wordlist is not empty.
        # However, usually users want both or just the transformed. 
        # Following original logic: if prefixes/suffixes exist, we yield those.
        # If not, we yield the path itself.
        
        has_transformations = False
        if options.prefixes:
             for pref in options.prefixes:
                if not path.startswith(("/", pref)):
                    has_transformations = True
        
        if options.suffixes:
             for suff in options.suffixes:
                if (
                    not path.endswith(("/", suff))
                    and "?" not in path
                    and "#" not in path
                ):
                    has_transformations = True

        if not has_transformations:
            yield path

    def apply_case(self, path: str) -> str:
        if options.lowercase:
            return path.lower()
        elif options.uppercase:
            return path.upper()
        elif options.capitalization:
            return path.capitalize()
        return path

    def generate(self) -> Generator[str, None, None]:
        seen = set()
        
        for dict_file in self._files:
            try:
                with open(dict_file, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        for processed in self.process_line(line):
                            for transformed in self.apply_transformations(processed):
                                final = self.apply_case(transformed)
                                if final not in seen:
                                    seen.add(final)
                                    yield final
                                    
                                    # Keep memory usage low by clearing seen set periodically if it gets too huge
                                    # ideally we want to dedup, but for massive lists we might accept some dupes
                                    # to save RAM. For now, let's keep it simple.
            except OSError:
                continue

    def is_valid(self, path: str) -> bool:
        # Skip comments and empty lines
        if not path or path.startswith("#"):
            return False

        # Skip if the path has excluded extensions
        cleaned_path = clean_path(path)
        if cleaned_path.endswith(
            tuple(f".{extension}" for extension in options.exclude_extensions)
        ):
            return False

        return True

    def add_extra(self, path) -> None:
        if path in self._extra:
            return
        self._extra.append(path)

    def reset(self) -> None:
        self._generator = self.generate()
        self._extra_index = 0
        self._extra.clear()
