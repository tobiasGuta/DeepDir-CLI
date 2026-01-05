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

from dataclasses import dataclass, field
from typing import Any, List, Dict
import time
import httpx
import requests

from deepdir.core.settings import (
    DEFAULT_ENCODING,
    ITER_CHUNK_SIZE,
    MAX_RESPONSE_SIZE,
    UNKNOWN,
)
from deepdir.parse.url import clean_path, parse_path
from deepdir.utils.common import get_readable_size, is_binary, replace_from_all_encodings


@dataclass
class BaseResponse:
    url: str
    status: int
    headers: Dict[str, str]
    redirect: str = ""
    history: List[str] = field(default_factory=list)
    content: str = ""
    body: bytes = b""
    datetime: str = field(init=False)
    full_path: str = field(init=False)
    path: str = field(init=False)

    def __post_init__(self):
        self.datetime = time.strftime("%Y-%m-%d %H:%M:%S")
        self.full_path = parse_path(self.url)
        self.path = clean_path(self.full_path)

    @property
    def type(self) -> str:
        if ct := self.headers.get("content-type"):
            return ct.split(";")[0]

        return UNKNOWN

    @property
    def length(self) -> int:
        if cl := self.headers.get("content-length"):
            return int(cl)

        return len(self.body)

    @property
    def size(self) -> str:
        return get_readable_size(self.length)

    def __hash__(self) -> int:
        # Hash the static parts of the response only.
        # See https://github.com/maurosoria/DeepDir/pull/1436#issuecomment-2476390956
        body = replace_from_all_encodings(self.content, self.full_path.split("#")[0], "") if self.content else self.body
        return hash((self.status, body))

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, BaseResponse):
            return False
        return (self.status, self.body, self.redirect) == (
            other.status,
            other.body,
            other.redirect,
        )


class Response(BaseResponse):
    def __init__(self, url: str, response: requests.Response) -> None:
        super().__init__(
            url=url,
            status=response.status_code,
            headers=dict(response.headers),
            redirect=response.headers.get("location") or "",
            history=[str(res.url) for res in response.history]
        )

        for chunk in response.iter_content(chunk_size=ITER_CHUNK_SIZE):
            self.body += chunk

            if len(self.body) >= MAX_RESPONSE_SIZE or (
                "content-length" in self.headers and is_binary(self.body)
            ):
                break

        if not is_binary(self.body):
            try:
                self.content = self.body.decode(
                    response.encoding or DEFAULT_ENCODING, errors="ignore"
                )
            except LookupError:
                self.content = self.body.decode(DEFAULT_ENCODING, errors="ignore")


class AsyncResponse(BaseResponse):
    @classmethod
    async def create(cls, url: str, response: httpx.Response) -> AsyncResponse:
        instance = cls(
            url=url,
            status=response.status_code,
            headers=dict(response.headers),
            redirect=response.headers.get("location") or "",
            history=[str(res.url) for res in response.history]
        )
        
        async for chunk in response.aiter_bytes(chunk_size=ITER_CHUNK_SIZE):
            instance.body += chunk

            if len(instance.body) >= MAX_RESPONSE_SIZE or (
                "content-length" in instance.headers and is_binary(instance.body)
            ):
                break

        if not is_binary(instance.body):
            try:
                instance.content = instance.body.decode(
                    response.encoding or DEFAULT_ENCODING, errors="ignore"
                )
            except LookupError:
                instance.content = instance.body.decode(DEFAULT_ENCODING, errors="ignore")

        return instance
