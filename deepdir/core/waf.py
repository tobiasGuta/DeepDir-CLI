# -*- coding: utf-8 -*-
import re
import json
from pathlib import Path
from deepdir.connection.response import BaseResponse
from deepdir.core.settings import SCRIPT_PATH

class WAF:
    _signatures = None
    _regexes = {}

    @classmethod
    def load_signatures(cls):
        if cls._signatures is not None:
            return

        sig_path = Path(SCRIPT_PATH) / "db" / "waf_signatures.json"
        try:
            with open(sig_path, "r") as f:
                cls._signatures = json.load(f)
        except Exception:
            cls._signatures = {}

        # Compile regexes
        for key, patterns in cls._signatures.items():
            cls._regexes[key] = {}
            for type_, pattern in patterns.items():
                try:
                    cls._regexes[key][type_] = re.compile(pattern, re.IGNORECASE)
                except re.error:
                    pass

    @classmethod
    def analyze(cls, response: BaseResponse) -> dict:
        cls.load_signatures()
        
        result = {
            "source": "Unknown",
            "confidence": "Low",
            "trigger": None,
            "waf_present": False
        }
        
        # Prepare data
        headers = {k.lower(): v for k, v in response.headers.items()}
        body = ""
        if hasattr(response, "content") and response.content:
            body = response.content
        elif hasattr(response, "body") and response.body:
            body = response.body.decode('utf-8', errors='ignore')
            
        # ---------------------------------------------------------
        # 1. Cloudflare Logic
        # ---------------------------------------------------------
        is_cloudflare_infra = "cloudflare" in headers.get("server", "").lower() or "cf-ray" in headers

        if is_cloudflare_infra:
            result["waf_present"] = True
            
            if "Cloudflare" in cls._regexes:
                if "block" in cls._regexes["Cloudflare"] and (match := cls._regexes["Cloudflare"]["block"].search(body)):
                     return {"source": "Cloudflare WAF", "confidence": "High", "trigger": f"Body: {match.group(0)}", "waf_present": True}
                
                if "app_error" in cls._regexes["Cloudflare"] and (match := cls._regexes["Cloudflare"]["app_error"].search(body)):
                     return {"source": "Cloudflare (App Logic)", "confidence": "High", "trigger": f"Body: {match.group(0)}", "waf_present": True}
            
            return {"source": "Cloudflare", "confidence": "Medium", "trigger": "Header: Server: cloudflare", "waf_present": True}

        # ---------------------------------------------------------
        # 2. AWS WAF / CloudFront Logic
        # ---------------------------------------------------------
        is_aws_infra = (
            "cloudfront" in headers.get("via", "").lower() or
            "x-amz-cf-id" in headers or
            "awselb" in headers.get("server", "").lower() or
            "x-amzn-errortype" in headers
        )

        if is_aws_infra:
            result["waf_present"] = True
            
            # True Block
            if headers.get("x-amzn-errortype") == "ForbiddenException":
                return {"source": "AWS WAF", "confidence": "High", "trigger": "AWS Block Signature", "waf_present": True}
            
            if "AWS" in cls._regexes:
                if "block" in cls._regexes["AWS"] and cls._regexes["AWS"]["block"].search(body):
                    return {"source": "AWS WAF", "confidence": "High", "trigger": "AWS Block Signature", "waf_present": True}
            
                # App Logic
                if "app_error" in cls._regexes["AWS"] and cls._regexes["AWS"]["app_error"].search(body):
                    return {"source": "AWS (App Logic)", "confidence": "High", "trigger": "AWS App Signature", "waf_present": True}
            
            return {"source": "AWS/CloudFront", "confidence": "Medium", "trigger": "AWS Infrastructure Header", "waf_present": True}

        # ---------------------------------------------------------
        # 3. Nginx Logic
        # ---------------------------------------------------------
        if "nginx" in headers.get("server", "").lower():
            # True Block (Server Config)
            # Check for stock page signature OR plain text "403 Forbidden" in a short body
            if "Nginx" in cls._regexes and "stock" in cls._regexes["Nginx"] and cls._regexes["Nginx"]["stock"].search(body):
                 return {"source": "Nginx (Server Block)", "confidence": "High", "trigger": "Nginx Stock Page", "waf_present": False}
            
            if len(body) < 200 and "403 forbidden" in body.lower():
                 return {"source": "Nginx (Server Block)", "confidence": "High", "trigger": "Nginx Stock Page", "waf_present": False}
            
            # App Logic (Default if header is nginx but body is not stock)
            return {"source": "Nginx (App Logic)", "confidence": "Medium", "trigger": "Nginx Header + Custom Body", "waf_present": False}

        # ---------------------------------------------------------
        # 4. Apache Logic
        # ---------------------------------------------------------
        if "apache" in headers.get("server", "").lower():
             # True Block
             if "Apache" in cls._regexes and "stock" in cls._regexes["Apache"] and cls._regexes["Apache"]["stock"].search(body):
                 return {"source": "Apache (Server Block)", "confidence": "High", "trigger": "Apache Stock Page", "waf_present": False}
             
             if len(body) < 200 and "forbidden" in body.lower():
                 return {"source": "Apache (Server Block)", "confidence": "High", "trigger": "Apache Stock Page", "waf_present": False}
             
             # App Logic
             return {"source": "Apache (App Logic)", "confidence": "Medium", "trigger": "Apache Header + Custom Body", "waf_present": False}

        # ---------------------------------------------------------
        # 5. Generic / Other WAFs
        # ---------------------------------------------------------
        if "Generic" in cls._regexes and "block" in cls._regexes["Generic"] and (match := cls._regexes["Generic"]["block"].search(body)):
            return {"source": "Generic WAF", "confidence": "Medium", "trigger": f"Body: {match.group(0)}", "waf_present": True}

        if "x-cdn" in headers and "incapsula" in headers["x-cdn"].lower():
            return {"source": "Incapsula", "confidence": "High", "trigger": "Header: X-CDN: Incapsula", "waf_present": True}
            
        if "server" in headers:
            server = headers["server"].lower()
            if "iis" in server:
                return {"source": "IIS", "confidence": "High", "trigger": "Header: Server: iis", "waf_present": False}
            if "sucuri" in server:
                return {"source": "Sucuri", "confidence": "High", "trigger": "Header: Server: sucuri", "waf_present": True}
            if "akamai" in server:
                return {"source": "Akamai", "confidence": "High", "trigger": "Header: Server: akamai", "waf_present": True}

        return result

    @classmethod
    def detect(cls, response: BaseResponse) -> str | None:
        result = cls.analyze(response)
        if result["source"] != "Unknown":
            return result["source"]
        return None
