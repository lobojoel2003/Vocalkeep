//! Commands the interface calls. Every command returns a plain-language error string on failure.

use std::collections::HashMap;
use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::time::Duration;

use anyhow::anyhow;
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use tauri::ipc::Response;
use tauri::{AppHandle, Emitter, Manager, State};
use vocalkeep_core::audio::write_wav;
use vocalkeep_core::bank::{Bank, LegacyDetails, LegacyMessage, Speaker};
use vocalkeep_core::export::{self, ExportSummary};
use vocalkeep_core::progress::{self, Milestone, Progress, MILESTONES};
use vocalkeep_core::prompts::{self, CustomPrompt, Energy, PromptSetInfo, QueuedPrompt};
use vocalkeep_core::quality::{self, Analysis, IssueCode, RoomCheck, Verdict};
use vocalkeep_core::{build_info, synth};

use crate::pipeline::{self, Jobs};
use crate::recorder::{self, InputDevice, Recorder, STOP_TAIL};
use crate::settings::{self, SessionLength, Settings};
use crate::voices::{self, VoiceInfo};

type CmdResult<T> = Result<T, String>;

fn err(e: anyhow::Error) -> String {
    format!("{e:#}")
}

/// A take waiting for the person to keep or discard it.
struct Pending {
    path: PathBuf,
    analysis: Analysis,
}

pub struct AppState {
    pub config_dir: PathBuf,
    pub data_dir: PathBuf,
    pub settings: Mutex<Settings>,
    pub bank: Mutex<Option<Bank>>,
    pub recorder: Recorder,
    pending: Mutex<HashMap<String, Pending>>,
    pub jobs: Jobs,
}

impl AppState {
    pub fn new(config_dir: PathBuf, data_dir: PathBuf) -> Self {
        let settings = settings::load(&config_dir);
        let state = Self {
            config_dir,
            data_dir,
            settings: Mutex::new(settings),
            bank: Mutex::new(None),
            recorder: Recorder::default(),
            pending: Mutex::new(HashMap::new()),
            jobs: Jobs::default(),
        };
        let root = state.bank_dir();
        if root.join(vocalkeep_core::bank::MANIFEST).exists() {
            match Bank::open(&root) {
                Ok(bank) => {
                    let _ = bank.clear_pending();
                    *state.bank.lock() = Some(bank);
                }
                Err(e) => log::error!("could not open the voice bank: {e:#}"),
            }
        }
        state
    }

    pub fn bank_dir(&self) -> PathBuf {
        self.settings
            .lock()
            .bank_dir
            .as_ref()
            .map(PathBuf::from)
            .unwrap_or_else(|| self.data_dir.join("voice-bank"))
    }

    pub fn voices_dir(&self) -> PathBuf {
        self.data_dir.join("voices")
    }

    fn work_dir(&self) -> PathBuf {
        self.data_dir.join("work")
    }

    fn with_bank<T>(&self, f: impl FnOnce(&mut Bank) -> anyhow::Result<T>) -> CmdResult<T> {
        let mut guard = self.bank.lock();
        let bank = guard
            .as_mut()
            .ok_or_else(|| "Set up your voice bank first.".to_string())?;
        f(bank).map_err(err)
    }

    fn pipeline(&self) -> Option<pipeline::PipelineCommand> {
        pipeline::resolve(self.settings.lock().pipeline_command.as_deref())
    }
}

/// Runs blocking work off the main thread.
async fn blocking<T: Send + 'static>(
    app: &AppHandle,
    f: impl FnOnce(&AppState) -> CmdResult<T> + Send + 'static,
) -> CmdResult<T> {
    let app = app.clone();
    tauri::async_runtime::spawn_blocking(move || f(&app.state::<AppState>()))
        .await
        .map_err(|e| format!("internal error: {e}"))?
}

// ----- App and settings -----

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AppInfo {
    #[serde(flatten)]
    build: build_info::BuildInfo,
    platform: &'static str,
    data_dir: String,
    bank_dir: String,
    voices_dir: String,
}

#[tauri::command]
pub fn app_info(state: State<'_, AppState>) -> AppInfo {
    AppInfo {
        build: build_info::build_info(),
        platform: std::env::consts::OS,
        data_dir: state.data_dir.display().to_string(),
        bank_dir: state.bank_dir().display().to_string(),
        voices_dir: state.voices_dir().display().to_string(),
    }
}

