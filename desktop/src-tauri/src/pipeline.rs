//! Running the Python training pipeline (`vocalkeep` command) from the app.
//!
//! Training needs a graphics card and a large Python environment, so it is a separate install.
//! When the `vocalkeep` command is found, the app can build, try, package and install voices
//! without the person ever opening a terminal. Arguments are always built here from checked
//! values; nothing from the UI reaches a shell.

use std::ffi::OsString;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Arc;
use std::time::Duration;

use anyhow::{anyhow, bail, Context, Result};
use parking_lot::Mutex;
use serde::Serialize;

/// The pipeline command as a program plus leading arguments, e.g. `["python3", "-m", "vocalkeep"]`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PipelineCommand {
    pub program: PathBuf,
    pub prefix: Vec<String>,
}

impl PipelineCommand {
    pub fn display(&self) -> String {
        std::iter::once(self.program.display().to_string())
            .chain(self.prefix.iter().cloned())
            .collect::<Vec<_>>()
            .join(" ")
    }

    fn command(&self, args: &[OsString]) -> Command {
        let mut cmd = Command::new(&self.program);
        cmd.args(&self.prefix).args(args);
        cmd.stdin(Stdio::null());
        // Plain output and UTF-8 everywhere.
        cmd.env("PYTHONIOENCODING", "utf-8").env("NO_COLOR", "1");
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            cmd.creation_flags(CREATE_NO_WINDOW);
        }
        cmd
    }
}

/// Finds the pipeline: the configured command, then `vocalkeep` on PATH, then the places
/// `pipx`, `uv tool` and `pip install --user` put it (apps started from a desktop menu often
/// don't see the shell's PATH).
pub fn resolve(configured: Option<&str>) -> Option<PipelineCommand> {
    if let Some(cfg) = configured {
        let mut parts = split_command(cfg);
        if parts.is_empty() {
            return None;
        }
        let program = PathBuf::from(parts.remove(0));
        return Some(PipelineCommand {
            program,
            prefix: parts,
        });
    }
    let exe = if cfg!(windows) {
        "vocalkeep.exe"
    } else {
        "vocalkeep"
    };
    let mut candidates: Vec<PathBuf> = std::env::var_os("PATH")
        .map(|p| std::env::split_paths(&p).map(|d| d.join(exe)).collect())
        .unwrap_or_default();
    if let Some(home) = dirs::home_dir() {
        candidates.push(home.join(".local").join("bin").join(exe));
        candidates.push(
            home.join(".local")
                .join("share")
                .join("vocalkeep")
                .join("venv")
                .join(if cfg!(windows) { "Scripts" } else { "bin" })
                .join(exe),
        );
    }
    candidates
        .into_iter()
        .find(|p| p.is_file())
        .map(|program| PipelineCommand {
            program,
            prefix: Vec::new(),
        })
}

