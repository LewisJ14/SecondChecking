# Visual refresh — 28 October 2026

The desktop now uses a shared light theme: white surfaces on a quiet slate
background, Astro green primary actions, green passes, amber review states and red
failures. Text labels continue to explain each state independently of colour.
Segoe UI headings, spacing, borders and secondary actions are consistent across
the workspace and test dialogs.

## Changes

- A clearer workspace heading, operator/version identity, quieter measurement
  metadata, and consistent search, refresh and test-menu actions.
- Alternating specification rows and tinted MATCH/REVIEW result cells, with
  clearer column headings: Check, Order requirement, This device and Result.
- Sign-in, hardware-test cards, saved reports, assignment review, serial lists,
  USB and camera dialogs use the same palette and button hierarchy.
- The combined speaker/microphone dialog has a scrolling content area and a
  fixed Pass/Fail/Cancel action row. Instructions wrap to the actual viewport.
- Hardware Tests keeps Run All and Stop tests together above its status line.
- Explicit Tk card/label colours opt out of ttkbootstrap automatic restyling;
  this prevents the theme replacing them with white label rectangles or losing
  the dark test header. Primary-button foreground contrast is covered by a test.
- Existing adaptive initial sizing, flexible details allocation, combined audio
  workflow, recorded-reason policy and portable certificate paths are retained.

Testing also exposed a serial-viewer font lifetime problem: callback cycles
could let a database worker collect a Tk font and deadlock against the UI thread.
The viewer now releases its measured font from its window-destroy handler on
the Tk thread. Serial actions and exact identifiers remain covered by tests.
The VM pass also exposed Windows replacing some initial dialog positions with
its default cascade; the shared centring helper now reapplies the intended
position once after mapping and cancels that pending callback if the window
closes first.

## Visual review and verification

Offline VM fixtures render the actual UI modules with synthetic records and
mocked service/hardware boundaries. Screens cover sign-in, password reset,
workspace, hardware tests, overrides, speaker/microphone, manual microphone,
assigned serials, saved report, assignment review, USB, camera error and keyboard.
They do not authenticate a real account, assign/remove a real serial, capture
host audio/video or run maintenance actions.

The VM currently exposes a single 1280×800 display mode. Captures exercise
100%, 150% and 200% **Tk font scaling**, while the automated layout tests also
exercise simulated 1080p, Surface-size and 4K work areas up to 250%. These results
are not a claim of a new physical mixed-monitor or native 4K VM acceptance run.
Scrollable content is expected on small desktops at large text sizes; primary
decision controls remain outside the scrolling audio content.

The final VM run captured 39 screens (13 per font scale); all recorded client
rectangles stayed within the desktop after the placement correction.

287 tests passed, including theme-colour preservation, responsive geometry,
audio outcomes, assignment review and serial-viewer cleanup. Packaged build
identity, private configuration and read-only database/schema probes passed
from an unrelated working directory. The private config and public MySQL CA
stay outside the repository alongside the executable.

Evidence and synthetic screenshots are under the private local review folder:
`SecondChecking Review/visual-refresh-2026-10-28`. The deliverable is the
`SecondChecking Review/astro-theme-2026-10-28/ready/dist` directory. It is an unsigned review build, with its
source identity and artifact hash recorded by the existing build pipeline.


## Astro / Web-Tools alignment

The 28 October follow-up uses the live Astro palette rather than the earlier
blue styling: brand green #339c6b, dark green #1f7f52, white surfaces, pale grey
#f1f4f8, and the production site's Arial body / Segoe UI heading pairing.
Small filled actions use Astro's darker green to keep white labels readable.
The existing Astro sign-in illustration is reused byte-for-byte as a public
bundled asset. Wide sign-in windows show the green welcome panel alongside the
form; narrow windows hide the decorative panel and retain the scrolling form.
No image is fetched from the network at runtime.

The native app retains its existing workflows and navigation. This matches the
Astro light design within native Tk controls; browser CSS gradients, rounded
containers and the website's multi-section sidebar are not replicated as web
widgets. Theme colours are a deployment snapshot, independent of server uptime.

Switching to Arial exposed a pre-map test-row wrapping feedback loop at 150%.
Rows now wrap against the allocated canvas viewport after it has a real width,
rather than changing their own requested width repeatedly before mapping.

The alignment build and review evidence are stored outside Git under
`SecondChecking Review/astro-theme-2026-10-28`.

### Live charge label follow-up

The reported current-charge clipping came from centring DPI-scaled text over
a fixed 340-by-18-pixel bar. The charge label now wraps above the progress
track, using the actual available width and measured text bounds to set its
height. Redraws clear the previous items without re-entering Tk layout.
A real Tk regression covers 100%, 150%, 200% and 250% text scaling at
220-, 340- and 800-pixel widths, including changing charge/status labels.
The replacement build is under
`SecondChecking Review/battery-layout-2026-10-28/ready-final/dist`.
The responsive regression also now measures visible keyboard keys before and
after enabling the optional numpad; hidden controls have no allocated width.

### Battery cycle counts

Battery health cells now retain the cycle count immediately after the health
percentage, for example `31.1% (120 cycles)`. Windows BatteryCycleCount records
are joined by case-insensitive InstanceName, never by enumeration position.
The fallback BatteryInfoView CSV parser preserves the cycle column for each
pack in horizontal and vertical exports. Evidence and saved battery reports
retain the captured counts. The live current-charge progress bar is separate.

Missing, duplicate, invalid and sentinel counts display `cycles unavailable`;
an unavailable cycle provider does not discard valid health measurements.
Windows documents zero as an unsupported counter, so it is not presented as
a measured zero: https://learn.microsoft.com/en-us/windows/win32/api/batclass/ns-batclass-battery_wmi_cycle_count
Health comparison thresholds are unchanged. Regression coverage includes
reversed two-pack records, absent counts, CSV alignment and actual Tk table
text/status. This build is under
`SecondChecking Review/battery-cycles-2026-10-28/ready/dist`.