#[tauri::command]
pub fn get_settings(state: State<'_, AppState>) -> Settings {
    state.settings.lock().clone()
}

#[tauri::command]
pub fn save_settings(state: State<'_, AppState>, settings: Settings) -> CmdResult<Settings> {
    let settings = settings.sanitized();
    let moved = state.settings.lock().bank_dir != settings.bank_dir;
    settings::save(&state.config_dir, &settings).map_err(err)?;
    *state.settings.lock() = settings.clone();
    if moved {
        // A different bank folder was chosen: open it if it holds a bank.
        let root = state.bank_dir();
        *state.bank.lock() = if root.join(vocalkeep_core::bank::MANIFEST).exists() {
            Some(Bank::open(&root).map_err(err)?)
        } else {
            None
        };
    }
    Ok(settings)
}

// ----- Voice bank overview -----

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BankSummary {
    id: String,
    speaker: Speaker,
    room: Option<RoomCheck>,
    created_at: String,
    path: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Overview {
    bank: Option<BankSummary>,
    progress: Option<Progress>,
    sets: Vec<PromptSetInfo>,
    milestones: &'static [Milestone],
}

fn overview_of(state: &AppState) -> Overview {
    let guard = state.bank.lock();
    Overview {
        bank: guard.as_ref().map(|b| BankSummary {
            id: b.manifest.id.clone(),
            speaker: b.manifest.speaker.clone(),
            room: b.manifest.room.clone(),
            created_at: b.manifest.created_at.clone(),
            path: b.root().display().to_string(),
        }),
        progress: guard
            .as_ref()
            .map(|b| progress::progress(&b.manifest, prompts::library())),
        sets: prompts::library().infos(),
        milestones: MILESTONES,
    }
}

#[tauri::command]
pub fn get_overview(state: State<'_, AppState>) -> Overview {
    overview_of(&state)
}

#[tauri::command]
pub fn create_bank(state: State<'_, AppState>, speaker: Speaker) -> CmdResult<Overview> {
    let root = state.bank_dir();
    let bank = Bank::open_or_create(&root, clean_speaker(speaker.clone())?).map_err(err)?;
    let mut bank = bank;
    bank.manifest.speaker = clean_speaker(speaker)?;
    bank.save().map_err(err)?;
    *state.bank.lock() = Some(bank);
    Ok(overview_of(&state))
}

#[tauri::command]
pub fn update_speaker(state: State<'_, AppState>, speaker: Speaker) -> CmdResult<Overview> {
    let speaker = clean_speaker(speaker)?;
    state.with_bank(|b| {
        b.manifest.speaker = speaker;
        b.save()
    })?;
    Ok(overview_of(&state))
}

fn clean_speaker(mut s: Speaker) -> CmdResult<Speaker> {
    s.name = s.name.split_whitespace().collect::<Vec<_>>().join(" ");
    if s.name.chars().count() > 80 {
        return Err("Names can be up to 80 characters.".into());
    }
    let lang = s.language.trim();
    let valid = !lang.is_empty()
        && lang.len() <= 20
        && lang.chars().all(|c| c.is_ascii_alphanumeric() || c == '-');
    s.language = if valid { lang.into() } else { "en-US".into() };
    s.gender = s
        .gender
        .filter(|g| matches!(g.as_str(), "female" | "male" | "neutral"));
    Ok(s)
}

// ----- Microphone -----

#[tauri::command]
pub async fn list_devices(app: AppHandle) -> CmdResult<Vec<InputDevice>> {
    blocking(&app, |_| recorder::list_devices().map_err(err)).await
}

fn emit_levels(app: &AppHandle) -> impl Fn(recorder::Level) + Send + 'static {
    let app = app.clone();
    move |level| {
        let _ = app.emit("level", level);
    }
}

