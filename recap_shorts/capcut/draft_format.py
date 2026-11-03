"""CapCut Desktop 초안 JSON 조각들 (파일 포맷을 아는 유일한 모듈). CapCut 9.x 에서 열리는 것을 확인한 구현이다.

Format notes (independently re-implemented, no code copied):
- time unit: microseconds; positions: `clip.transform` in half-canvas units (x right+, y UP+);
  `clip.scale` relative to CapCut's default "fit inside canvas" placement.
- draft folder layout + registration (draft_content.json / draft_info.json / Timelines/<id>/ /
  draft_meta_info.json / root_meta_info.json) follow clipcraft-labs/capcut-draft (MIT, verified on
  CapCut Desktop 9.1). Field names/semantics of segments, text styles, keyframes, speeds, audio fades and
  transitions were cross-checked against the public format notes of GuanYixuan/pyCapCut (Windows CapCut 6.7)
  and CapCutAPI; neither of those two ships a license, so nothing was copied from them.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

US = 1_000_000

# empty material groups a fresh CapCut draft carries (from capcut-draft, MIT)
MATERIAL_GROUPS = (
    "flowers", "videos", "tail_leaders", "audios", "images", "texts", "effects", "stickers", "canvases",
    "transitions", "audio_effects", "audio_fades", "beats", "material_animations", "placeholders",
    "placeholder_infos", "speeds", "common_mask", "chromas", "text_templates", "realtime_denoises",
    "audio_pannings", "audio_pitch_shifts", "video_trackings", "hsl", "drafts", "color_curves", "hsl_curves",
    "primary_color_wheels", "log_color_wheels", "video_effects", "ai_text_effects", "audio_balances",
    "handwrites", "manual_deformations", "manual_beautys", "plugin_effects", "sound_channel_mappings",
    "green_screens", "shapes", "material_colors", "digital_humans", "digital_human_model_dressing",
    "smart_crops", "ai_translates", "audio_track_indexes", "loudnesses", "vocal_beautifys",
    "vocal_separations", "smart_relights", "time_marks", "multi_language_refs", "video_shadows",
    "video_strokes", "video_radius",
)

# render_index bases per track type (higher = closer to the viewer)
RENDER_BASE = {"video": 0, "audio": 0, "effect": 10000, "filter": 11000, "sticker": 14000, "text": 15000}


def us(seconds: float) -> int:
    return int(round(max(0.0, seconds) * US))


def uid() -> str:
    return str(uuid.uuid4()).upper()


def timerange(start_us: int, duration_us: int) -> dict:
    return {"start": int(start_us), "duration": int(max(1, duration_us))}


def rgb01(hex_color: str) -> list[float]:
    c = (hex_color or "#FFFFFF").lstrip("#")
    return [round(int(c[i:i + 2], 16) / 255.0, 6) for i in (0, 2, 4)]


def empty_materials() -> dict[str, list]:
    return {k: [] for k in MATERIAL_GROUPS}


# ---------------------------------------------------------------- materials
def video_material(mid: str, path: str, *, kind: str, duration_us: int, width: int, height: int, name: str) -> dict:
    return {
        "id": mid, "material_id": mid, "local_material_id": "", "type": kind,  # "video" | "photo"
        "path": path, "media_path": "", "material_name": name, "name": name,
        "duration": int(duration_us), "width": int(width), "height": int(height),
        "category_id": "", "category_name": "local", "check_flag": 63487,
        "crop": {"upper_left_x": 0.0, "upper_left_y": 0.0, "upper_right_x": 1.0, "upper_right_y": 0.0,
                 "lower_left_x": 0.0, "lower_left_y": 1.0, "lower_right_x": 1.0, "lower_right_y": 1.0},
        "crop_ratio": "free", "crop_scale": 1.0, "audio_fade": None, "remote_url": None,
        "has_audio": kind == "video",
    }


def audio_material(mid: str, path: str, *, duration_us: int, name: str) -> dict:
    return {
        "id": mid, "local_material_id": mid, "music_id": mid, "type": "extract_music", "path": path, "name": name,
        "duration": int(duration_us), "app_id": 0, "category_id": "", "category_name": "local", "check_flag": 3,
        "copyright_limit_type": "none", "effect_id": "", "formula_id": "", "source_platform": 0, "wave_points": [],
    }


def speed_material(speed: float) -> dict:
    return {"id": uid(), "type": "speed", "mode": 0, "speed": float(speed), "curve_speed": None}


def audio_fade(fade_in_us: int, fade_out_us: int) -> dict:
    return {"id": uid(), "type": "audio_fade", "fade_type": 0,
            "fade_in_duration": int(fade_in_us), "fade_out_duration": int(fade_out_us)}


def transition_material(spec: dict, duration_us: int) -> dict:
    return {"id": uid(), "type": "transition", "name": spec["name"], "effect_id": spec["effect_id"],
            "resource_id": spec["resource_id"], "duration": int(duration_us), "is_overlap": bool(spec.get("is_overlap", True)),
            "category_id": "", "category_name": "", "platform": "all"}


def _color_pieces(text_len: int, base: str, runs: list[tuple[int, int, str]] | None) -> list[tuple[int, int, str]]:
    """[0, text_len] 을 빈틈·겹침 없이 순서대로 덮는 (시작, 끝, 색) 조각. 구간 밖은 기본색. 범위 밖·역순·겹치는 부분은 잘라 낸다."""
    pieces: list[tuple[int, int, str]] = []
    pos = 0
    for a, b, col in sorted(runs or [], key=lambda r: (r[0], r[1])):
        a, b = max(int(a), pos), min(int(b), text_len)
        if b <= a:
            continue
        if a > pos:
            pieces.append((pos, a, base))
        pieces.append((a, b, col))
        pos = b
    if pos < text_len or not pieces:
        pieces.append((pos, text_len, base))
    return pieces


def text_material(text: str, *, size: float, color: str, alpha: float = 1.0, bold: bool = False, italic: bool = False,
                  font_path: str = "", font_name: str = "", stroke: tuple[str, float] | None = None,
                  background: dict | None = None, shadow: dict | None = None, align: int = 1,
                  max_line_width: float = 0.82, auto_wrap: bool = False, line_spacing: float = 0.02,
                  color_runs: list[tuple[int, int, str]] | None = None) -> dict:
    """stroke = (hex, width 0..0.2 draft units); background = {color, alpha, round, height, width}; shadow = {...}.
    color_runs = [(시작, 끝, hex)] — 글자 구간별 색(파이썬 len 단위, [시작, 끝)). 구간마다 style 이 하나씩 생기고 모두 같은 서식에 range·색만 다르다."""
    def style_for(rng: list[int], col: str) -> dict[str, Any]:
        style: dict[str, Any] = {
            "fill": {"alpha": 1.0, "content": {"render_type": "solid", "solid": {"alpha": 1.0, "color": rgb01(col)}}},
            "range": rng, "size": round(float(size), 2), "bold": bold, "italic": italic, "underline": False,
            "strokes": [{"content": {"solid": {"alpha": 1.0, "color": rgb01(stroke[0])}}, "width": round(stroke[1], 4)}] if stroke else [],
        }
        if font_path:
            style["font"] = {"id": "", "path": font_path}
        if shadow:
            style["shadows"] = [{"diffuse": shadow.get("diffuse", 0.025), "alpha": shadow.get("alpha", 0.8),
                                 "distance": shadow.get("distance", 5.0), "angle": shadow.get("angle", -45.0),
                                 "content": {"solid": {"color": rgb01(shadow.get("color", "#000000"))}}}]
        return style

    if color_runs:
        styles = [style_for([a, b], col) for a, b, col in _color_pieces(len(text), color, color_runs)]
    else:
        styles = [style_for([0, len(text)], color)]
    check_flag = 7 | (8 if stroke else 0) | (16 if background else 0) | (32 if shadow else 0)
    mat: dict[str, Any] = {
        "id": uid(), "type": "subtitle" if auto_wrap else "text",
        "content": json.dumps({"styles": styles, "text": text}, ensure_ascii=False),
        "typesetting": 0, "alignment": align, "letter_spacing": 0.0, "line_spacing": line_spacing, "line_feed": 1,
        "line_max_width": round(max_line_width, 4), "force_apply_line_max_width": False,
        "check_flag": check_flag, "global_alpha": alpha,
        # redundant flat fields some CapCut builds read for the inspector
        "font_size": round(float(size), 2), "text_size": round(float(size), 2), "text_color": color,
        "font_name": font_name, "font_path": font_path, "bold_width": 0.0, "italic_degree": 0,
        "border_color": stroke[0] if stroke else "", "border_width": round(stroke[1], 4) if stroke else 0.0,
        "has_shadow": bool(shadow), "text_alpha": alpha, "underline": False,
    }
    if background:
        mat.update({
            "background_style": 1, "background_color": background["color"], "background_alpha": background.get("alpha", 1.0),
            "background_round_radius": background.get("round", 0.25), "background_height": background.get("height", 0.14),
            "background_width": background.get("width", 0.14),
            "background_horizontal_offset": 0.0, "background_vertical_offset": 0.0,
        })
    return mat


# ---------------------------------------------------------------- segments / keyframes
def keyframes(prop: str, points: list[tuple[int, float]]) -> dict:
    """prop: KFTypePositionX/Y (half-canvas units), KFTypeScaleX (uniform), KFTypeRotation, KFTypeAlpha, KFTypeVolume."""
    return {"id": uid(), "material_id": "", "property_type": prop,
            "keyframe_list": [{"id": uid(), "curveType": "Line", "graphID": "", "left_control": {"x": 0.0, "y": 0.0},
                               "right_control": {"x": 0.0, "y": 0.0}, "time_offset": int(t), "values": [float(v)]}
                              for t, v in sorted(points)]}


def clip_settings(*, scale: float = 1.0, tx: float = 0.0, ty: float = 0.0, alpha: float = 1.0, rotation: float = 0.0) -> dict:
    return {"alpha": alpha, "flip": {"horizontal": False, "vertical": False}, "rotation": rotation,
            "scale": {"x": round(scale, 6), "y": round(scale, 6)}, "transform": {"x": round(tx, 6), "y": round(ty, 6)}}


def segment(material_id: str, target: dict, *, source: dict | None = None, speed: float = 1.0, volume: float = 1.0,
            clip: dict | None = None, extra_refs: list[str] | None = None, common_keyframes: list[dict] | None = None,
            visual: bool = True) -> dict:
    seg: dict[str, Any] = {
        "id": uid(), "material_id": material_id, "target_timerange": target, "source_timerange": source,
        "speed": float(speed), "volume": float(volume), "last_nonzero_volume": float(volume) if volume > 0 else 1.0,
        "extra_material_refs": list(extra_refs or []), "common_keyframes": list(common_keyframes or []), "keyframe_refs": [],
        "visible": True, "reverse": False, "track_attribute": 0, "track_render_index": 0, "render_index": 0,
        "enable_adjust": True, "enable_color_correct_adjust": False, "enable_color_curves": True,
        "enable_color_match_adjust": False, "enable_color_wheels": True, "enable_lut": True, "enable_smart_color_adjust": False,
    }
    if visual:
        seg["clip"] = clip or clip_settings()
        seg["uniform_scale"] = {"on": True, "value": 1.0}
        seg["hdr_settings"] = {"intensity": 1.0, "mode": 1, "nits": 1000}
    else:
        seg["clip"] = None
        seg["hdr_settings"] = None
    return seg


def track(kind: str, name: str, segments: list[dict], *, lane: int = 0, mute: bool = False) -> dict:
    ri = RENDER_BASE.get(kind, 0) + lane
    for sg in segments:
        sg["render_index"] = ri
    return {"id": uid(), "type": kind, "name": name, "is_default_name": not name, "attribute": int(mute), "flag": 0,
            "segments": segments}


# ---------------------------------------------------------------- draft files
def _config() -> dict:
    return {
        "video_mute": False, "record_audio_last_index": 1, "extract_audio_last_index": 1, "original_sound_last_index": 1,
        "subtitle_recognition_id": "", "subtitle_taskinfo": [], "lyrics_recognition_id": "", "lyrics_taskinfo": [],
        "subtitle_sync": True, "lyrics_sync": True, "voice_change_sync": False, "sticker_max_index": 1,
        "adjust_max_index": 1, "material_save_mode": 0, "export_range": None, "maintrack_adsorb": True,
        "combination_max_index": 1, "attachment_info": [], "zoom_info_params": None, "system_font_list": [],
        "multi_language_mode": "none", "multi_language_main": "none", "multi_language_current": "none",
        "multi_language_list": [], "subtitle_keywords_config": None, "use_float_render": False,
    }


def draft_content(*, draft_id: str, name: str, width: int, height: int, fps: float, duration_us: int, tracks: list[dict],
                  materials: dict, draft_path: str, os_name: str, app_version: str, new_version: str) -> dict:
    now = int(time.time() * US)
    platform = {"app_id": 359289, "app_source": "cc", "app_version": app_version, "os": os_name, "os_version": "",
                "device_id": "", "hard_disk_id": "", "mac_address": ""}
    return {
        "id": draft_id, "version": 360000, "new_version": new_version, "name": name, "duration": int(duration_us),
        "create_time": now // US, "update_time": now // US, "fps": float(fps), "is_drop_frame_timecode": False,
        "color_space": 0, "config": _config(),
        "canvas_config": {"width": width, "height": height, "ratio": "original", "background": None},
        "tracks": tracks, "group_container": None, "materials": materials,
        "keyframes": {k: [] for k in ("videos", "audios", "texts", "stickers", "filters", "adjusts", "handwrites", "effects")},
        "keyframe_graph_list": [], "platform": platform, "last_modified_platform": dict(platform),
        "mutable_config": None, "cover": None, "retouch_cover": None, "extra_info": None, "relationships": [],
        "mixed_track_mode_on": False, "render_index_track_mode_on": False, "free_render_index_mode_on": False,
        "static_cover_image_path": "", "source": "default", "time_marks": None, "path": draft_path,
        "lyrics_effects": [], "uneven_animation_template_info": {}, "draft_type": "video",
        "smart_ads_info": {}, "function_assistant_info": {},
    }


def meta_info(*, draft_id: str, name: str, fold_path: str, root_path: str, duration_us: int, new_version: str,
              imported: list[dict], cover: str = "draft_cover.jpg") -> dict:
    now = int(time.time() * US)
    groups = [{"type": t, "value": []} for t in (0, 1, 2, 3, 6, 7, 8)]
    groups[0]["value"] = [{
        "id": m["id"], "type": 0, "metetype": m["metetype"], "file_Path": m["path"], "extra_info": m["name"],
        "duration": m["duration_us"], "width": m.get("width", 0), "height": m.get("height", 0),
        "create_time": now // US, "import_time": now // US, "import_time_ms": now, "item_source": 1, "md5": "",
        "roughcut_time_range": {"duration": -1, "start": -1}, "sub_time_range": {"duration": -1, "start": -1},
    } for m in imported]
    return {
        "cloud_draft_cover": False, "cloud_draft_sync": False, "draft_cloud_last_action_download": False,
        "draft_cover": cover, "draft_fold_path": fold_path, "draft_id": draft_id, "draft_name": name,
        "draft_root_path": root_path, "draft_new_version": new_version, "draft_is_invisible": False,
        "draft_need_rename_folder": False, "draft_is_from_deeplink": "false", "draft_is_ai_shorts": False,
        "draft_materials": groups, "draft_materials_copied_info": [], "draft_segment_extra_info": [],
        "draft_removable_storage_device": "", "draft_timeline_materials_size_": 0, "draft_type": "",
        "draft_enterprise_info": {"draft_enterprise_extra": "", "draft_enterprise_id": "", "draft_enterprise_name": "",
                                  "enterprise_material": []},
        "tm_draft_create": now, "tm_draft_modified": now, "tm_draft_removed": 0, "tm_duration": int(duration_us),
        "tm_draft_cloud_completed": "", "tm_draft_cloud_modified": 0,
    }


ATTACHMENT_PC_COMMON = {"ai_packaging_infos": [], "ai_packaging_report_info": {}, "broll": [],
                        "commercial_music_category_ids": [], "pc_feature_flag": {}, "recognize_tasks": [],
                        "reference_lines_config": {}, "safe_area_type": 0, "template_item_infos": [],
                        "unlock_template_ids": []}
PERFORMANCE_OPT = {"manual_cancle_precombine_segs": [], "need_auto_precombine_segs": []}
