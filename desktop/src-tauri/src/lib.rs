//! Vocalkeep desktop app: the recording studio.

mod commands;
mod pipeline;
mod recorder;
mod settings;
mod voices;

use tauri::Manager;

/// The base voices Vocalkeep knows about, with their licences, for when the voice builder
/// isn't installed yet. The pipeline's `vocalkeep bases --json` is preferred when available.
pub(crate) fn bundled_bases() -> serde_json::Value {
    serde_json::from_str(include_str!(
        "../../../pipeline/src/vocalkeep/data/base_models.json"
    ))
    .unwrap_or(serde_json::Value::Null)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();
    log::info!("Vocalkeep {}", vocalkeep_core::build_info::long_version());

    tauri::Builder::default()
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            let config_dir = app.path().app_config_dir()?;
            let data_dir = app.path().app_data_dir()?;
            std::fs::create_dir_all(&data_dir)?;
            app.manage(commands::AppState::new(config_dir, data_dir));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::app_info,
            commands::get_settings,
            commands::save_settings,
            commands::get_overview,
            commands::create_bank,
            commands::update_speaker,
            commands::list_devices,
            commands::check_room,
            commands::start_session,
            commands::more_prompts,
            commands::end_session,
            commands::start_recording,
            commands::cancel_recording,
            commands::stop_recording,
            commands::keep_take,
            commands::discard_take,
            commands::pending_audio,
            commands::take_audio,
            commands::recent_takes,
            commands::delete_take,
            commands::list_custom_prompts,
            commands::add_custom_prompt,
            commands::remove_custom_prompt,
            commands::list_legacy,
            commands::save_legacy,
            commands::update_legacy,
            commands::delete_legacy,
            commands::legacy_audio,
            commands::export_backup,
            commands::restore_backup,
            commands::export_legacy,
            commands::open_folder,
            commands::pipeline_status,
            commands::list_bases,
            commands::build_voice,
            commands::cancel_build,
            commands::list_voices,
            commands::delete_voice,
            commands::try_voice,
            commands::package_voice,
            commands::install_voice,
            commands::self_test,
        ])
        .run(tauri::generate_context!())
        .expect("error while running Vocalkeep");
}

#[cfg(test)]
mod tests {
    #[test]
    fn bundled_base_voices_parse() {
        let bases = super::bundled_bases();
        let list = bases["bases"].as_array().expect("a list of base voices");
        assert!(list.len() >= 3);
        assert!(list
            .iter()
            .any(|b| b["recommended"] == true && b["commercial"] == "yes"));
    }
}
