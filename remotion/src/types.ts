export type RenderAsset = {
  asset_id: string;
  path: string;
  width: number;
  height: number;
  media_type: string;
  accent_color?: string | null;
};

export type RenderShot = {
  shot_id: string;
  scene_id?: string | null;
  scene_kind?: string | null;
  track: "base" | "overlay";
  template: string;
  asset_bindings: Record<string, string>;
  start_frame: number;
  end_frame: number;
  motion: string;
  transition_in: { kind: string; duration_frames: number };
  overlay_layout?: { x: number; y: number; w: number; h: number; fit: string; opacity: number; z_index: number } | null;
  parameter_sequence?: {
    base_asset_id: string;
    stage_asset_id: string;
    final_asset_id: string;
    start_frame: number;
    stage_frame: number;
    hit_frame: number;
    crossfade_frames: number;
    callout_reveal_frames?: number;
    required_field_labels?: string[];
    callout_text?: string;
  } | null;
  editor_flow_sequence?: {
    sequence_id: string;
    page_asset_id: string;
    modal_asset_id: string;
    focus_frame: number;
    modal_frame: number;
    focus_x: number;
    focus_y: number;
    focus_w: number;
    focus_h: number;
    lens_zoom: number;
    reveal_frames: number;
  } | null;
  gallery_items?: { asset_id: string; phrase: string; anchor_id: string; hit_frame: number; onset_frame?: number | null }[];
};

export type SubtitleCue = {
  text: string;
  start_frame: number;
  end_frame: number;
  slot: string;
  emphasize?: string | null;
  style?: "default" | "gallery_yellow";
};

export type TimelineProps = {
  width: number;
  height: number;
  fps: number;
  frame_count: number;
  assets: RenderAsset[];
  shots: RenderShot[];
  subtitles: SubtitleCue[];
  style?: {
    safe_area?: {
      content?: {x: number; y: number; w: number; h: number};
      critical?: {x: number; y: number; w: number; h: number};
      subtitle_top?: {x: number; y: number; w: number; h: number};
      subtitle_lower?: {x: number; y: number; w: number; h: number};
    };
    [key: string]: unknown;
  };
};
