//! gBox Bevy viewer: loads the glTF scenes listed in a scene.json (gBox UAP exports) and shows them.
//!   gbox_viewer <scene.json> [--screenshot out.png] [--live]
//! scene.json: {"assets_root": "...", "items": [{"gltf": "pso_dc_forest01/pso_dc_forest01.gltf",
//!               "translation": [0,0,0], "rotation_y_deg": 0, "scale": 1.0}], "camera": {"eye": [x,y,z], "target": [x,y,z]}}
//! --live keeps the window open and reacts to files next to scene.json, so gBox tools (bevy_scene op=...) can drive it:
//!   <name>.quit  — exists? exit.
//!   <name>.shot  — contains a PNG path: capture a screenshot there, delete the request.
//!   scene.json   — mtime changed? rebuild the whole scene (items + camera).
use bevy::prelude::*;
use bevy::render::view::screenshot::{save_to_disk, Screenshot};
use std::path::PathBuf;
use std::time::SystemTime;

#[derive(Resource)]
struct Shot {
    path: Option<String>,
    frames: u32,
}

#[derive(Resource)]
struct SceneSpec(serde_json::Value);

#[derive(Resource)]
struct Live {
    scene_path: PathBuf,
    mtime: Option<SystemTime>,
    tick: u64,
}

#[derive(Component)]
struct SceneItem;
#[derive(Component)]
struct SceneCam;
#[derive(Component)]
struct SceneLight;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let scene_path = args.get(1).cloned().unwrap_or_else(|| "scene.json".into());
    let shot = args.iter().position(|a| a == "--screenshot").and_then(|i| args.get(i + 1).cloned());
    let scene: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(&scene_path).expect("read scene.json")).expect("parse scene.json");
    let root = scene["assets_root"].as_str().unwrap_or(".").to_string();
    let mtime = std::fs::metadata(&scene_path).and_then(|m| m.modified()).ok();
    App::new()
        .add_plugins(DefaultPlugins.set(AssetPlugin { file_path: root, ..default() }).set(WindowPlugin {
            primary_window: Some(Window { title: "gBox · Bevy".into(), ..default() }),
            ..default()
        }))
        .insert_resource(SceneSpec(scene))
        .insert_resource(Shot { path: shot, frames: 0 })
        .insert_resource(Live { scene_path: PathBuf::from(&scene_path), mtime, tick: 0 })
        .add_systems(Startup, setup)
        .add_systems(Update, screenshot_then_exit)
        .add_systems(Update, live_commands)
        .run();
}

fn v3(v: &serde_json::Value, d: [f32; 3]) -> Vec3 {
    match v.as_array() {
        Some(a) if a.len() == 3 => {
            let f = |i: usize| a[i].as_f64().unwrap_or(0.0) as f32;
            Vec3::new(f(0), f(1), f(2))
        }
        _ => Vec3::from_array(d),
    }
}

fn spawn_scene_inner(commands: &mut Commands, assets: &AssetServer, spec: &serde_json::Value) {
    for item in spec["items"].as_array().cloned().unwrap_or_default() {
        let path = item["gltf"].as_str().unwrap_or_default().to_string();
        let scale = item["scale"].as_f64().unwrap_or(1.0) as f32;
        let rot = (item["rotation_y_deg"].as_f64().unwrap_or(0.0) as f32).to_radians();
        commands.spawn((
            SceneItem,
            WorldAssetRoot(assets.load(GltfAssetLabel::Scene(0).from_asset(path))),
            Transform::from_translation(v3(&item["translation"], [0.0; 3]))
                .with_rotation(Quat::from_rotation_y(rot))
                .with_scale(Vec3::splat(scale)),
        ));
    }
    let eye = v3(&spec["camera"]["eye"], [900.0, 700.0, 900.0]);
    let target = v3(&spec["camera"]["target"], [0.0; 3]);
    commands.spawn((SceneCam, Camera3d::default(), Transform::from_translation(eye).looking_at(target, Vec3::Y)));
    commands.spawn((
        SceneLight,
        DirectionalLight { illuminance: 12_000.0, shadow_maps_enabled: true, ..default() },
        Transform::from_xyz(400.0, 900.0, 300.0).looking_at(Vec3::ZERO, Vec3::Y),
    ));
    commands.insert_resource(GlobalAmbientLight { brightness: 600.0, ..default() });
}

fn setup(mut commands: Commands, assets: Res<AssetServer>, spec: Res<SceneSpec>) {
    spawn_scene_inner(&mut commands, &assets, &spec.0);
}

fn live_commands(
    mut commands: Commands,
    mut spec: ResMut<SceneSpec>,
    mut live: ResMut<Live>,
    assets: Res<AssetServer>,
    items: Query<Entity, With<SceneItem>>,
    cams: Query<Entity, With<SceneCam>>,
    lights: Query<Entity, With<SceneLight>>,
    mut exit: MessageWriter<AppExit>,
) {
    live.tick = live.tick.wrapping_add(1);
    if live.tick % 20 != 0 {
        return;
    }
    let dir = live.scene_path.parent().unwrap_or_else(|| std::path::Path::new(".")).to_path_buf();
    let stem = live.scene_path.file_stem().map(|s| s.to_string_lossy().to_string()).unwrap_or_else(|| "scene".into());
    let quit = dir.join(format!("{stem}.quit"));
    let shot = dir.join(format!("{stem}.shot"));
    if quit.exists() {
        let _ = std::fs::remove_file(&quit);
        exit.write(AppExit::Success);
        return;
    }
    if shot.exists() {
        let target = std::fs::read_to_string(&shot).map(|s| s.trim().to_string()).unwrap_or_default();
        let _ = std::fs::remove_file(&shot);
        if !target.is_empty() {
            commands.spawn(Screenshot::primary_window()).observe(save_to_disk(target));
        }
    }
    let Ok(meta) = std::fs::metadata(&live.scene_path) else { return };
    let Ok(mtime) = meta.modified() else { return };
    if live.mtime != Some(mtime) {
        live.mtime = Some(mtime);
        let Ok(text) = std::fs::read_to_string(&live.scene_path) else { return };
        let Ok(next) = serde_json::from_str::<serde_json::Value>(&text) else { return };
        spec.0 = next;
        for e in items.iter().chain(cams.iter()).chain(lights.iter()) {
            commands.entity(e).despawn();
        }
        let spec_ref = &spec.0;
        spawn_scene_inner(&mut commands, &assets, spec_ref);
    }
}

fn screenshot_then_exit(mut commands: Commands, mut shot: ResMut<Shot>, mut exit: MessageWriter<AppExit>) {
    let Some(path) = shot.path.clone() else { return };
    shot.frames += 1;
    if shot.frames == 240 {
        // ~4 s for assets to load and shaders to compile, then capture
        commands.spawn(Screenshot::primary_window()).observe(save_to_disk(path));
    }
    if shot.frames == 300 {
        exit.write(AppExit::Success);
    }
}
