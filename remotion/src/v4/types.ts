export type V4Layout = {
  x: number;
  y: number;
  width: number;
  height: number;
  fit: "contain" | "cover";
  border_radius: number;
  opacity: number;
  background_style_id: string;
  safe_area_profile_id: string;
};

export type V4RenderAsset = {
  asset_ref: string;
  object_key: string;
  sha256: string;
  media_kind: "image" | "video";
  width: number;
  height: number;
  duration_ms: number | null;
  has_alpha: boolean;
};

export type V4OrderedItem = {
  item_id: string;
  asset_binding_name: string;
  member_key: string | null;
  start_frame: number;
  end_frame: number;
  hit_frame: number;
};

export type V4Clip = {
  clip_id: string;
  scene_id: string;
  slot_id: string | null;
  group_ref: string | null;
  member_key: string | null;
  asset_bindings: Record<string, string>;
  ordered_items?: V4OrderedItem[];
  start_frame: number;
  end_frame: number;
  semantic_hit_frame: number;
  hold_reason: string | null;
  layout_profile_id: string;
  layout: V4Layout;
  effect_instance_id: string;
  z_index: number;
};

export type V4EffectEvent = {
  event_id: string;
  event_type: string;
  anchor_id: string;
  hit_frame: number;
  start_frame: number;
  end_frame: number;
};

export type V4EffectInstance = {
  effect_instance_id: string;
  effect_id: string;
  effect_version: string;
  adapter_id: string;
  variant_id: "full" | "compact" | "instant";
  direction: "none" | "left" | "right" | "up" | "down";
  parameters: Record<string, unknown>;
  events: V4EffectEvent[];
};

export type V4EffectProps = {
  effect_instance_id: string;
  effect_id: string;
  effect_version: string;
  variant_id: "full" | "compact" | "instant";
  start_frame: number;
  end_frame: number;
  events: V4EffectEvent[];
  direction: "none" | "left" | "right" | "up" | "down";
  layout: V4Layout;
  parameters: Record<string, unknown>;
  assets: Record<string, string>;
  ordered_items: V4OrderedItem[];
};

export type V4PixelRect = {
  x: number;
  y: number;
  w: number;
  h: number;
};

export type V4PlatformProfileProps = {
  profile_id: string;
  canvas: V4PixelRect;
  subtitle_top: V4PixelRect;
  subtitle_lower: V4PixelRect;
  subtitle_font_px: number;
};

export type V4SubtitleCue = {
  cue_id: string;
  scene_id: string;
  anchor_id: string | null;
  text: string;
  start_frame: number;
  end_frame: number;
  slot_id: "subtitle_top" | "subtitle_lower";
  style_id: "default" | "gallery_yellow";
  emphasize_text: string | null;
  emphasize_start_frame: number | null;
  single_line: true;
};

export type V4TimelineProps = {
  composition_id: string;
  schema_version: number;
  case_id: string;
  run_id: string;
  width: number;
  height: number;
  fps: number;
  frame_count: number;
  platform_profile_id: string;
  platform_profile: V4PlatformProfileProps;
  render_assets: V4RenderAsset[];
  visual_tracks: Array<{track_id: string; track_kind: "base" | "overlay"; clips: V4Clip[]}>;
  effect_instances: V4EffectInstance[];
  effect_props: V4EffectProps[];
  subtitle_track: V4SubtitleCue[];
  audio_tracks: unknown[];
};
