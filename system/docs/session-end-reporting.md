# Intentional closes and crash warnings

Closing a game must not be labelled a crash merely because the process returned
1. Generic nonzero exits use neutral wording and retain their exit code in the
session record, without showing it as an error in the popup. Explicit
Stop intent wins over the process termination value. Known Windows exception
statuses (signed or unsigned) and POSIX fatal signals retain crash warnings;
failed relaunches retain their separate error.

The session-ended handler preserves prior stop/replacement metadata. Stop results
can add their saved moment even when the process watcher reported first. A late
raw process report cannot erase that intent, checkpoint or original end time.
Failed/rejected/cancelled stop jobs are not evidence of an intentional stop.
Automatic crash reporting uses the same classification as the reload popup.

The popup refreshes when a late stop confirmation or checkpoint arrives for the
same session. A pre-existing build issue is labelled **Related report**, separate
from the reason the emulator ended. A compatibility path neutralizes the legacy
backend's exact generic-code-1 warning during rolling deployment.

Windows exit values can originate from application exit, process termination or
an unhandled exception: [GetExitCodeProcess](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getexitcodeprocess).
Python represents POSIX signal termination as a negative signal number:
[subprocess returncode](https://docs.python.org/3/library/subprocess.html#subprocess.Popen.returncode).
