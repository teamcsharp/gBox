//! gBox Bevy viewer: loads the glTF scenes listed in a scene.json (gBox UAP exports) and shows them.
//!   gbox_viewer <scene.json> [--screenshot out.png]
//! scene.json: {"assets_root": "...", "items": [{"gltf": "pso_dc_forest01/pso_dc_forest01.gltf",
//!               "translation": [0,0,0], "rotation_y_deg": 0, "scale": 1.0}], "camera": {"eye": [x,y,z], "target": [x,y,z]}}
use bevy::prelude::*;
use bevy::render::view::screenshot::{save_to_disk, Screenshot};

#[derive(Resource)]
struct Shot {
    path: Option<String>,
    frames: u32,
}

#[derive(Resource)]
struct SceneSpec(serde_json::Value);

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let scene_path = args.get(1).cloned().unwrap_or_else(|| "scene.json".into());
    let shot = args.iter().position(|a| a == "--screenshot").and_then(|i| args.get(i + 1).cloned());
    let scene: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(&scene_path).expect("read scene.json")).expect("parse scene.json");
    let root = scene["assets_root"].as_str().unwrap_or(".").to_string();
    App::new()
        .add_plugins(DefaultPlugins.set(AssetPlugin { file_path: root, ..default() }).set(WindowPlugin {
            primary_window: Some(Window { title: "gBox · Bevy".into(), ..default() }),
            ..default()
        }))
        .insert_resource(SceneSpec(scene))
        .insert_resource(Shot { path: shot, frames: 0 })
        .add_systems(Startup, setup)
        .add_systems(Update, screenshot_then_exit)
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

fn setup(mut commands: Commands, assets: Res<AssetServer>, spec: Res<SceneSpec>) {
    let s = &spec.0;
    for item in s["items"].as_array().cloned().unwrap_or_default() {
        let path = item["gltf"].as_str().unwrap_or_default().to_string();
        let scale = item["scale"].as_f64().unwrap_or(1.0) as f32;
        let rot = (item["rotation_y_deg"].as_f64().unwrap_or(0.0) as f32).to_radians();
        commands.spawn((
            WorldAssetRoot(assets.load(GltfAssetLabel::Scene(0).from_asset(path))),
            Transform::from_translation(v3(&item["translation"], [0.0; 3]))
                .with_rotation(Quat::from_rotation_y(rot))
                .with_scale(Vec3::splat(scale)),
        ));
    }
    let eye = v3(&s["camera"]["eye"], [900.0, 700.0, 900.0]);
    let target = v3(&s["camera"]["target"], [0.0; 3]);
    commands.spawn((Camera3d::default(), Transform::from_translation(eye).looking_at(target, Vec3::Y)));
    commands.spawn((
        DirectionalLight { illuminance: 12_000.0, shadow_maps_enabled: true, ..default() },
        Transform::from_xyz(400.0, 900.0, 300.0).looking_at(Vec3::ZERO, Vec3::Y),
    ));
    commands.insert_resource(GlobalAmbientLight { brightness: 600.0, ..default() });
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
