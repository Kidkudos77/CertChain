# Labeling Rubric — CertChain Eligibility

## Task

For each (course, requirement) pair, answer: **Does this course satisfy this
certificate requirement?** Label 1 (yes) or 0 (no).

## Definitions

A course **satisfies** a requirement if a reasonable registrar would accept it
as fulfilling that specific requirement for the FAMU Cyber Defense Certificate,
given only the course name, code, credit hours, and granting institution.

## Rules (apply in order)

1. **Credit hours must be >= the requirement's credit hours (3).** A 1-credit
   course cannot satisfy a 3-credit requirement regardless of topic match.

2. **Topic must be substantially the same.** The course must cover the core
   content of the requirement, not merely overlap.
   - "Introduction to Computer Security" satisfies R2 ("Introduction to Computer
     Security"). Obviously.
   - "Network Security" satisfies R4 ("Network Security"). Name match.
   - "Computer Forensics" satisfies R1 ("Digital Forensics"). Same domain,
     "computer" and "digital" are synonymous in this context.
   - "Database Design" satisfies R5 ("Database Management Systems"). Core
     content overlap — design is a component of DBMS curricula.
   - "Web Development" does NOT satisfy R4 ("Network Security"). Different domain.
   - "IT Essentials" does NOT satisfy R3 ("Applied Security"). Too general.

3. **"Applied Security" (R3) requires explicit security focus.** A course must
   have security, cybersecurity, information security, or infosec as a primary
   topic. Courses that merely touch security as a subtopic do not qualify.
   Courses in penetration testing, ethical hacking, or security auditing DO qualify.

4. **Prerequisite (COP 3014C, "Fundamentals of Programming"):** any introductory
   programming course (C, C++, Java, Python) with >= 3 credits satisfies this.
   Data structures and algorithms courses do NOT — they are beyond introductory.

5. **Elective/general courses never satisfy a specific requirement.** If the
   course name is "Computer Elective", "Free Elective", or similar generic
   placeholder, label 0 regardless of what it might be.

## Exclusions

- **Combined/bundled entries** (code contains `/` after dept prefix, e.g.
  `CIS 228/244/247`) are excluded from the sample. You will not encounter them.

- **Replaced/discontinued courses** are still labeled. A student may present
  a discontinued course from their transcript.

## Edge Cases

- If genuinely uncertain after applying rules 1–4, label 0. The rubric favors
  precision (fewer false positives) over recall, because a false positive means
  issuing a credential to someone who didn't earn it.

- Cross-listed courses (e.g. "Management of Data Analytics / MGT 206") are
  judged on their content, not their department prefix.

## What NOT to consider

- Do not consider the granting institution's reputation.
- Do not consider whether the course is offered online vs. in-person.
- Do not consider the student's grade (that's a separate gate check).
- Do not look up the course on the institution's website. Judge from the name
  and credits alone. This is the same information the model sees.
