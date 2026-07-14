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
  } | null;
};

export type SubtitleCue = {
  text: string;
  start_frame: number;
  end_frame: number;
  slot: string;
  emphasize?: string | null;
};

export type TimelineProps = {
  width: number;
  height: number;
  fps: number;
  frame_count: number;
  assets: RenderAsset[];
  shots: RenderShot[];
  subtitles: SubtitleCue[];
  style?: Record<string, unknown>;
};
