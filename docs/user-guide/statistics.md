# Statistics Dashboard

[← Back to User Guide](../USER_GUIDE.md)

---

## Statistics Dashboard

Monitor your system's security status and scan activity with ClamUI's comprehensive Statistics Dashboard. Get an
at-a-glance view of your protection level, scan history, and threat detection trends.

**What you'll find in the Statistics Dashboard:**

- **Protection Status**: Current security posture and last scan information
- **Scan Metrics**: Aggregated statistics for scans, files checked, and threats found
- **Timeframe Filtering**: View statistics by day, week, month, or all time
- **Activity Charts**: Visual trends showing scan and threat patterns
- **Quick Actions**: One-click access to common scanning operations

**When to use the Statistics Dashboard:**

- Check your current protection status at a glance
- Review your scanning activity over time
- Identify patterns in threat detection
- Verify that scheduled scans are running
- Monitor scanning coverage (how many files you're checking)
- Generate insights for security reports

### Understanding Protection Status

The Protection Status section at the top of the Statistics Dashboard tells you whether your system is currently
protected based on your scanning activity and virus definition freshness.

#### Opening the Statistics Dashboard

1. Click the **Statistics** button in the navigation bar
2. The dashboard loads automatically with your current statistics
3. All data is calculated from your scan history logs (`~/.local/share/clamui/logs/`)

#### Protection Status Levels

The Statistics Dashboard determines your protection status from how recently you last scanned your system (*scan
recency*). It reads your scan history logs and compares your most recent scan against two age thresholds: 7 days and
30 days. (Virus-definition freshness is *not* a factor in this dashboard's status.)

**Protection Levels:**

| Status             | Badge Color   | Icon        | What It Means                    | Criteria                                                       |
|--------------------|---------------|-------------|----------------------------------|----------------------------------------------------------------|
| 🟢 **Protected**   | Green         | ✅ Checkmark | System is actively protected     | Last scan within the past 7 days                               |
| 🟡 **At Risk**     | Yellow/Orange | ⚠️ Warning  | Protection is degraded           | Last scan 7-30 days ago                                        |
| 🔴 **Unprotected** | Red           | ❌ Error     | System lacks adequate protection | No scans performed, or last scan over 30 days ago              |
| ⚪ **Unknown**      | Gray          | ❓ Question  | Cannot determine status          | Unable to access scan history or parse data                    |

#### Protection Status Display

```
┌─────────────────────────────────────────────────────┐
│ Protection Status                      [🔄 Refresh] │
│ Current system security posture                     │
├─────────────────────────────────────────────────────┤
│ ✅  System Status                      [Protected] │
│     System is protected                            │
│                                                     │
│ 🕐  Last Scan                                       │
│     2026-01-02 14:30 (2 hours ago)                 │
└─────────────────────────────────────────────────────┘
```

**What you see:**

- **System Status Row**: Shows your current protection level with icon and message
- **Protection Badge**: Color-coded label indicating your status (Protected/At Risk/Unprotected/Unknown)
- **Status Message**: Explanation of your current protection state
- **Last Scan Row**: Timestamp of your most recent scan with human-readable age
- **Refresh Button**: Manually reload statistics to get latest data

#### Protection Status Messages

**🟢 Protected:**

- `"System is protected"` - Your last scan was within the past 7 days

**🟡 At Risk:**

- `"Last scan was over a week ago"` - Your last scan was 7-30 days ago (time to scan again)

**🔴 Unprotected:**

- `"No scans performed yet"` - You haven't run any scans (run your first scan!)
- `"Last scan was over 30 days ago"` - Your last scan is too old to provide meaningful protection

**⚪ Unknown:**

- `"Unable to determine status"` - ClamUI couldn't read or parse your scan history. Before you've ever scanned, the
  badge instead reads **No Data** with the message `"No scan history available"`.

#### Improving Your Protection Status

If your status is not **Protected**, here's what to do:

**For "At Risk" or "Unprotected" (scan age issues):**

1. Click **Quick Scan** in the Quick Actions section (bottom of Statistics view)
2. Or navigate to the Scan view and perform a scan of your important folders
3. Consider setting up [Scheduled Scans](scheduling.md) for automatic protection
4. Refresh the Statistics view to see updated status

**Keeping virus definitions fresh:**

Updating virus definitions does **not** change the Statistics protection status (which is based on scan recency), but
current definitions are essential for accurate detection. Open the **Database** view from the sidebar to update them.

**For "Unknown" status:**

1. Check that ClamAV is installed correctly (see [Troubleshooting](troubleshooting.md))
2. Verify you have scan history in the Logs view
3. Try refreshing the statistics manually
4. If the issue persists, run a new scan to generate fresh data

💡 **Tip**: Set up a weekly scheduled scan to maintain "Protected" status automatically without manual intervention.

⚠️ **Important**: The Protection Status is based on *scan recency*, not real-time threat detection. ClamAV doesn't
provide active real-time protection like some commercial antivirus products. Regular scans are essential.

#### Last Scan Information

The **Last Scan** row shows details about your most recent scan:

- **Timestamp**: Date and time in YYYY-MM-DD HH:MM format (24-hour clock)
- **Age**: Human-readable time since the scan (e.g., "2 hours ago", "3 days ago")
- **No Scans**: Shows "No scans recorded" if you haven't run any scans yet

**Age Display Formats:**

| Age        | Display Format          | Example                                  |
|------------|-------------------------|------------------------------------------|
| < 1 hour   | "less than an hour ago" | 2026-01-02 14:30 (less than an hour ago) |
| 1-23 hours | "X hour(s) ago"         | 2026-01-02 10:00 (4 hours ago)           |
| 1-6 days   | "X day(s) ago"          | 2026-01-01 14:30 (1 day ago)             |
| 7+ days    | "X week(s) ago"         | 2025-12-15 09:00 (3 weeks ago)           |

### Viewing Scan Statistics

The **Scan Statistics** section displays aggregated metrics for all scans in your selected timeframe.

#### Statistics Cards

```
┌─────────────────────────────────────────────────────┐
│ Scan Statistics                                     │
│ Statistics for: Dec 26 - Jan 02, 2026              │
├─────────────────────────────────────────────────────┤
│ 🔍  Total Scans                               42   │
│     Number of scans performed                      │
│                                                     │
│ 📄  Files Scanned                         15,234   │
│     Total files checked                            │
│                                                     │
│ ⚠️  Threats Detected                            3   │
│     Malware and suspicious files found             │
│                                                     │
│ ✅  Clean Scans                                39   │
│     Scans with no threats found                    │
│                                                     │
│ ⏱️  Average Scan Duration                   2m 15s │
│     Mean time per scan                             │
└─────────────────────────────────────────────────────┘
```

#### Understanding Each Metric

**1. Total Scans**

- **What it is**: Number of scans you've performed in the selected timeframe
- **Includes**: Both manual and scheduled scans
- **Use case**: Monitor your scanning frequency
- **Example**: `42` means you ran 42 scans in the past week

**What counts as a scan:**

- Manual scans from the Scan view
- Scheduled scans (automatic)
- Scans run from the command line
- Scans triggered via drag-and-drop

**What doesn't count:**

- Cancelled scans (stopped before completion)
- Database updates (shown separately in Logs)
- Failed scans that never started

**2. Files Scanned**

- **What it is**: Total number of individual files checked across all scans
- **Format**: Formatted with thousand separators (e.g., `15,234` not `15234`)
- **Calculation**: Sum of all files checked in every scan in the timeframe
- **Use case**: Understand your scanning coverage

**Example interpretation:**

- `15,234 files scanned` with `42 total scans` = average of 363 files per scan
- High file count typically means full system scans or large folder scans
- Low file count might indicate targeted Quick Scans of specific folders

**What files are counted:**

- Every file ClamAV examines, including:
    - Regular files (documents, images, executables, etc.)
    - Archive contents (files inside .zip, .tar, .7z, etc.)
    - Email attachments (if scanning mail folders)
    - Nested archives (archives within archives)

**What's excluded from the count:**

- Directories (folders are traversed but not "scanned")
- Excluded files/patterns (see [Managing Exclusions](settings.md#managing-exclusion-patterns))
- Symbolic links (unless they point to real files)
- Files that couldn't be accessed (permission errors)

💡 **Tip**: If your Files Scanned count seems lower than expected, check
your [exclusion patterns](settings.md#managing-exclusion-patterns) - you might be excluding more than intended.

**3. Threats Detected**

- **What it is**: Total number of threats (malware, viruses, suspicious files) found
- **Color coding**: Displays in red if threats were found, normal color if zero
- **Calculation**: Sum of all infected files across all scans in the timeframe
- **Use case**: Monitor threat activity on your system

**What counts as a threat:**

- Any file that ClamAV flags as infected
- All severity levels (CRITICAL, HIGH, MEDIUM, LOW)
- EICAR test files (if you tested with the EICAR button)
- False positives (files incorrectly identified as threats)

**Example scenarios:**

| Threats Detected | Interpretation                     | What To Do                                                                           |
|------------------|------------------------------------|--------------------------------------------------------------------------------------|
| `0` (in green)   | No threats found - system is clean | Continue regular scanning schedule                                                   |
| `1-2` (in red)   | Minimal threat activity            | Review [Quarantine](quarantine.md) to see what was found                    |
| `3-10` (in red)  | Moderate threat detection          | Check Quarantine, investigate sources, run additional scans                          |
| `10+` (in red)   | Significant threat activity        | Review all detected threats, check for infection patterns, consider full system scan |

**Understanding the count:**

- If the same infected file is scanned multiple times, it's counted each time
- Quarantining a file doesn't remove it from statistics (historical data is preserved)
- The count reflects *when threats were detected*, not when they appeared on your system

💡 **Tip**: A sudden spike in Threats Detected (visible in the [activity chart](#understanding-scan-activity-charts))
might indicate a new infection source like a USB drive or download.

⚠️ **Note**: Not all detections are equally serious. ClamAV assigns each threat a severity (CRITICAL, HIGH, MEDIUM, or
LOW), but this count treats every detection equally - a LOW-severity test file counts the same as CRITICAL ransomware.

**4. Clean Scans**

- **What it is**: Number of scans that completed with zero threats found
- **Formula**: Clean Scans + Infected Scans ≈ Total Scans (error scans excluded)
- **Use case**: Gauge your system's overall health

**Example analysis:**

```
Total Scans: 42
Clean Scans: 39
Threats Detected: 3

Analysis: 39 out of 42 scans were clean (93% success rate)
```

**What makes a scan "clean":**

- Scan completed successfully (no errors)
- Zero infected files found
- All scanned files passed ClamAV checks

**Why clean scans matter:**

- High clean scan percentage (90%+) = healthy system with minimal threats
- Low clean scan percentage (<80%) = may indicate recurring infections or problematic files
- Consistent clean scans = good evidence your protection is working

**5. Average Scan Duration**

- **What it is**: Mean time it took to complete scans in the timeframe
- **Format**: Human-readable (e.g., `2m 15s`, `45.3s`, `1h 5m`)
- **Calculation**: Total time spent scanning ÷ number of scans
- **Use case**: Understand scanning performance and plan scan schedules

**Duration Formats:**

| Duration     | Display Format | Example  |
|--------------|----------------|----------|
| < 60 seconds | `X.Xs`         | `45.3s`  |
| 1-59 minutes | `Xm Ys`        | `2m 15s` |
| 1+ hours     | `Xh Ym`        | `1h 5m`  |

**Interpreting Average Duration:**

| Average Duration | Typical Scenario                | What It Means                                       |
|------------------|---------------------------------|-----------------------------------------------------|
| < 30 seconds     | Quick Scans of Downloads folder | Small, targeted scans of specific folders           |
| 30s - 5 minutes  | Home folder scans               | Medium-sized scans with moderate file counts        |
| 5-30 minutes     | Partial system scans            | Scanning multiple large folders or user directories |
| 30+ minutes      | Full system scans               | Complete filesystem scans with high file counts     |

**Factors affecting scan duration:**

- **File count**: More files = longer scans
- **File sizes**: Larger files take longer to scan
- **File types**: Archives and compressed files are slower
- **Backend**: `daemon` backend is 10-50x faster than `clamscan` (see [Scan Backend Options](settings.md#scan-backend-options))
- **Storage speed**: SSDs scan faster than HDDs
- **System load**: CPU/disk usage from other programs slows scans

💡 **Tip**: If your average duration seems too long:

1. Switch to the `daemon` backend in [Settings](settings.md#scan-backend-options) for dramatically faster scans
2. Use scan profiles with targeted folders instead of full system scans
3. Add exclusions for cache directories and other non-critical folders

#### Date Range Display

The statistics group description shows the date range for your selected timeframe:

**Examples:**

- `"Statistics for: Dec 26 - Jan 02, 2026"` - Weekly view showing 7-day range
- `"Statistics for: Jan 01 - Jan 02, 2026"` - Daily view showing 24-hour range
- `"Aggregated metrics for all time"` - All Time view (no date filtering)

**Empty State:**

If you haven't run any scans yet, the statistics section displays:

```
┌─────────────────────────────────────────────────────┐
│ Scan Statistics                                     │
│ Run your first scan to see statistics here         │
├─────────────────────────────────────────────────────┤
│ 🔍  Total Scans                                0   │
│ 📄  Files Scanned                              0   │
│ ⚠️  Threats Detected                            0   │
│ ✅  Clean Scans                                 0   │
│ ⏱️  Average Scan Duration                      -- │
└─────────────────────────────────────────────────────┘
```

### Filtering by Timeframe

The **Timeframe** selector lets you filter statistics to specific time periods, helping you analyze recent activity or
view your complete scanning history.

#### Timeframe Options

```
┌─────────────────────────────────────────────────────┐
│ Timeframe                                           │
│ Select the time period for statistics               │
├─────────────────────────────────────────────────────┤
│           [ Day ] [ Week ] [ Month ] [ All Time ]  │
└─────────────────────────────────────────────────────┘
```

**Available Timeframes:**

| Timeframe    | Time Period      | When to Use                                                | Example Use Case                                 |
|--------------|------------------|------------------------------------------------------------|--------------------------------------------------|
| **Day**      | Last 24 hours    | Monitor today's activity, verify scheduled scans ran today | Check if your daily 3am scan completed           |
| **Week**     | Last 7 days      | Review recent protection (default view), weekly summary    | See this week's scanning coverage before weekend |
| **Month**    | Last 30 days     | Monthly reports, identify long-term trends                 | Generate monthly security report for team        |
| **All Time** | Complete history | View cumulative statistics, assess overall protection      | Review total threats found since installation    |

#### Changing the Timeframe

1. **Click the desired timeframe button** (Day, Week, Month, or All Time)
2. The button becomes **highlighted/active** to show it's selected
3. Statistics **automatically reload** for the new timeframe
4. The **date range updates** in the statistics section (except for All Time)
5. The **activity chart updates** to show trends for the selected period

**Visual Feedback:**

- **Active button**: Highlighted with accent color, appears "pressed"
- **Inactive buttons**: Neutral appearance
- **Loading state**: Buttons disabled with spinner while data loads
- **Only one button active**: Selecting a new timeframe deactivates the previous one

💡 **Tip**: The timeframe selection is remembered during your session but resets to "Week" when you relaunch ClamUI.

#### Timeframe and Chart Data Points

The number of data points in the [activity chart](#understanding-scan-activity-charts) varies by timeframe:

| Timeframe    | Data Points | Interval          | Example                                                 |
|--------------|-------------|-------------------|---------------------------------------------------------|
| **Day**      | Up to 6     | Day-level (MM/DD) | 06/06, 06/07 (scans grouped by calendar day)            |
| **Week**     | 7 points    | Daily intervals   | 06/01, 06/02, ..., 06/07 (one bar per day)              |
| **Month**    | 10 points   | 3-day intervals   | 06/01, 06/04, ..., 06/28 (first day of each 3-day span) |
| **All Time** | 12 points   | Monthly intervals | 01/01, 02/01, ..., 12/01 (distributed across history)   |

This ensures the chart remains readable regardless of how much data you have.

#### Examples: Comparing Timeframes

**Scenario 1: Daily Quick Scans**

You run Quick Scans of Downloads every day at 3am via scheduled scans.

- **Day view**: Shows 1 scan (today's 3am scan)
- **Week view**: Shows 7 scans (one per day)
- **Month view**: Shows ~30 scans (one per day for 30 days)
- **All Time view**: Shows total scans since you installed ClamUI

**Scenario 2: Weekly Full Scans**

You run a Full Scan every Sunday at 2am.

- **Day view**: Shows 1 scan if today is Sunday, 0 if another day
- **Week view**: Shows 1 scan (this week's Sunday scan)
- **Month view**: Shows 4-5 scans (4-5 Sundays in a month)
- **All Time view**: Shows total scans since installation

**Scenario 3: Mixed Manual and Scheduled**

You have daily scheduled scans plus manual scans when downloading files.

- **Day view**: Shows today's scheduled scan + any manual scans you ran today
- **Week view**: Shows 7 scheduled scans + manual scans from the week
- **Month view**: Shows all 30 scheduled scans + all manual scans
- **All Time view**: Complete combined history

#### Understanding Filtered Statistics

When you change timeframes, **all statistics recalculate** for the selected period:

**Example: Switching from Week to Month**

```
Week View (last 7 days):
- Total Scans: 7
- Files Scanned: 2,450
- Threats Detected: 0
- Average Duration: 1m 30s

Month View (last 30 days):
- Total Scans: 35
- Files Scanned: 10,283
- Threats Detected: 2
- Average Duration: 1m 42s
```

**What changed:**

- Scans increased 5x (7 → 35) because we're looking at 4x more time
- Files scanned increased ~4x (proportional to scan count)
- Threats appeared (2 were found 10 days ago, outside the weekly view)
- Average duration increased slightly (might have had longer scans 2-3 weeks ago)

💡 **Tip**: Use **Week view** as your default for monitoring recent activity, then switch to **Month** when you need a
broader perspective or **Day** to troubleshoot today's scans.

⚠️ **Note**: Timeframe filtering affects statistics and charts but does NOT filter the Logs view - use the Logs view
itself to see individual scan details.

### Understanding Scan Activity Charts

The **Scan Activity** chart provides a visual representation of your scanning patterns and threat detection trends over
the selected timeframe.

(The activity chart is rendered with matplotlib, which ClamUI ships as a runtime dependency.)

#### Chart Overview

```
┌─────────────────────────────────────────────────────┐
│ Scan Activity                                       │
│ Scan trends over the selected timeframe            │
├─────────────────────────────────────────────────────┤
│                                                     │
│   8 ┤                                               │
│   7 ┤     ▅▅                  ▅▅                    │
│   6 ┤     ██        ▅▅        ██                    │
│   5 ┤ ▅▅  ██        ██    ▅▅  ██                    │
│   4 ┤ ██  ██    ▅▅  ██    ██  ██    ▅▅              │
│   3 ┤ ██  ██    ██  ██    ██  ██    ██              │
│   2 ┤ ██  ██    ██  ██    ██  ██    ██              │
│   1 ┤ ██  ██    ██  ██    ██  ██    ██  ▅▅          │
│   0 ┴─────────────────────────────────────────      │
│     Mon Tue Wed Thu Fri Sat Sun                     │
│                                                     │
│     Legend: █ Scans  ▅ Threats                      │
│                                                     │
└─────────────────────────────────────────────────────┘
```

**Chart Components:**

- **Blue bars**: Number of scans performed in each time interval
- **Red bars**: Number of threats detected in each interval
- **X-axis**: Time intervals (dates or time periods)
- **Y-axis**: Count (number of scans or threats)
- **Legend**: Identifies what the blue and red bars represent
- **Grid**: Light background grid for easier reading

#### Reading the Chart

**Bar Chart Structure:**

For each time interval, you'll see two bars side-by-side:

- **Left bar (blue)**: How many scans ran in this interval
- **Right bar (red)**: How many threats were found in this interval

**Example interpretation (Weekly view):**

```
Monday:    7 scans, 0 threats  (tall blue bar, no red bar)
Tuesday:   8 scans, 1 threat   (tall blue bar, short red bar)
Wednesday: 5 scans, 0 threats  (medium blue bar, no red bar)
...
```

**What the chart tells you:**

✅ **Consistent blue bars**: Regular scanning schedule is working
✅ **Low/no red bars**: System is clean with minimal threat activity
⚠️ **Missing blue bars**: Gaps in your scanning coverage (consider scheduled scans)
⚠️ **Tall red bars**: Spike in threat detection (investigate the source)
⚠️ **Red bars without blue bars**: Impossible (indicates data issue)

#### Chart Time Intervals

The X-axis shows different time units depending on your selected timeframe:

**Daily View (day-level intervals):**

```
X-axis labels: MM/DD (e.g. 06/06, 06/07)
Example: "06/07" shows all scans on June 7
```

Note: every timeframe labels the x-axis in MM/DD (month/day) format - the chart is always day-based, so the daily
view shows recent calendar days rather than intra-day hours.

**Weekly View (7 data points - daily):**

```
X-axis labels: 12/26, 12/27, 12/28, 12/29, 12/30, 12/31, 01/01
Format: MM/DD (month/day)
Example: "12/26" shows all scans on December 26
```

**Monthly View (10 data points - 3-day intervals):**

```
X-axis labels: 12/03, 12/06, 12/09, ..., 12/30
Format: MM/DD (first day of each 3-day period)
Example: "12/06" shows scans from Dec 6-8
```

**All Time View (12 data points - monthly):**

```
X-axis labels: 01/01, 02/01, 03/01, ..., 12/01
Format: MM/DD (first day of each month)
Example: "03/01" shows all scans in March
```

💡 **Tip**: Hover over or click chart elements in some GTK themes to see tooltips with exact values (though this feature
depends on your desktop environment).

#### Chart Patterns and What They Mean

**Pattern 1: Steady blue bars, no red bars (Ideal)**

```
All intervals have similar blue bar heights, red bars are absent
Interpretation: Consistent scanning schedule, no threats detected
Action: ✅ Keep up the good work! Your protection strategy is working.
```

**Pattern 2: Scattered blue bars (Irregular scanning)**

```
Some intervals have tall blue bars, others have no bars
Interpretation: Inconsistent scanning (manual scans only, no schedule)
Action: ⚠️ Consider setting up [scheduled scans](scheduling.md) for regular protection
```

**Pattern 3: Single tall red bar spike (Isolated threat)**

```
One interval has a red bar, others are clean
Interpretation: Threat detected once, possibly from external source (USB, download)
Action: ℹ️ Review [Quarantine](quarantine.md) for that day's threats, investigate source
```

**Pattern 4: Multiple red bars (Persistent threats)**

```
Red bars appear in multiple consecutive intervals
Interpretation: Recurring threat detection, possible active infection
Action: ⚠️ Run full system scan, check if threats are being re-downloaded, review [quarantine](quarantine.md)
```

**Pattern 5: All red bars same height as blue bars (Problematic)**

```
Every scan finds the same number of threats (e.g., blue=1, red=1 every day)
Interpretation: Same threat being detected repeatedly without removal
Action: ⚠️ Check if threat is in an excluded folder, verify quarantine is working, review scan targets
```

**Pattern 6: No data (Empty chart)**

```
Chart shows "No scan data available" message instead of bars
Interpretation: No scans in the selected timeframe (or no scans ever)
Action: ℹ️ Run your first scan or select a different timeframe (e.g., switch from Day to All Time)
```

#### Chart Color Coding

ClamUI uses GNOME/Adwaita color scheme for consistency:

| Element     | Color                  | Meaning                                     |
|-------------|------------------------|---------------------------------------------|
| Blue bars   | `#3584e4` (GNOME Blue) | Scans performed (neutral/positive)          |
| Red bars    | `#e01b24` (GNOME Red)  | Threats detected (warning/attention needed) |
| Text/labels | Adapts to theme        | Black in light mode, white in dark mode     |
| Grid lines  | Light gray             | Background reference lines                  |
| Background  | Transparent            | Matches the application window background   |

💡 **Dark Mode Support**: The chart automatically adapts its text and grid colors when you switch your system to dark
mode, ensuring readability.

#### Chart Empty States

**No scan history at all:**

```
┌─────────────────────────────────────────────────────┐
│ Scan Activity                                       │
│ No scan activity recorded                           │
├─────────────────────────────────────────────────────┤
│                                                     │
│         📊                                          │
│    No scan data available                           │
│  Run some scans to see activity trends here         │
│                                                     │
└─────────────────────────────────────────────────────┘
```

**No scans in selected timeframe:**

Same empty state appears if you select "Day" but haven't scanned today, or "Week" but have only older scans.

**Action**: Switch to a broader timeframe (e.g., All Time) to see your historical data.

#### Chart Limitations

⚠️ **What the chart doesn't show:**

- **Individual scan details**: Use [Logs view](history.md) to see specific scan information
- **Which files were infected**: Check [Quarantine](quarantine.md) for infected file details
- **Scan targets**: Chart shows counts only, not what was scanned
- **Scan duration**: Average duration is in the statistics cards, not visualized
- **Real-time updates**: Chart loads once; click Refresh to update
- **Threat severity**: All threats are counted equally (no distinction between CRITICAL and LOW)

**Chart rendering issues:**

If the chart displays "Unable to render chart" instead of bars:

1. Check that matplotlib is installed correctly
2. Try refreshing the statistics (click the refresh button)
3. Restart ClamUI to reload the chart library
4. See [Troubleshooting](troubleshooting.md) if the issue persists

#### Scrolling in the Statistics View

The chart area is embedded in the scrollable Statistics view. When you scroll:

- **On the chart area**: Scrolling moves the entire Statistics view up/down
- **Chart doesn't zoom**: The chart size is fixed (no pinch-to-zoom)
- **Mobile/touchpad scrolling**: Uses kinetic scrolling (smooth momentum)

💡 **Tip**: If the chart feels too small, consider maximizing the ClamUI window or viewing it in fullscreen.

### Quick Actions

The **Quick Actions** section at the bottom of the Statistics Dashboard provides one-click access to common scanning
operations without navigating to other views.

#### Available Quick Actions

```
┌─────────────────────────────────────────────────────┐
│ Quick Actions                                       │
│ Common scanning operations                          │
├─────────────────────────────────────────────────────┤
│ ▶️  Quick Scan                                   ❯  │
│     Scan your home directory                        │
│                                                     │
│ 📋  View Scan Logs                               ❯  │
│     See detailed scan history                       │
└─────────────────────────────────────────────────────┘
```

**What you see:**

- **Icon**: Visual indicator of the action (▶️ for scan, 📋 for logs)
- **Action title**: What the action does
- **Description**: Brief explanation of the action
- **Chevron (❯)**: Indicates the row is clickable/activatable
- **Hover effect**: Row highlights when you hover over it

#### Quick Scan Action

**What it does:**

- Switches to the **Scan view** and selects the **Quick Scan** profile (your `~/Downloads` folder)
- Does **not** start the scan automatically — review the target, then click **Start Scan**. If the Quick Scan profile is missing, it falls back to your home directory
- Uses your configured scan backend and settings

**When to use it:**

- You want to quickly verify your home folder is clean
- You've just downloaded files and want to scan them
- Your protection status shows "At Risk" or "Unprotected"
- You want to run a scan without manually selecting folders

**How to use it:**

1. Click the **Quick Scan** row (anywhere on the row is clickable)
2. ClamUI **navigates to the Scan view**
3. ClamUI selects the **Quick Scan** profile (`~/Downloads`); click **Start Scan** to begin
4. **Monitor progress** in the Scan view
5. **Return to Statistics** when done to see updated metrics

⚠️ **Note**: Quick Scan uses the **Quick Scan** profile (`~/Downloads`). For different targets or exclusions,
pick another profile or manage them via [Scan Profiles](profiles.md).

💡 **Tip**: Quick Scan is equivalent to:

1. Opening the **Scan** view
2. Selecting the **Quick Scan** profile
3. Clicking **Start Scan**

It just saves you 3 steps!

#### View Scan Logs Action

**What it does:**

- Switches to the **Logs view** (navigates away from Statistics)
- Shows your complete scan history
- Allows you to review past scan results, export logs, etc.

**When to use it:**

- You see threats in the statistics and want to know when they were found
- You want to verify scheduled scans are running
- You need to export scan logs for reporting
- You want detailed information about specific scans

**How to use it:**

1. Click the **View Scan Logs** row
2. ClamUI **navigates to the Logs view** (Historical Logs tab)
3. Review your scan history (see [Scan History](history.md) for details)
4. Click **Statistics** in the navigation bar to return

💡 **Tip**: The Statistics Dashboard and Logs view complement each other:

- **Statistics**: High-level overview and trends (aggregated data)
- **Logs**: Detailed individual scan information (raw data)

#### Quick Actions Workflow Examples

**Example 1: Responding to "At Risk" status**

1. Check Statistics Dashboard
2. See status: **"At Risk - Last scan was over a week ago"**
3. Click **Quick Scan** to immediately scan home directory
4. Scan completes, switch back to Statistics (or it auto-refreshes)
5. Status updates to **"Protected - System is protected"**

**Example 2: Investigating a threat spike**

1. Check Statistics Dashboard
2. See chart shows **red bars** (threats detected)
3. Click **View Scan Logs**
4. Review logs to find when threats were detected
5. See details like file paths, threat names, timestamps
6. Navigate to **Quarantine** to see what was isolated

**Example 3: Verifying scheduled scans**

1. Check Statistics Dashboard daily view
2. See if scans ran today (blue bar in today's chart interval)
3. If no scans visible, click **View Scan Logs**
4. Check if scheduled scan failed or didn't run
5. Review [Scheduled Scans](scheduling.md) to troubleshoot

#### Quick Actions Notes

**What Quick Actions don't do:**

- **Don't perform actions in-place**: They navigate you to another view
- **Don't show confirmation dialogs**: Actions execute immediately
- **Don't interrupt ongoing scans**: If a scan is running, Quick Scan is disabled
- **Don't customize scan targets**: Use Scan view with profiles for custom targets

**Keyboard navigation:**

- Quick Actions rows are **keyboard accessible**
- Press **Tab** to focus on a Quick Action row
- Press **Enter** or **Space** to activate it
- Use **Shift+Tab** to navigate backwards

💡 **Tip**: If you frequently use Quick Actions, consider learning the keyboard shortcuts:

- **Ctrl+Q**: Quit ClamUI (not Quick Scan!)
- **Ctrl+,**: Open Preferences
- For view navigation, use the navigation buttons or click the view name in the header

#### Refreshing Statistics

While not in the Quick Actions section, the **Refresh button** (🔄) in the Protection Status header is another important
quick action:

**How to refresh:**

1. Click the **refresh icon** (🔄) in the top-right of the Protection Status section
2. Statistics **reload automatically** from scan history
3. A **loading spinner** appears while refreshing
4. All sections update: Protection Status, Statistics, and Chart

**When to refresh:**

- After completing a scan
- After quarantining threats
- After updating virus definitions
- When you want to see latest protection status
- If statistics seem outdated

**Auto-refresh:**

- Statistics do **NOT auto-refresh** while the view is open
- You must manually refresh to see updates
- Statistics **reload automatically** when you change timeframes
- Statistics **load automatically** when you first open the Statistics view

💡 **Tip**: Get in the habit of clicking Refresh after important actions (scans, updates, quarantine operations) to
ensure your statistics reflect the latest data.

---

**Summary: Making the Most of the Statistics Dashboard**

✅ **Do:**

- Check your Protection Status regularly (daily or weekly)
- Use timeframe filtering to analyze different periods
- Review the activity chart for patterns and trends
- Investigate red bars (threat spikes) in the chart
- Use Quick Scan for immediate home directory scanning
- Refresh after scans to see updated statistics

⚠️ **Don't:**

- Rely solely on Protection Status - run regular scans
- Ignore "At Risk" or "Unprotected" warnings
- Assume all threats are critical (check severity in Quarantine)
- Expect real-time updates (manual refresh required)
- Use statistics as a replacement for detailed Logs

💡 **Best Practices:**

- **Daily check**: Open Statistics view, verify Protection Status is "Protected"
- **Weekly review**: Switch to Week timeframe, check for consistent scan patterns
- **Monthly analysis**: Switch to Month timeframe, review threat trends
- **After major events**: Refresh statistics after scans, updates, or quarantine operations
- **Combine with Logs**: Use Statistics for overview, Logs for investigation

---

