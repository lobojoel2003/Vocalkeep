# Security policy

Vocalkeep handles something irreplaceable: recordings of a person's voice. Please report any
problem that could expose, corrupt or delete those recordings, or let someone else's files be
read or written, **privately**:

- use [GitHub's private vulnerability reporting](https://github.com/lobojoel2003/Vocalkeep/security/advisories/new), or
- open an issue that says only "security report, please contact me" and we will reach out.

Please include the version and build (Settings › About), your operating system, and steps to
reproduce. We aim to reply within a week and to fix serious issues in a patch release.

## Supported versions

The latest release receives fixes. Older releases do not.

## What Vocalkeep does to stay safe

- The app has no network code. Recordings never leave the computer unless you export them.
- `bank.json` is saved atomically with a recovery copy; paths inside a voice bank, backups and
  voice packages are checked so nothing can be written outside the intended folder.
- The app's web view runs with a strict content security policy and only the permissions it needs.
- The voice builder is run with arguments built from checked values, never through a shell.