/// Splits a command line on spaces, honouring double quotes (for paths with spaces).
pub fn split_command(s: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut cur = String::new();
    let mut quoted = false;
    let mut any = false;
    for c in s.chars() {
        match c {
            '"' => {
                quoted = !quoted;
                any = true;
            }
            c if c.is_whitespace() && !quoted => {
                if any || !cur.is_empty() {
                    out.push(std::mem::take(&mut cur));
                    any = false;
                }
            }
            c => cur.push(c),
        }
    }
    if any || !cur.is_empty() {
        out.push(cur);
    }
    out
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PipelineStatus {
    pub found: bool,
    pub command: Option<String>,
    pub version: Option<String>,
    /// `vocalkeep doctor --json`, passed through to the UI.
    pub doctor: Option<serde_json::Value>,
    pub error: Option<String>,
}

pub fn status(cmd: Option<&PipelineCommand>) -> PipelineStatus {
    let Some(cmd) = cmd else {
        return PipelineStatus {
            found: false,
            command: None,
            version: None,
            doctor: None,
            error: None,
        };
    };
    match run_capture(
        cmd,
        &["doctor".into(), "--json".into()],
        Duration::from_secs(60),
    ) {
        Ok(out) => {
            let doctor: Option<serde_json::Value> = serde_json::from_str(out.trim()).ok();
            let version = doctor
                .as_ref()
                .and_then(|d| d.get("version"))
                .and_then(|v| v.as_str())
                .map(str::to_string);
            PipelineStatus {
                found: true,
                command: Some(cmd.display()),
                version,
                doctor,
                error: None,
            }
        }
        Err(e) => PipelineStatus {
            found: false,
            command: Some(cmd.display()),
            version: None,
            doctor: None,
            error: Some(format!("{e:#}")),
        },
    }
}

/// Runs a pipeline command to completion and returns its standard output.
pub fn run_capture(cmd: &PipelineCommand, args: &[OsString], timeout: Duration) -> Result<String> {
    let mut child = cmd
        .command(args)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .with_context(|| format!("could not run {}", cmd.display()))?;
    let stdout = child.stdout.take().expect("piped stdout");
    let stderr = child.stderr.take().expect("piped stderr");
    let out_thread = std::thread::spawn(move || read_all(stdout));
    let err_thread = std::thread::spawn(move || read_all(stderr));
    let started = std::time::Instant::now();
    let status = loop {
        if let Some(status) = child.try_wait()? {
            break status;
        }
        if started.elapsed() > timeout {
            let _ = child.kill();
            let _ = child.wait();
            bail!("{} took too long and was stopped", cmd.display());
        }
        std::thread::sleep(Duration::from_millis(50));
    };
    let out = out_thread.join().unwrap_or_default();
    let err = err_thread.join().unwrap_or_default();
    if !status.success() {
        bail!(
            "{}",
            last_lines(&err, 6).unwrap_or_else(|| format!("exited with {status}"))
        );
    }
    Ok(out)
}

fn read_all(mut r: impl std::io::Read) -> String {
    let mut s = String::new();
    let _ = r.read_to_string(&mut s);
    s
}

fn last_lines(s: &str, n: usize) -> Option<String> {
    let lines: Vec<&str> = s.lines().filter(|l| !l.trim().is_empty()).collect();
    if lines.is_empty() {
        return None;
    }
    Some(lines[lines.len().saturating_sub(n)..].join("\n"))
}

/// A long-running pipeline job (building a voice).
#[derive(Default)]
pub struct Jobs {
    current: Mutex<Option<Arc<Mutex<Child>>>>,
}

impl Jobs {
    pub fn is_running(&self) -> bool {
        self.current.lock().is_some()
    }

    /// Runs `args`, calling `on_event` for every progress event (JSON lines) and log line.
    /// Returns the exit status message on failure.
    pub fn run_streaming(
        &self,
        cmd: &PipelineCommand,
        args: &[OsString],
        on_event: impl Fn(serde_json::Value),
    ) -> Result<()> {
        let mut child = cmd
            .command(args)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .with_context(|| format!("could not run {}", cmd.display()))?;
        let stdout = child.stdout.take().expect("piped stdout");
        let stderr = child.stderr.take().expect("piped stderr");
        let child = Arc::new(Mutex::new(child));
        {
            let mut current = self.current.lock();
            if current.is_some() {
                let _ = child.lock().kill();
                bail!("A voice is already being built.");
            }
            *current = Some(child.clone());
        }
        let err_thread = std::thread::spawn(move || read_all(stderr));
        for line in BufReader::new(stdout).lines() {
            let Ok(line) = line else { break };
            let line = line.trim();
            if line.is_empty() {
                continue;
            }
            match serde_json::from_str::<serde_json::Value>(line) {
                Ok(v) if v.get("event").is_some() => on_event(v),
                _ => on_event(serde_json::json!({ "event": "log", "message": line })),
            }
        }
        let status = child.lock().wait();
        *self.current.lock() = None;
        let err = err_thread.join().unwrap_or_default();
        let status = status?;
        if status.success() {
            Ok(())
        } else {
            Err(anyhow!(
                "{}",
                last_lines(&err, 8).unwrap_or_else(|| format!("stopped ({status})"))
            ))
        }
    }

    pub fn cancel(&self) -> bool {
        if let Some(child) = self.current.lock().as_ref() {
            let _ = child.lock().kill();
            return true;
        }
        false
    }
}

/// Converts paths and strings into command arguments.
pub fn args<I, S>(items: I) -> Vec<OsString>
where
    I: IntoIterator<Item = S>,
    S: Into<OsString>,
{
    items.into_iter().map(Into::into).collect()
}

pub fn path_arg(p: &Path) -> OsString {
    p.as_os_str().to_os_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn splits_commands_with_quotes() {
        assert_eq!(split_command("vocalkeep"), vec!["vocalkeep"]);
        assert_eq!(
            split_command("  python3   -m vocalkeep "),
            vec!["python3", "-m", "vocalkeep"]
        );
        assert_eq!(
            split_command(r#""C:\Program Files\Python\python.exe" -m vocalkeep"#),
            vec![r"C:\Program Files\Python\python.exe", "-m", "vocalkeep"]
        );
        assert!(split_command("   ").is_empty());
    }

    #[test]
    fn configured_command_wins() {
        let cmd = resolve(Some("python3 -m vocalkeep")).unwrap();
        assert_eq!(cmd.program, PathBuf::from("python3"));
        assert_eq!(cmd.prefix, vec!["-m", "vocalkeep"]);
        assert_eq!(cmd.display(), "python3 -m vocalkeep");
    }

    #[cfg(unix)]
    #[test]
    fn captures_output_and_errors() {
        let sh = PipelineCommand {
            program: "sh".into(),
            prefix: vec!["-c".into()],
        };
        let out = run_capture(&sh, &args(["echo hello"]), Duration::from_secs(5)).unwrap();
        assert_eq!(out.trim(), "hello");
        let err = run_capture(
            &sh,
            &args(["echo nope >&2; exit 3"]),
            Duration::from_secs(5),
        )
        .unwrap_err();
        assert_eq!(format!("{err}"), "nope");
    }

    #[cfg(unix)]
    #[test]
    fn streams_json_events_and_logs() {
        let sh = PipelineCommand {
            program: "sh".into(),
            prefix: vec!["-c".into()],
        };
        let jobs = Jobs::default();
        let seen = Mutex::new(Vec::new());
        jobs.run_streaming(
            &sh,
            &args([r#"echo '{"event":"stage","stage":"prepare"}'; echo plain text"#]),
            |v| seen.lock().push(v),
        )
        .unwrap();
        let seen = seen.into_inner();
        assert_eq!(seen[0]["stage"], "prepare");
        assert_eq!(seen[1]["event"], "log");
        assert_eq!(seen[1]["message"], "plain text");
        assert!(!jobs.is_running());
    }
}
