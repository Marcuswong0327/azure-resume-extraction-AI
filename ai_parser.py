import json
import re
import time
from datetime import date, datetime

import requests
import streamlit as st
from dateutil import parser as date_parser
from dateutil.relativedelta import relativedelta

_PRESENT_END = re.compile(
    r"^(present|current|now|till date|to date|ongoing|today)$",
    re.IGNORECASE,
)
_RANGE_SPLIT = [
    re.compile(r"\s+to\s+", re.IGNORECASE),
    re.compile(r"\s+until\s+", re.IGNORECASE),
    re.compile(r"\s*–\s*"),
    re.compile(r"\s*—\s*"),
    re.compile(r"\s*-\s*"),
]
_TRAILING_SPAN = re.compile(r"\s*\([^)]*\)\s*$")
_YEAR_4 = re.compile(r"\b(19\d{2}|20\d{2})\b")


_COUNTRY_PHONE_RULES = {
    "AU": {
        "code": "+61",
        "name": "Australia",
    },
    "MY": {
        "code": "+60",
        "name": "Malaysia",
    },
}


class AIParser:
    """Handle Claude Sonnet 4 API integration via OpenRouter for intelligent resume parsing"""
    
    def __init__(self, api_key, country="AU"):

        if not api_key:
            raise ValueError("OpenRouter API key is required")

        if country not in _COUNTRY_PHONE_RULES:
            raise ValueError(f"Unsupported country: {country!r} (expected one of {list(_COUNTRY_PHONE_RULES)})")

        self.api_key = api_key
        self.country = country
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Title": "Resume Parser"
        }

    @staticmethod
    def _strip_existing_span(s: str) -> str:
        return _TRAILING_SPAN.sub("", s).strip()

    @staticmethod
    def _split_date_range(base: str) -> tuple[str | None, str | None]:
        for pat in _RANGE_SPLIT:
            m = pat.search(base)
            if m:
                left, right = base[: m.start()].strip(), base[m.end() :].strip()
                if left and right:
                    return left, right
        return None, None


    @staticmethod
    def _years_in(s: str) -> list[int]:
        return [int(y) for y in _YEAR_4.findall(s)]

    @staticmethod
    def _first_year_in(s: str) -> int | None:
        m = _YEAR_4.search(s)
        return int(m.group(1)) if m else None

    @staticmethod
    def _parse_range_token(part: str, hint_year: int | None) -> date | None:
        """
        Parse one side of a range. If the text has no 4-digit year, use hint_year
        (e.g. from 'December 2018' or a single trailing year on the full range) so
        'September' does not default to 1900.
        """
        part = part.strip()
        if not part:
            return None
        if _PRESENT_END.match(part):
            return date.today()
        explicit_year = AIParser._first_year_in(part)
        y = explicit_year or hint_year or 2000
        default = datetime(y, 6, 15)
        try:
            return date_parser.parse(part, default=default, fuzzy=True).date()
        except (ValueError, OverflowError, TypeError, OSError):
            return None


    @staticmethod
    # adding static method
    def _span_label(start_d: date, end_d: date) -> str:
        if end_d < start_d:
            start_d, end_d = end_d, start_d
        rd = relativedelta(end_d, start_d)
        years, months, days = rd.years, rd.months, rd.days
        parts: list[str] = []
        if years > 0:
            parts.append("1 year" if years == 1 else f"{years} years")
        if months > 0:
            parts.append("1 month" if months == 1 else f"{months} months")
        if not parts and days > 0:
            parts.append("1 day" if days == 1 else f"{days} days")
        return " ".join(parts) if parts else ""


    @staticmethod
    def _append_calculated_duration(duration_raw: str) -> str:
        """
        Turn 'Jan 2025 - Jan 2026' into 'Jan 2025 - Jan 2026 (1 year)'.
        If the range cannot be parsed, return "".
        """
        raw = (duration_raw or "").strip()
        if not raw:
            return ""
        base = AIParser._strip_existing_span(raw)
        if not base:
            return ""
        left, right = AIParser._split_date_range(base)
        if not left or not right:
            return ""

        years_base = AIParser._years_in(base)
        singleton_year = years_base[0] if len(years_base) == 1 else None
        y_left, y_right = AIParser._first_year_in(left), AIParser._first_year_in(right)
        # If only one year appears for the whole phrase (e.g. "Sep - Dec 2018"), use it for month-only sides.
        hint_left = y_left or y_right or singleton_year
        hint_right = y_right or y_left or singleton_year

        start_d = AIParser._parse_range_token(left, hint_left)
        end_d = AIParser._parse_range_token(right, hint_right)
        if start_d is None or end_d is None:
            return ""
        label = AIParser._span_label(start_d, end_d)
        if not label:
            return ""
        return f"{base} ({label})"

    def parse_resume(self, resume_text):

        try:
            if not resume_text or not resume_text.strip():
                return self._create_empty_structure()
            
            # Create prompt 
            prompt = self._create_parsing_prompt(resume_text)
            
            # Make API call 
            response = self._make_api_call_with_retry(prompt)
            
            if response:
                return self._parse_api_response(response)
            else:
                return self._create_empty_structure()
                
        except Exception as e:
            st.error(f"Error parsing resume with AI: {str(e)}")
            return self._create_empty_structure()
    
    def _create_parsing_prompt(self, resume_text):
 
        # Truncate text if too long to avoid token limits
        max_chars = 15000
        if len(resume_text) > max_chars:
            resume_text = resume_text[:max_chars] + "..."

        rule = _COUNTRY_PHONE_RULES.get(self.country, _COUNTRY_PHONE_RULES["AU"])
        country_code = rule["code"]
        country_name = rule["name"]

        prompt = f"""
You are an expert resume parser. Analyze the following resume text and extract structured information in JSON format.

Resume Text:
{resume_text}

Return ONLY a valid JSON object with EXACTLY these keys (use empty string "" when unknown or not applicable):

{{
    "role type": "",
    "first name": "",
    "last name": "",
    "mobile": "",
    "email": "",
    "duration 1": "",
    "job title 1": "",
    "company 1": "",
    "duration 2": "",
    "job title 2": "",
    "company 2": "",
    "duration 3": "",
    "job title 3": "",
    "company 3": "",
    "location": ""
}}

Ordering rules (work experience — use dates, not resume layout order):
1. **Slot 1 (duration 1, job title 1, company 1)** = the single **most recent** role by end date (still employed if it says Present/Current/Now, or the job with the latest end month/year).
2. **Slot 2** = the next role **older** than slot 1 (immediately before in career timeline).
3. **Slot 3** = the next role **older** than slot 2. If the resume has **fewer than three** distinct roles, leave duration 3, job title 3, and company 3 as "".
4. **duration N**: write **only** the employment date range as on the resume (e.g. "Jan 2022 – Present", "Jan 2025 - Jan 2026", "2019 – 2021"). **Do not** add any parenthetical length; the app will append that. If there is no clear start and end, use "".
5. **job title N** / **company N**: title and employer for that same role as slot N.

Other fields:
- **role type**: always return "" (reserved column for downstream use).
- **first name** / **last name**: from the header; split full name logically.
- **email**: contact near the name/header when possible.
- **mobile**: the candidate's phone number, **standardized to E.164 format with no spaces, dashes, or parentheses**. This batch is for **{country_name}**, so:
    - Collapse all local variations (e.g. "0412 345 678", "012-345 6789", "(02) 1234 5678", with or without a country code) into a single E.164 string.
    - For {country_name} numbers, the country code is **{country_code}**. Drop the national trunk leading "0" before adding the code (e.g. AU "0412 345 678" -> "+61412345678"; MY "012-345 6789" -> "+60123456789").
    - If the number already has a different valid country code (e.g. "+44...", "+65..."), **leave it unchanged** — do not force it to {country_code}.
    - If there is no usable phone number, return "".
- **location**: city/region/country the candidate states as current or primary (header, summary, or contact line). If none, "".

General:
- Information may appear on a second page; scan the whole text.
- Return ONLY JSON, no markdown fences or commentary.
- Use "" for any missing field.
"""
        return prompt
    
    def _make_api_call_with_retry(self, prompt, max_retries=3):

        for attempt in range(max_retries):
            try:
                response = self._make_api_call(prompt)
                if response:
                    return response
                    
            except Exception as e:
                if attempt == max_retries - 1:
                    st.error(f"OpenRouter API failed after {max_retries} attempts: {str(e)}")
                    return None
                else:
                    st.warning(f"OpenRouter API attempt {attempt + 1} failed, retrying...")
                    time.sleep(2 ** attempt)  # Exponential backoff
        
        return None
    
    def _make_api_call(self, prompt):

        try:
            payload = {
                "model": "anthropic/claude-sonnet-4",
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "max_tokens": 900,
                "temperature": 0.1,
                "stream": False
            }
            
            response = requests.post(
                self.base_url,
                headers=self.headers,
                json=payload,
                timeout=(30, 120),
            )
            
            if response.status_code == 200:
                result = response.json()
                content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                return content
            else:
                error_msg = f"Claude API error: {response.status_code}"
                try:
                    error_detail = response.json()
                    error_msg += f" - {error_detail}"
                except:
                    error_msg += f" - {response.text}"
                raise Exception(error_msg)
                
        except requests.exceptions.Timeout:
            raise Exception("Claude API request timed out")
        except requests.exceptions.RequestException as e:
            raise Exception(f"Network error calling Claude API: {str(e)}")
        except Exception as e:
            raise Exception(f"Error calling Claude API: {str(e)}")
    
    def _parse_api_response(self, response_text):

        try:
            # Try to find JSON in the response
            response_text = response_text.strip()
            
            # Remove any markdown code block markers
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            elif response_text.startswith("```"):
                response_text = response_text[3:]
                
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            
            response_text = response_text.strip()
            
            # Try to find JSON object in the text
            start_idx = response_text.find('{')
            end_idx = response_text.rfind('}')
            
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                json_text = response_text[start_idx:end_idx + 1]
                parsed_data = json.loads(json_text)
            else:
                # Try parsing the entire text
                parsed_data = json.loads(response_text)
            
            # Validate structure
            return self._validate_parsed_data(parsed_data)
            
        except json.JSONDecodeError as e:
            st.warning(f"Failed to parse AI response as JSON: {str(e)}")
            st.text("Raw response:")
            st.code(response_text)
            return self._create_empty_structure()
        except Exception as e:
            st.warning(f"Error processing AI response: {str(e)}")
            return self._create_empty_structure()
    
    def _validate_parsed_data(self, data):
        def s(key: str) -> str:
            return str(data.get(key, "") or "").strip()

        validated_data = {
            "role type": s("role type"),
            "full name": "",
            "first name": s("first name"),
            "last name": s("last name"),
            "mobile": s("mobile"),
            "email": s("email"),
            "duration 1": s("duration 1"),
            "job title 1": s("job title 1"),
            "company 1": s("company 1"),
            "duration 2": s("duration 2"),
            "job title 2": s("job title 2"),
            "company 2": s("company 2"),
            "duration 3": s("duration 3"),
            "job title 3": s("job title 3"),
            "company 3": s("company 3"),
            "location": s("location"),
        }

        # Backward compatibility if the model returns the old two-job schema
        if not validated_data["job title 1"] and s("current job title"):
            validated_data["job title 1"] = s("current job title")
            validated_data["company 1"] = s("current company")
            validated_data["duration 1"] = s("duration 1") or s("current duration")
        if not validated_data["job title 2"] and s("previous job title"):
            validated_data["job title 2"] = s("previous job title")
            validated_data["company 2"] = s("previous company")
            validated_data["duration 2"] = s("duration 2") or s("previous duration")

        for dkey in ("duration 1", "duration 2", "duration 3"):
            validated_data[dkey] = self._append_calculated_duration(validated_data[dkey])

        validated_data["full name"] = " ".join(
            p for p in (validated_data["first name"], validated_data["last name"]) if p
        ).strip()

        return validated_data

    def _create_empty_structure(self):
        return {
            "role type": "",
            "full name": "",
            "first name": "",
            "last name": "",
            "mobile": "",
            "email": "",
            "duration 1": "",
            "job title 1": "",
            "company 1": "",
            "duration 2": "",
            "job title 2": "",
            "company 2": "",
            "duration 3": "",
            "job title 3": "",
            "company 3": "",
            "location": "",
        }
