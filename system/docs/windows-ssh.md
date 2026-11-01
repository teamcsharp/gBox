# Windows SSH in gBox

On Windows, the desktop app shows a key-icon **Enable SSH** button in the
full window's title bar area (or just below the chat bar in narrower windows).
The button remains visible near the upper right, below the compact controls, in
compact and picture-in-picture views, including the separate mini window. Once
running it reads **SSH: On**; setup, errors and unreachable local service states
have distinct labels. When stopped or missing, clicking **Enable SSH** opens the status panel and
requests Windows setup on this PC. When running or unverified, it opens status
and refreshes without starting setup. The panel includes **Enable SSH on this PC** and the
saved **Enable / start SSH when gBox opens** option. The same controls remain
available in **Settings ? SSH access to this PC**.

These controls always manage the PC running this desktop app, regardless of
which worker's game is displayed. To enable the i9's service, use the updated
app on the i9. Installing this update requires a full app relaunch so its main
process and preload match; an older running app does not gain these APIs from a
page-only refresh. A status-only click does not request elevation. The explicit **Enable SSH**
action can show the normal Windows administrator prompt.

**Enable SSH on this PC** installs the standard Windows OpenSSH Server optional feature if needed,
then starts `sshd`. Windows shows its normal administrator consent/credential
prompt. Cancelling leaves setup unapproved. Installation may need Windows
Update, organizational policy changes, or a later Windows restart; gBox reports
that outcome and never restarts the PC.

**Enable / start SSH when gBox opens** saves immediately in this desktop profile.
It is off by default. When selected, startup reads status and offers elevation
once if the built-in service is stopped or missing. A failed status read or a
custom service never triggers automatic setup. This is an app-start preference,
not a change to Windows boot startup. Closing gBox leaves the service running.
Turning the preference off stops future app-start requests; it does not stop or
uninstall SSH. Windows Services remains available for stopping it.

The gBox firewall rule allows only TCP 22 for the built-in `sshd.exe`, from
`LocalSubnet`, on Private and Domain networks. If installing OpenSSH creates
Windows' default rule, gBox narrows that new rule before starting the service.
Existing operator firewall rules are preserved and can allow additional access.
No Public-profile or unrestricted rule is added. Passwords, accounts, authorized
keys, SSH authentication settings and existing custom server installations are
not changed.

Status distinguishes missing, stopped, custom, running and locally unreachable
service states. “Running” includes a listener owned by `sshd` and a successful
loopback TCP connection to port 22. It does not prove LAN access or a successful
SSH login. Existing servers listening on another port need their existing
administration flow. Setup errors remain visible independently of service state.

Only the owned local desktop or mini window's main frame can invoke these fixed
operations. Guest frames, remote pages and other windows are rejected. There is
no remote API or arbitrary shell-command input. Concurrent setup is serialized;
an uncertain timeout is not retried automatically. Setup uses standard Windows
elevation, following Microsoft's [OpenSSH installation guidance](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_install_firstuse)
and [Start-Process RunAs support](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/start-process?view=powershell-5.1).

Development validation uses mocked service operations, PowerShell syntax parsing,
and read-only status checks. It does not install a feature, start a service, or
change this development machine's firewall. An actual UAC/install/start workflow
still needs operator acceptance on the target PC.

The focused Node suite passed 33 tests (19 SSH tests plus existing desktop
authority/profile tests). The visible launcher, shared panel state, blocked setup states, and both PiP
visibility/interaction contracts are covered by mocked DOM and source checks;
no visual end-to-end browser acceptance is claimed. Both PowerShell scripts parsed successfully without
execution; JavaScript syntax and diff checks passed. A read-only check on the
development PC reported the built-in service installed and stopped, with no gBox
firewall rule. No end-to-end installation, elevation consent, or remote login
success is claimed.