#[tauri::command]
pub async fn check_room(app: AppHandle) -> CmdResult<RoomCheck> {
    let on_level = emit_levels(&app);
    blocking(&app, move |state| {
        let device = state.settings.lock().input_device.clone();
        let seconds = quality::config().room.seconds;
        state
            .recorder
            .start(device.as_deref(), seconds + 2, on_level)
            .map_err(err)?;
        std::thread::sleep(Duration::from_secs(seconds as u64));
        let clip = state.recorder.stop(Duration::ZERO).map_err(err)?;
        // Skip the first half second: the click of starting and settling.
        let skip = clip.samples_for_ms(500).min(clip.samples.len());
        let clip =
            vocalkeep_core::audio::Clip::new(clip.sample_rate, clip.samples[skip..].to_vec());
        let room = quality::analyze_room(&clip, quality::config());
        state.with_bank(|b| {
            b.manifest.room = Some(room.clone());
            b.save()
        })?;
        Ok(room)
    })
    .await
}

// ----- Sessions -----

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SessionStart {
    session_id: String,
    energy: Energy,
    length: SessionLength,
    break_every: u32,
    prompts: Vec<QueuedPrompt>,
}

fn queue(
    state: &AppState,
    bank: &Bank,
    energy: Energy,
    count: usize,
    exclude: &[String],
) -> Vec<QueuedPrompt> {
    let mut done = bank.done_ids();
    done.extend(exclude.iter().cloned());
    let enabled = state.settings.lock().enabled_sets.clone();
    prompts::next_prompts(
        prompts::library(),
        &bank.manifest.custom_prompts,
        &done,
        &enabled,
        energy,
        count,
    )
}

#[tauri::command]
pub fn start_session(state: State<'_, AppState>, energy: Energy) -> CmdResult<SessionStart> {
    let (length, break_every) = {
        let s = state.settings.lock();
        (s.sessions.for_energy(energy).clone(), s.break_every)
    };
    let mut guard = state.bank.lock();
    let bank = guard.as_mut().ok_or("Set up your voice bank first.")?;
    let session_id = bank.start_session(energy);
    bank.save().map_err(err)?;
    let prompts = queue(&state, bank, energy, length.prompts as usize, &[]);
    Ok(SessionStart {
        session_id,
        energy,
        length,
        break_every,
        prompts,
    })
}

#[tauri::command]
pub fn more_prompts(
    state: State<'_, AppState>,
    energy: Energy,
    count: usize,
    exclude: Vec<String>,
) -> CmdResult<Vec<QueuedPrompt>> {
    let guard = state.bank.lock();
    let bank = guard.as_ref().ok_or("Set up your voice bank first.")?;
    Ok(queue(&state, bank, energy, count.min(100), &exclude))
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SessionEnd {
    kept: u32,
    retried: u32,
    speech_minutes: f32,
    progress: Progress,
}

#[tauri::command]
pub fn end_session(state: State<'_, AppState>, session_id: String) -> CmdResult<SessionEnd> {
    state.with_bank(|b| {
        let (kept, retried, speech_ms) = b
            .manifest
            .sessions
            .iter()
            .find(|s| s.id == session_id)
            .map(|s| (s.kept, s.retried, s.speech_ms))
            .unwrap_or_default();
        b.end_session(&session_id);
        b.save()?;
        Ok(SessionEnd {
            kept,
            retried,
            speech_minutes: speech_ms as f32 / 60_000.0,
            progress: progress::progress(&b.manifest, prompts::library()),
        })
    })
}

// ----- Recording -----

#[derive(Debug, Clone, Copy, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum RecordingKind {
    Take,
    Legacy,
}

impl RecordingKind {
    fn max_seconds(self) -> u32 {
        match self {
            RecordingKind::Take => 60,
            RecordingKind::Legacy => 15 * 60,
        }
    }
}

/// Opens the microphone. Runs off the main thread so the window stays responsive while the
/// device starts.
#[tauri::command]
pub async fn start_recording(app: AppHandle, kind: RecordingKind) -> CmdResult<u32> {
    let on_level = emit_levels(&app);
    blocking(&app, move |state| {
        if state.bank.lock().is_none() {
            return Err("Set up your voice bank first.".into());
        }
        let device = state.settings.lock().input_device.clone();
        state
            .recorder
            .start(device.as_deref(), kind.max_seconds(), on_level)
            .map_err(err)
    })
    .await
}

