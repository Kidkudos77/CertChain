"""
CertChain — Transcript Parser
================================
Combines BERT course detection (Layer 1) with GPA regex extraction
to produce a complete structured payload for the smart contract (Layer 2).

Falls back to regex-only mode if BERT model is not yet trained.
"""

import re, json
from dataclasses import dataclass
from typing import List, Optional

W1, W2, W3      = 0.40, 0.40, 0.20
SCORE_THRESHOLD = 0.70
MIN_GPA         = 3.0
MIN_COURSES     = 3

# Official Cyber Defense Certificate courses. Each entry matches either the
# course code (formatting-tolerant: CIS4385C / CIS 4385C / CIS-4385C) or a
# distinguishing title phrase, since a real transcript may list either.
# These five codes must match api/server.js's VALID_COURSES allowlist
# exactly — that allowlist is the source of truth and is not touched here.
COURSE_PATTERNS = {
    'CIS4385C': [r'\bCIS[\s-]?4385C\b', r'\bdigital\s+forensics\b'],
    'CIS4360':  [r'\bCIS[\s-]?4360\b',  r'\bcomputer\s+security\b'],
    'CIS4361':  [r'\bCIS[\s-]?4361\b',  r'\bapplied\s+security\b'],
    'CNT4406':  [r'\bCNT[\s-]?4406\b',  r'\bnetwork\s+security\b'],
    'COP3710':  [r'\bCOP[\s-]?3710\b',  r'\bdatabase\s+management\b'],
}

# Prerequisite: COP 3014C (Fundamentals of Programming) must be completed
# BEFORE starting the certificate program of study. Detected separately
# from COURSE_PATTERNS above — it is not one of the 5 certificate courses
# and must never count toward MIN_COURSES; it's a hard gate, like MIN_GPA.
PREREQUISITE_COURSE = 'COP3014C'
PREREQUISITE_PATTERNS = [r'\bCOP[\s-]?3014C?\b', r'\bfundamentals\s+of\s+programming\b']


@dataclass
class ParsedTranscript:
    student_id:           str
    student_name:         Optional[str]
    gpa:                  float
    courses_completed:    List[str]
    prerequisite_completed: bool
    bert_confidence:      float
    eligibility_score:    float
    eligible:             bool
    ineligibility_reason: Optional[str]
    program:              str = 'FAMU-FCCS'


class TranscriptParser:

    def __init__(self, bert_model_dir: str = None):
        self.bert = None
        if bert_model_dir:
            try:
                from nlp.bert_classifier import BERTClassifier
                self.bert = BERTClassifier()
                self.bert.load(bert_model_dir)
                print('Parser: BERT model loaded.')
            except Exception as e:
                print(f'Parser: BERT unavailable ({e}). Using regex fallback.')

    def parse(self, transcript_text: str, student_id: str = None) -> ParsedTranscript:
        sid    = student_id or self._extract_id(transcript_text)
        name   = self._extract_name(transcript_text)
        gpa    = self._extract_gpa(transcript_text)
        prerequisite_completed = self._detect_prerequisite(transcript_text)

        if self.bert:
            result     = self.bert.parse_transcript(transcript_text)
            courses    = result['courses_detected']
            confidence = result['bert_confidence']
        else:
            courses, confidence = self._regex_courses(transcript_text), 0.75

        score    = round(W1*(gpa/4.0) + W2*(len(courses)/5.0) + W3*confidence, 4)
        eligible, reason = self._check(gpa, courses, score, prerequisite_completed)

        return ParsedTranscript(
            student_id=sid, student_name=name, gpa=gpa,
            courses_completed=sorted(courses),
            prerequisite_completed=prerequisite_completed,
            bert_confidence=confidence, eligibility_score=score,
            eligible=eligible, ineligibility_reason=reason,
        )

    def to_payload(self, t: ParsedTranscript) -> str:
        return json.dumps({
            'gpa':               t.gpa,
            'courses_completed': t.courses_completed,
            'prerequisite_completed': t.prerequisite_completed,
            'bert_confidence':   t.bert_confidence,
            'eligibility_score': t.eligibility_score,
            'student_name':      t.student_name,
        })

    def _extract_id(self, text):
        m = re.search(r'\b(FAMU\d{4,8})\b', text, re.I)
        return m.group(1).upper() if m else 'UNKNOWN'

    def _extract_name(self, text):
        m = re.search(r'(?:student\s*name|name)\s*[:\-]\s*([A-Z][a-z]+ [A-Z][a-z]+)', text, re.I)
        return m.group(1) if m else None

    def _extract_gpa(self, text):
        m = re.search(r'(?:cumulative\s+)?gpa\s*[:\-]?\s*(\d\.\d{1,2})', text, re.I)
        if m:
            g = float(m.group(1))
            return g if 0.0 <= g <= 4.0 else 0.0
        return 0.0

    def _detect_prerequisite(self, text):
        """Whether COP 3014C (Fundamentals of Programming) appears on the
        transcript. Always regex-based, independent of whether BERT is used
        for the 5 certificate courses — BERT's training taxonomy
        (COURSE_VARIATIONS in dataset/data_loader.py) doesn't include this
        prerequisite, so there's nothing to defer to it for."""
        return any(re.search(p, text, re.I) for p in PREREQUISITE_PATTERNS)

    def _regex_courses(self, text):
        """Fallback and baseline for evaluation comparison.
        Matches the five official Cyber Defense Certificate course codes or
        their distinguishing title keywords — see COURSE_PATTERNS.
        """
        found = set()
        for code, patterns in COURSE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, text, re.I):
                    found.add(code)
                    break
        return sorted(found)

    def _check(self, gpa, courses, score, prerequisite_completed):
        if not prerequisite_completed:
            return False, f'Prerequisite {PREREQUISITE_COURSE} (Fundamentals of Programming) not completed'
        if gpa < MIN_GPA:
            return False, f'GPA {gpa} below minimum {MIN_GPA}'
        if len(courses) < MIN_COURSES:
            return False, f'Only {len(courses)} FCCS courses completed (need {MIN_COURSES})'
        if score < SCORE_THRESHOLD:
            return False, f'Eligibility score {score} below threshold {SCORE_THRESHOLD}'
        return True, None
