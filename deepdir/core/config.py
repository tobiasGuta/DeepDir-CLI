# -*- coding: utf-8 -*-
from dataclasses import dataclass, field
from typing import Any, List, Set, Dict, Tuple, Optional

@dataclass
class Config:
    urls: List[str] = field(default_factory=list)
    urls_file: Optional[str] = None
    stdin_urls: Optional[str] = None
    cidr: Optional[str] = None
    raw_file: Optional[str] = None
    session_file: Optional[str] = None
    config: Optional[str] = None
    wordlists: List[str] = field(default_factory=list)
    extensions: Tuple[str, ...] = ()
    force_extensions: bool = False
    overwrite_extensions: bool = False
    exclude_extensions: Tuple[str, ...] = ()
    prefixes: Tuple[str, ...] = ()
    suffixes: Tuple[str, ...] = ()
    mutation: bool = False
    uppercase: bool = False
    lowercase: bool = False
    capitalization: bool = False
    thread_count: int = 25
    recursive: bool = False
    deep_recursive: bool = False
    force_recursive: bool = False
    recursion_depth: int = 0
    recursion_status_codes: Set[int] = field(default_factory=set)
    filter_threshold: int = 0
    subdirs: List[str] = field(default_factory=list)
    exclude_subdirs: List[str] = field(default_factory=list)
    include_status_codes: Set[int] = field(default_factory=set)
    exclude_status_codes: Set[int] = field(default_factory=set)
    exclude_sizes: Set[str] = field(default_factory=set)
    exclude_texts: Optional[List[str]] = None
    exclude_regex: Optional[str] = None
    exclude_redirect: Optional[str] = None
    exclude_response: Optional[str] = None
    no_wildcard: bool = False
    skip_on_status: Set[int] = field(default_factory=set)
    minimum_response_size: int = 0
    maximum_response_size: int = 0
    max_time: int = 0
    target_max_time: int = 0
    http_method: str = "GET"
    data: Optional[str] = None
    data_file: Optional[str] = None
    nmap_report: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    headers_file: Optional[str] = None
    follow_redirects: bool = False
    random_agents: bool = False
    auth: Optional[str] = None
    auth_type: Optional[str] = None
    cert_file: Optional[str] = None
    key_file: Optional[str] = None
    user_agent: Optional[str] = None
    cookie: Optional[str] = None
    timeout: float = 10.0
    delay: float = 0.0
    proxies: List[str] = field(default_factory=list)
    proxies_file: Optional[str] = None
    proxy_auth: Optional[str] = None
    replay_proxy: Optional[str] = None
    tor: Optional[bool] = None
    scheme: Optional[str] = None
    max_rate: int = 0
    max_retries: int = 1
    network_interface: Optional[str] = None
    ip: Optional[str] = None
    exit_on_error: bool = False
    crawl: bool = False
    async_mode: bool = False
    full_url: bool = False
    redirects_history: bool = False
    color: bool = True
    quiet: bool = False
    disable_cli: bool = False
    output_file: Optional[str] = None
    output_formats: Optional[List[str]] = None
    mysql_url: Optional[str] = None
    postgres_url: Optional[str] = None
    log_file: Optional[str] = None
    log_file_size: int = 0
    calibration: bool = False
    calibration_response: Any = None
    capital: bool = False
    output_table: Optional[str] = None

    def update(self, new_options: Dict[str, Any]):
        for key, value in new_options.items():
            if hasattr(self, key):
                setattr(self, key, value)
