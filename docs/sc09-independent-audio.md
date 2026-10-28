# SC09 — independent audio checks

Implemented locally on 22 October 2026. No database migration or server contract
change is required: speaker and microphone already have separate result fields.
The candidate executable and VM have not been updated with this change.

## Operator workflow

The Hardware Tests panel has Speaker Test and Microphone Test buttons. As
requested on 28 October 2026, Speaker Test now plays the original sample and
captures microphone input in the same owned worker. The selected input starts
before playback. Sound detection may pass the microphone, while the speaker
always requires a separate operator decision.

If detection fails or input capture is unavailable, the manual microphone dialog
opens after the speaker decision. Its recording controls are immediately
available. The runner stays active until this fallback finishes. Run All commits
both results and does not repeat the microphone test. The separate Microphone
Test button remains available for targeted retests. Each measured component
supersedes its own override history; results remain separately recorded.

Select the intended device explicitly. Output devices are listed by PortAudio
index and name; the microphone test also lists input devices. The first available
entry is initially selected, so confirm the target before starting. Device changes
discard the recording and invalidate listening confirmation.

For speakers, play the original bundled AudioCheck.wav sample and confirm that
it is heard clearly from the selected output. The original stereo channels and
32 kHz sample rate are preserved. For the microphone, Start automatic microphone check first captures four seconds
from the selected input while playing the original sample through the selected
output. Sound passes the microphone automatically when peak amplitude reaches
0.02 or RMS reaches 0.005 (the original thresholds). Background noise is accepted
as sufficient evidence, as explicitly requested on 28 October 2026. This does not
prove that the microphone heard the sample or that speech is intelligible.

If the automatic attempt detects insufficient sound or encounters an error, the
manual recording controls become available. Speak a phrase, replay it through the
chosen output, and confirm that it is intelligible. Manual Pass requires completed
playback and an explicit operator decision. The speaker result always requires
its own listening confirmation; automatic microphone detection never passes it. A microphone can fail while the speaker passes and vice versa.

Playback starts at 100% digital amplitude, adjustable from 1% to 100%, following
the owner's 28 October request. This is not a
calibrated acoustic loudness guarantee. The app never raises Windows volume,
unmutes endpoints, changes microphone gain or changes default devices. Existing
settings therefore stay unchanged on success, failure, cancellation and errors;
there is no system-volume restoration step that can be skipped. Replay attenuates
the recording without normalizing or amplifying background noise.

Each dialog selects the Windows default input and output from the WASAPI host
API at enumeration time. If WASAPI is unavailable, it uses the PortAudio system
defaults. Enumeration and default-index resolution happen together in the owned
worker. A missing default is left unselected so the operator can choose a device;
it does not silently choose the first item. Manual selection remains available.
Changing Windows defaults while a dialog is already open requires reopening it.
These selections do not modify Windows defaults or its master-volume setting.
The original stereo sample and combined microphone/fallback flow are retained.

The full-scale callback regression checks sample fidelity and zero-padding;
default selection checks cover non-first Windows endpoints and missing defaults.
Build output: `SecondChecking Review/audio-defaults-2026-10-28/ready/dist`.

### Default endpoint format compatibility follow-up

The reported `PaErrorCode -9997` came from opening the 32 kHz original sample on
an endpoint that did not accept that rate. Backend aliases can expose the same
physical speakers with different format support; choosing a different alias
worked on the bench machine. The corrected worker checks output format support
before starting playback. It keeps the selected/default endpoint and converts
to its advertised native rate when necessary, preserving pitch, duration and
stereo channels. The original WAV is unchanged. Unsupported native formats
remain an error rather than silently testing another speaker.

Backend names now appear next to device names, distinguishing WASAPI, DirectSound
and MME entries. Rate conversion is logged with source/target rates and channel
count, without recordings or device names. Regression checks cover 32-to-48 kHz
playback on the same endpoint, unsupported native formats, and pitch/duration/
stereo preservation. Build output:
`SecondChecking Review/audio-rate-compatibility-2026-10-28/ready/dist`.

