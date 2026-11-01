# ClamUI

ClamUI configures host ClamAV tools and presents their scan outcomes.

## Language

**Save & Apply**:
The explicit application of edited ClamAV configuration and scheduled-scan preferences. It may finish with some changes saved and others not applied.
_Avoid_: atomic settings transaction

**Save proposal**:
The edited configuration and scheduled-scan values captured for one Save & Apply attempt, separate from currently loaded values.

**Durable group**:
A set of preference changes confirmed saved during a Save & Apply attempt, such as ClamAV configuration files or scheduled-scan preferences.

**Scan result**:
A scan outcome containing its status, detected threats, counts, warnings, and errors. Standalone observed counts and daemon pre-counts are distinct evidence, not interchangeable measurements.