/// Stops a recording without keeping it. Returns whether anything was being recorded.
#[tauri::command]
pub async fn cancel_recording(app: AppHandle) -> CmdResult<bool> {
    blocking(&app, |state| {
        let was_recording = state.recorder.is_recording();
        state.recorder.cancel();
        Ok(was_recording)
    })
    .await
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PendingTake {
    token: String,
    analysis: Analysis,
    duration_ms: u32,
}

#[tauri::command]
pub async fn stop_recording(
    app: AppHandle,
    kind: RecordingKind,
    text: Option<String>,
) -> CmdResult<PendingTake> {
    blocking(&app, move |state| {
        let clip = state.recorder.stop(STOP_TAIL).map_err(err)?;
        let analysis = match kind {
            RecordingKind::Take => quality::analyze(&clip, text.as_deref(), quality::config()),
            // Messages are kept as said: only problems that spoil listening are flagged.
            RecordingKind::Legacy => legacy_analysis(&clip),
        };
        let token = uuid::Uuid::new_v4().to_string();
        let path = state.with_bank(|b| b.pending_path(&token))?;
        write_wav(&path, &clip).map_err(err)?;
        let duration_ms = clip.duration_ms();
        state.pending.lock().insert(
            token.clone(),
            Pending {
                path,
                analysis: analysis.clone(),
            },
        );
        Ok(PendingTake {
            token,
            analysis,
            duration_ms,
        })
    })
    .await
}

fn legacy_analysis(clip: &vocalkeep_core::audio::Clip) -> Analysis {
    let mut a = quality::analyze(clip, None, quality::config());
    a.issues.retain(|i| {
        matches!(
            i.code,
            IssueCode::NoSpeech | IssueCode::Clipping | IssueCode::TooQuiet | IssueCode::Noisy
        )
    });
    a.verdict = quality::verdict_for(&a.issues);
    a
}

fn take_pending(state: &AppState, token: &str) -> CmdResult<Pending> {
    state
        .pending
        .lock()
        .remove(token)
        .ok_or_else(|| "That recording is no longer available. Please record it again.".into())
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TakeSummary {
    prompt_id: String,
    set_id: String,
    text: String,
    verdict: Verdict,
    issues: Vec<IssueCode>,
    recorded_at: String,
    duration_ms: u32,
    attempts: u32,
}

impl From<&vocalkeep_core::bank::Take> for TakeSummary {
    fn from(t: &vocalkeep_core::bank::Take) -> Self {
        Self {
            prompt_id: t.prompt_id.clone(),
            set_id: t.set_id.clone(),
            text: t.text.clone(),
            verdict: t.quality.verdict,
            issues: t.quality.issues.iter().map(|i| i.code).collect(),
            recorded_at: t.recorded_at.clone(),
            duration_ms: t.duration_ms,
            attempts: t.attempts,
        }
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct KeepResult {
    take: TakeSummary,
    progress: Progress,
}

#[tauri::command]
pub fn keep_take(
    state: State<'_, AppState>,
    token: String,
    prompt_id: String,
    session_id: Option<String>,
) -> CmdResult<KeepResult> {
    let pending = take_pending(&state, &token)?;
    state.with_bank(|b| {
        let prompt = b
            .prompt_ref(&prompt_id)
            .ok_or_else(|| anyhow!("That sentence is no longer in the list."))?;
        let take = b.keep_take_file(
            &prompt,
            &pending.path,
            pending.analysis,
            session_id.as_deref(),
        )?;
        b.save()?;
        Ok(KeepResult {
            take: TakeSummary::from(&take),
            progress: progress::progress(&b.manifest, prompts::library()),
        })
    })
}

#[tauri::command]
pub fn discard_take(
    state: State<'_, AppState>,
    token: String,
    session_id: Option<String>,
    retry: bool,
) -> CmdResult<()> {
    if let Some(p) = state.pending.lock().remove(&token) {
        let _ = std::fs::remove_file(&p.path);
    }
    if retry {
        if let Some(id) = session_id {
            state.with_bank(|b| {
                b.note_retry(&id);
                Ok(())
            })?;
        }
    }
    Ok(())
}

fn wav_response(path: &Path) -> CmdResult<Response> {
    std::fs::read(path)
        .map(Response::new)
        .map_err(|_| "That recording could not be found.".to_string())
}

#[tauri::command]
pub fn pending_audio(state: State<'_, AppState>, token: String) -> CmdResult<Response> {
    let path = state
        .pending
        .lock()
        .get(&token)
        .map(|p| p.path.clone())
        .ok_or("That recording is no longer available.")?;
    wav_response(&path)
}

#[tauri::command]
pub fn take_audio(state: State<'_, AppState>, prompt_id: String) -> CmdResult<Response> {
    let path = state.with_bank(|b| {
        let t = b
            .take(&prompt_id)
            .ok_or_else(|| anyhow!("No recording of that sentence yet."))?;
        b.resolve(&t.file)
    })?;
    wav_response(&path)
}

#[tauri::command]
pub fn recent_takes(state: State<'_, AppState>, limit: usize) -> CmdResult<Vec<TakeSummary>> {
    state.with_bank(|b| {
        let mut takes: Vec<_> = b.manifest.takes.iter().collect();
        takes.sort_by(|a, b| b.recorded_at.cmp(&a.recorded_at));
        Ok(takes
            .into_iter()
            .take(limit.min(500))
            .map(TakeSummary::from)
            .collect())
    })
}

#[tauri::command]
pub fn delete_take(state: State<'_, AppState>, prompt_id: String) -> CmdResult<Progress> {
    state.with_bank(|b| {
        b.remove_take(&prompt_id)?;
        b.save()?;
        Ok(progress::progress(&b.manifest, prompts::library()))
    })
}

// ----- The person's own phrases -----

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CustomPromptInfo {
    #[serde(flatten)]
    prompt: CustomPrompt,
    recorded: bool,
}

#[tauri::command]
pub fn list_custom_prompts(state: State<'_, AppState>) -> CmdResult<Vec<CustomPromptInfo>> {
    state.with_bank(|b| {
        let done = b.done_ids();
        Ok(b.manifest
            .custom_prompts
            .iter()
            .map(|p| CustomPromptInfo {
                recorded: done.contains(&p.id),
                prompt: p.clone(),
            })
            .collect())
    })
}

#[tauri::command]
pub fn add_custom_prompt(state: State<'_, AppState>, text: String) -> CmdResult<CustomPrompt> {
    state.with_bank(|b| {
        let p = b.add_custom_prompt(&text)?;
        b.save()?;
        Ok(p)
    })
}

#[tauri::command]
pub fn remove_custom_prompt(state: State<'_, AppState>, id: String) -> CmdResult<()> {
    state.with_bank(|b| {
        b.remove_custom_prompt(&id)?;
        b.save()
    })
}

// ----- Legacy messages -----

#[tauri::command]
pub fn list_legacy(state: State<'_, AppState>) -> CmdResult<Vec<LegacyMessage>> {
    state.with_bank(|b| {
        let mut list = b.manifest.legacy.clone();
        list.sort_by(|a, b| b.recorded_at.cmp(&a.recorded_at));
        Ok(list)
    })
}

#[tauri::command]
pub fn save_legacy(
    state: State<'_, AppState>,
    token: String,
    details: LegacyDetails,
) -> CmdResult<LegacyMessage> {
    let pending = take_pending(&state, &token)?;
    state.with_bank(|b| {
        let m = b.add_legacy_file(details, &pending.path, Some(pending.analysis))?;
        b.save()?;
        Ok(m)
    })
}

#[tauri::command]
pub fn update_legacy(
    state: State<'_, AppState>,
    id: String,
    details: LegacyDetails,
) -> CmdResult<LegacyMessage> {
    state.with_bank(|b| {
        let m = b.update_legacy(&id, details)?;
        b.save()?;
        Ok(m)
    })
}

#[tauri::command]
pub fn delete_legacy(state: State<'_, AppState>, id: String) -> CmdResult<()> {
    state.with_bank(|b| {
        b.remove_legacy(&id)?;
        b.save()
    })
}

#[tauri::command]
pub fn legacy_audio(state: State<'_, AppState>, id: String) -> CmdResult<Response> {
    let path = state.with_bank(|b| {
        let m = b
            .legacy(&id)
            .ok_or_else(|| anyhow!("That message no longer exists."))?;
        b.resolve(&m.file)
    })?;
    wav_response(&path)
}

// ----- Backups -----

#[tauri::command]
pub async fn export_backup(app: AppHandle, path: String) -> CmdResult<ExportSummary> {
    blocking(&app, move |state| {
        state.with_bank(|b| {
            b.save()?;
            export::backup_zip(b, Path::new(&path))
        })
    })
    .await
}

#[tauri::command]
pub async fn restore_backup(app: AppHandle, path: String) -> CmdResult<Overview> {
    blocking(&app, move |state| {
        let root = state.bank_dir();
        if root.join(vocalkeep_core::bank::MANIFEST).exists() {
            return Err(
                "There is already a voice bank here. To restore a backup, first choose \
                        an empty folder for the voice bank in Settings."
                    .into(),
            );
        }
        let bank = export::restore_zip(Path::new(&path), &root).map_err(err)?;
        *state.bank.lock() = Some(bank);
        Ok(overview_of(state))
    })
    .await
}

#[tauri::command]
pub async fn export_legacy(app: AppHandle, dir: String) -> CmdResult<ExportSummary> {
    blocking(&app, move |state| {
        state.with_bank(|b| export::export_legacy(b, Path::new(&dir)))
    })
    .await
}

#[tauri::command]
pub fn open_folder(app: AppHandle, state: State<'_, AppState>, which: String) -> CmdResult<()> {
    use tauri_plugin_opener::OpenerExt;
    let path = match which.as_str() {
        "bank" => state.bank_dir(),
        "voices" => state.voices_dir(),
        "data" => state.data_dir.clone(),
        _ => return Err("Unknown folder.".into()),
    };
    std::fs::create_dir_all(&path).map_err(|e| e.to_string())?;
    app.opener()
        .open_path(path.display().to_string(), None::<&str>)
        .map_err(|e| e.to_string())
}

// ----- The voice pipeline -----

#[tauri::command]
pub async fn pipeline_status(app: AppHandle) -> CmdResult<pipeline::PipelineStatus> {
    blocking(&app, |state| {
        Ok(pipeline::status(state.pipeline().as_ref()))
    })
    .await
}

#[tauri::command]
pub async fn list_bases(app: AppHandle) -> CmdResult<serde_json::Value> {
    blocking(&app, |state| {
        if let Some(cmd) = state.pipeline() {
            if let Ok(out) = pipeline::run_capture(
                &cmd,
                &pipeline::args(["bases", "--json"]),
                Duration::from_secs(60),
            ) {
                if let Ok(v) = serde_json::from_str(out.trim()) {
                    return Ok(v);
                }
            }
        }
        Ok(crate::bundled_bases())
    })
    .await
}

fn valid_base(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 80
        && id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
}

#[tauri::command]
pub async fn build_voice(app: AppHandle, base: String, quick: bool) -> CmdResult<()> {
    if !valid_base(&base) {
        return Err("Choose a starting voice first.".into());
    }
    let app2 = app.clone();
    blocking(&app, move |state| {
        let cmd = state.pipeline().ok_or(
            "The voice builder isn't installed on this computer yet. See \"Build on this \
             computer\" for how to install it.",
        )?;
        if state.jobs.is_running() {
            return Err("A voice is already being built.".into());
        }
        let bank_dir = state.bank_dir();
        state.with_bank(|b| b.save())?;
        let mut args: Vec<OsString> = pipeline::args(["build"]);
        args.push(pipeline::path_arg(&bank_dir));
        args.extend(pipeline::args(["--base", base.as_str(), "-o"]));
        args.push(pipeline::path_arg(&state.voices_dir()));
        args.extend(pipeline::args(["--work"]));
        args.push(pipeline::path_arg(&state.work_dir()));
        args.extend(pipeline::args(["--progress", "json"]));
        if quick {
            args.push("--quick".into());
        }
        let result = state.jobs.run_streaming(&cmd, &args, |event| {
            let _ = app2.emit("pipeline", event);
        });
        if let Err(e) = &result {
            let _ = app2.emit(
                "pipeline",
                serde_json::json!({ "event": "error", "message": format!("{e:#}") }),
            );
        }
        result.map_err(err)
    })
    .await
}

#[tauri::command]
pub fn cancel_build(state: State<'_, AppState>) -> bool {
    state.jobs.cancel()
}

#[tauri::command]
pub fn list_voices(state: State<'_, AppState>) -> Vec<VoiceInfo> {
    voices::list(&state.voices_dir())
}

#[tauri::command]
pub fn delete_voice(state: State<'_, AppState>, id: String) -> CmdResult<()> {
    voices::delete(&state.voices_dir(), &id).map_err(err)
}

#[tauri::command]
pub async fn try_voice(app: AppHandle, id: String, text: String) -> CmdResult<Response> {
    let text: String = text.chars().take(500).collect();
    if text.trim().is_empty() {
        return Err("Type something for your voice to say.".into());
    }
    blocking(&app, move |state| {
        let cmd = state
            .pipeline()
            .ok_or("The voice builder isn't installed.")?;
        let folder = voices::folder(&state.voices_dir(), &id).map_err(err)?;
        let out = std::env::temp_dir().join(format!("vocalkeep-try-{}.wav", uuid::Uuid::new_v4()));
        let mut args: Vec<OsString> = pipeline::args(["speak"]);
        args.push(pipeline::path_arg(&folder));
        args.push(text.into());
        args.push("-o".into());
        args.push(pipeline::path_arg(&out));
        pipeline::run_capture(&cmd, &args, Duration::from_secs(120)).map_err(err)?;
        let bytes = std::fs::read(&out).map_err(|e| e.to_string());
        let _ = std::fs::remove_file(&out);
        bytes.map(Response::new)
    })
    .await
}

const PACKAGE_FORMATS: &[&str] = &[
    "piper",
    "nvda",
    "sherpa",
    "saywell",
    "sherpatts",
    "voicegarden",
    "all",
];

#[tauri::command]
pub async fn package_voice(
    app: AppHandle,
    id: String,
    format: String,
    dir: String,
) -> CmdResult<Vec<String>> {
    if !PACKAGE_FORMATS.contains(&format.as_str()) {
        return Err("Unknown format.".into());
    }
    blocking(&app, move |state| {
        let cmd = state
            .pipeline()
            .ok_or("The voice builder isn't installed.")?;
        let folder = voices::folder(&state.voices_dir(), &id).map_err(err)?;
        let mut args: Vec<OsString> = pipeline::args(["package"]);
        args.push(pipeline::path_arg(&folder));
        args.extend(pipeline::args([
            "--format",
            format.as_str(),
            "--json",
            "-o",
        ]));
        args.push(dir.into());
        let out = pipeline::run_capture(&cmd, &args, Duration::from_secs(600)).map_err(err)?;
        let files: Vec<String> = serde_json::from_str(out.trim())
            .or_else(|_| {
                Ok::<_, String>(
                    out.lines()
                        .map(str::trim)
                        .filter(|l| !l.is_empty())
                        .map(str::to_string)
                        .collect(),
                )
            })
            .map_err(|e| e.to_string())?;
        Ok(files)
    })
    .await
}

#[tauri::command]
pub async fn install_voice(app: AppHandle, id: String, target: String) -> CmdResult<String> {
    let target = match target.as_str() {
        "linux" | "windows" => target,
        _ => return Err("Vocalkeep can install voices on Linux and Windows.".into()),
    };
    blocking(&app, move |state| {
        let cmd = state
            .pipeline()
            .ok_or("The voice builder isn't installed.")?;
        let folder = voices::folder(&state.voices_dir(), &id).map_err(err)?;
        let mut args: Vec<OsString> = pipeline::args(["install"]);
        args.push(pipeline::path_arg(&folder));
        args.extend(pipeline::args(["--target", target.as_str()]));
        pipeline::run_capture(&cmd, &args, Duration::from_secs(300)).map_err(err)
    })
    .await
}

// ----- Self-test -----

/// Plays a short test tone through the analysis path, so "Check the room" can be demonstrated
/// and the quality checker verified without a microphone.
#[tauri::command]
pub fn self_test() -> CmdResult<Analysis> {
    let clip = synth::take(48_000, synth::Take::default());
    let a = quality::analyze(&clip, Some("This is a test sentence."), quality::config());
    if a.verdict != Verdict::Good {
        return Err(format!(
            "The quality checker failed its self-test: {:?}",
            a.issues
        ));
    }
    Ok(a)
}