No device is labelled as failed solely because it cannot be opened. Missing
devices disable playback/capture and explain the limitation. Enumeration, stream
and timeout failures are shown as errors with Retry (using the same controls),
Record test error, Unavailable and Cancel options. Unavailable means verification
could not be completed; Fail is an explicit operator hardware decision. Escape,
window close and Cancel record Cancelled. Non-pass results still require an
assignment reason under SC04.

Each operation owns its InputStream or OutputStream; it closes only that stream,
including partial-start failures. Capture and playback are bounded, with a
duration-plus-five-second timeout. Device callbacks handle audio only; Tk polling
updates controls. Closing the dialog cancels polling, aborts/closes the stream and
signals the existing test runner. No global sounddevice.stop() call interrupts
other audio sessions. Successful playback requires the entire expected frame
count and no reported stream warnings.

The old joint speaker/microphone pass and forced maximum Windows levels
have been removed from this workflow. The automatic microphone attempt has been
restored with independent results and a manual fallback. The older volume helper remains unused by
these tests. On 28 October 2026, the original bundled AudioCheck.wav was restored
at the operator's request, replacing the generated tones. A missing or unreadable
sample is a test error and cannot pass playback. This is an operator hearing/intelligibility check, not a
calibrated frequency-response, channel-balance or microphone-quality measurement.
Selected devices are shown during the check; persistent device-level provenance
is not added to the existing report schema by SC09.

## Verification and remaining acceptance

104 desktop unittest tests passed using the Python 3.12 packaging runtime. Four
new tests include real hidden Tk controls with mocked audio boundaries, and
callback-driven backend checks. They cover explicit device selection, attenuation,
bounded capture, noise never deciding a result, independent outcomes, Pass gating,
device changes, missing devices, enumeration errors, timeout, failed start and
cleanup after success/failure/cancel. No sound was played on the host by the tests.

Before release, build the exact candidate and test it in the VM with its matching
server. Confirm Unavailable on a VM without audio endpoints. On physical laptops,
test built-in versus USB/headset devices, a muted output with background noise,
speaker-pass/mic-fail, mic-pass/speaker-fail, unplugging devices during capture and
playback, and cancellation. Compare OS volume, mute, gain and default devices
before/after each exit. Listen at the default and adjustable levels. These physical
checks are pending; SC10 hardware coverage and SC11 Run All cancellation remain
separate items.

Implementation follows the owned-stream and finished-callback API documented in
the [official sounddevice source and API documentation](https://python-sounddevice.readthedocs.io/en/latest/_modules/sounddevice.html).

## Automatic microphone restoration — 28 October 2026

The automatic attempt runs inside the existing owned audio worker. Its capture
and sample playback streams close on success and failure; cancellation terminates
the owned worker. Selecting different devices invalidates playback and requires
a new automatic attempt before manual fallback. OS volume and gain stay unchanged.
Automated checks cover audible input, background noise, silence, failed playback,
stream cleanup, independent results and manual fallback. Physical acoustic quality
remains a bench check.


## Combined speaker/microphone workflow — 28 October 2026

The combined worker continues speaker playback if microphone opening/capture
fails. Missing microphone input cannot prevent the operator checking speakers.
Automatic microphone PASS does not pass the speakers. A speaker failure does not
replace a detected microphone PASS. Cancellation closes the owned worker;
cancelling the manual fallback stops the remaining Run All queue. The runner
commits the staged results together after the combined workflow completes, with
no repeated microphone entry and no late callback changing a newer attempt.

Tests cover sound/silence, input failure, missing input, stream cleanup, manual
fallback handoff, independent decisions, override supersession and Run All queue
handling. No acoustic quality or actual host microphone capture is claimed by
these mocked audio-boundary tests.
