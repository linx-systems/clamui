# ClamUI

ClamUI configures host ClamAV tools and presents their scan outcomes.

## Language

**Flush**:
The application of edited ClamAV configuration and scheduled-scan preferences, in one of two modes. A *direct* flush runs automatically whenever the user leaves a settings section, and includes only proposals the backend confirms do not need the privileged helper. A *full* flush includes every pending proposal (direct and privileged) in one batch, behind a single authorization prompt; it runs automatically when Preferences is closed, and on demand from the header Save button. Either mode may finish with some changes saved and others not applied.
_Avoid_: Save & Apply, atomic settings transaction

**Save proposal**:
The edited configuration and scheduled-scan values captured for one flush attempt, separate from currently loaded values.

**Durable group**:
A set of preference changes confirmed saved during a flush attempt, such as ClamAV configuration files or scheduled-scan preferences.

**Scan result**:
A scan outcome containing its status, detected threats, counts, warnings, and errors. Standalone observed counts and daemon pre-counts are distinct evidence, not interchangeable measurements.
