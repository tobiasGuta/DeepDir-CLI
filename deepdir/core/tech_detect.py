# -*- coding: utf-8 -*-
import warnings
from deepdir.connection.response import BaseResponse

# Suppress Wappalyzer warnings if any
warnings.filterwarnings("ignore", category=UserWarning, module='Wappalyzer')

try:
    from Wappalyzer import Wappalyzer, WebPage
    _WAPPALYZER_AVAILABLE = True
except ImportError:
    _WAPPALYZER_AVAILABLE = False

class TechDetect:
    _wappalyzer = None

    @classmethod
    def _get_wappalyzer(cls):
        if cls._wappalyzer is None and _WAPPALYZER_AVAILABLE:
            try:
                # Initialize Wappalyzer
                # This might download the latest technologies.json on first run
                cls._wappalyzer = Wappalyzer.latest()
            except Exception:
                # Fallback if download fails or other issues
                cls._wappalyzer = None
        return cls._wappalyzer

    @classmethod
    def analyze(cls, response: BaseResponse) -> list[str]:
        if not _WAPPALYZER_AVAILABLE:
            return []

        wappalyzer = cls._get_wappalyzer()
        if not wappalyzer:
            return []
        
        # Prepare data for Wappalyzer
        url = response.url
        headers = {k.lower(): v for k, v in response.headers.items()}
        
        body = ""
        if hasattr(response, "content") and response.content:
            body = response.content
        elif hasattr(response, "body") and response.body:
            try:
                body = response.body.decode('utf-8', errors='ignore')
            except Exception:
                pass
                
        try:
            webpage = WebPage(url, body, headers)
            technologies = wappalyzer.analyze(webpage)
            return list(technologies)
        except Exception:
            return []
